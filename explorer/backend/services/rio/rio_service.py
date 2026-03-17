"""
services/rio/rio_service.py — Download ROS bags from Rapyuta IO.

Supports two acquisition paths:
  1. Shared URL download (gaapiserver links)
  2. Device upload download (via `rio` CLI subprocess)

Token resolution order:
  1. RAPYUTA_TOKEN / RAPYUTA_ORGANIZATION / RAPYUTA_PROJECT env vars
  2. ~/.config/rio-cli/config.json (auth_token, organization_id, project_id)
  3. ~/.rapyuta_token (legacy — token only)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import pathlib
import tempfile
import uuid
from urllib.parse import urlparse
from urllib.request import Request, HTTPRedirectHandler, build_opener
from urllib.error import HTTPError

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

_LEGACY_TOKEN_FILE = pathlib.Path.home() / ".rapyuta_token"
_SHARED_URL_PATTERN = re.compile(r'^https://gaapiserver[^\s]+/sharedurl/[^\s]+$')
_SAFE_NAME_PATTERN = re.compile(r'^[A-Za-z0-9._-]+$')
_MAX_FILENAME_LEN = 200


# ── Exceptions ─────────────────────────────────────────────────────────────────

class RioNotConfiguredError(Exception):
    """Raised when no RIO auth token can be found."""


class RioConfigMalformedError(Exception):
    """Raised when the rio config file exists but is unparseable."""


# ── Redirect handler ──────────────────────────────────────────────────────────

class _SafeAuthRedirectHandler(HTTPRedirectHandler):
    """Strip Authorization header when redirecting to a different domain.

    gaapiserver redirects to S3 for the actual file download; S3 rejects
    requests that carry a Bearer token with HTTP 400.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is None:
            return None
        old_host = urlparse(req.full_url).hostname
        new_host = urlparse(newurl).hostname
        if old_host != new_host:
            new_req.remove_header("Authorization")
        return new_req


_opener = build_opener(_SafeAuthRedirectHandler)


# ── Config resolution ─────────────────────────────────────────────────────────

def get_rio_config() -> dict:
    """Load RIO credentials.  Returns dict with auth_token, organization_id, project_id.

    Raises RioNotConfiguredError if no auth_token is found after all sources.
    Raises RioConfigMalformedError if the config file exists but cannot be parsed.
    """
    result = {
        "auth_token": os.environ.get("RAPYUTA_TOKEN", "").strip(),
        "organization_id": os.environ.get("RAPYUTA_ORGANIZATION", "").strip(),
        "project_id": os.environ.get("RAPYUTA_PROJECT", "").strip(),
    }

    config_path = pathlib.Path(settings.rio_config_path)
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            if not result["auth_token"]:
                result["auth_token"] = config.get("auth_token", "").strip()
            if not result["organization_id"]:
                result["organization_id"] = config.get("organization_id", "").strip()
            if not result["project_id"]:
                result["project_id"] = config.get("project_id", "").strip()
        except (json.JSONDecodeError, KeyError):
            raise RioConfigMalformedError(
                "RIO config file is malformed. Re-run 'rio auth login'."
            )

    if not result["auth_token"] and _LEGACY_TOKEN_FILE.exists():
        try:
            result["auth_token"] = _LEGACY_TOKEN_FILE.read_text().strip()
        except OSError:
            pass

    if not result["auth_token"]:
        raise RioNotConfiguredError(
            "RIO not configured. Run 'rio auth login' on this server."
        )

    return result


def get_rio_config_safe() -> dict:
    """Like get_rio_config but returns empty values instead of raising."""
    try:
        return get_rio_config()
    except (RioNotConfiguredError, RioConfigMalformedError):
        return {"auth_token": "", "organization_id": "", "project_id": ""}


def is_rio_cli_available() -> bool:
    """Return True if the `rio` CLI binary is on PATH."""
    return shutil.which("rio") is not None


# ── Filename sanitization ─────────────────────────────────────────────────────

def _sanitize_filename(raw: str) -> str:
    """Sanitize a filename for safe filesystem storage.

    Rejects path separators, .., null bytes; caps length.
    Raises ValueError if the result is empty or unsafe.
    """
    if not raw or "\x00" in raw:
        raise ValueError("Invalid filename.")
    # Strip any directory components
    name = pathlib.PurePosixPath(raw).name
    name = pathlib.PureWindowsPath(name).name
    if not name or ".." in name:
        raise ValueError("Invalid filename.")
    # Collapse unsafe chars to underscore, keep word chars, dots, hyphens
    name = re.sub(r"[^\w.\-]+", "_", name).strip("_")
    if not name:
        raise ValueError("Invalid filename.")
    return name[:_MAX_FILENAME_LEN]


# ── URL validation ─────────────────────────────────────────────────────────────

def _validate_shared_url(url: str) -> None:
    """Ensure the URL matches the gaapiserver shared URL pattern (SSRF protection)."""
    if not _SHARED_URL_PATTERN.match(url):
        raise ValueError("URL must be a gaapiserver shared URL.")


def _validate_safe_name(value: str, label: str = "value") -> None:
    """Validate that a string contains only safe characters [A-Za-z0-9._-]."""
    if not value or not _SAFE_NAME_PATTERN.match(value):
        raise ValueError(f"Invalid {label}.")


# ── Shared URL download ───────────────────────────────────────────────────────

def download_shared_url(url: str, project_override: str = "") -> pathlib.Path:
    """Download a bag from a gaapiserver shared URL.

    Returns the local Path after writing to bag_upload_dir.
    Raises ValueError for invalid URLs / filenames.
    Raises RioNotConfiguredError / RioConfigMalformedError for config issues.
    Raises RuntimeError for HTTP / network failures.
    """
    _validate_shared_url(url)

    rio = get_rio_config()
    project = project_override.strip() or rio["project_id"]
    if project_override:
        _validate_safe_name(project_override, "project_override")

    dest_dir = pathlib.Path(settings.bag_upload_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Derive initial filename from URL slug
    slug = url.rstrip("/").split("/")[-1]

    req = Request(url)
    req.add_header("Authorization", f"Bearer {rio['auth_token']}")
    if rio["organization_id"]:
        req.add_header("organization", rio["organization_id"])
    if project:
        req.add_header("project", project)

    try:
        with _opener.open(req) as resp:
            # Resolve filename from Content-Disposition, fallback to slug
            fname = slug
            cd = resp.headers.get("Content-Disposition", "")
            if "filename=" in cd:
                match = re.search(r'filename="?([^";]+)"?', cd)
                if match:
                    fname = match.group(1)

            data = resp.read()
    except HTTPError as e:
        raise RuntimeError(
            f"Upstream error: {e.code} {e.reason}"
        ) from e

    safe_name = _sanitize_filename(fname)
    dest = dest_dir / safe_name
    if dest.exists():
        stem, suffix = dest.stem, dest.suffix
        dest = dest_dir / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"

    dest.write_bytes(data)
    logger.info("Downloaded from RIO shared URL: %s (%d bytes)", dest.name, len(data))
    return dest


# ── Device upload download ─────────────────────────────────────────────────────

def download_device_upload(
    device: str,
    filename: str,
    project_override: str = "",
) -> pathlib.Path:
    """Download a bag from a RIO device via `rio device uploads download`.

    Returns the local Path after moving to bag_upload_dir.
    Raises ValueError for invalid device/filename.
    Raises RioNotConfiguredError / RioConfigMalformedError for config issues.
    Raises FileNotFoundError if rio CLI is not installed.
    Raises subprocess.TimeoutExpired on timeout.
    Raises RuntimeError on subprocess failure.
    """
    _validate_safe_name(device, "device name")
    _validate_safe_name(filename, "filename")
    if project_override:
        _validate_safe_name(project_override, "project_override")

    # Ensure RIO is configured (validates token exists)
    get_rio_config()

    if not is_rio_cli_available():
        raise FileNotFoundError("rio CLI is not installed on this server.")

    dest_dir = pathlib.Path(settings.bag_upload_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    saved_project: str | None = None
    try:
        # Optionally switch project
        if project_override:
            saved_project = _get_current_project()
            subprocess.run(
                ["rio", "project", "select", project_override],
                timeout=30,
                check=True,
                capture_output=True,
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            subprocess.run(
                ["rio", "device", "uploads", "download", device, filename],
                cwd=tmp_dir,
                timeout=settings.rio_download_timeout,
                check=True,
                capture_output=True,
            )

            # Find the downloaded file in tmp_dir
            downloaded = list(pathlib.Path(tmp_dir).iterdir())
            if not downloaded:
                raise RuntimeError("rio CLI completed but no file was downloaded.")
            src = downloaded[0]

            safe_name = _sanitize_filename(src.name)
            dest = dest_dir / safe_name
            if dest.exists():
                stem, suffix = dest.stem, dest.suffix
                dest = dest_dir / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"

            shutil.move(str(src), str(dest))

    except subprocess.TimeoutExpired:
        raise
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="replace").strip() if e.stderr else ""
        raise RuntimeError(f"Device download failed: {stderr or 'unknown error'}") from e
    finally:
        # Restore original project if we switched
        if saved_project:
            try:
                subprocess.run(
                    ["rio", "project", "select", saved_project],
                    timeout=30,
                    check=False,
                    capture_output=True,
                )
            except Exception:
                logger.warning("Failed to restore RIO project to %s", saved_project)

    logger.info("Downloaded from RIO device: %s (%d bytes)", dest.name, dest.stat().st_size)
    return dest


def _get_current_project() -> str:
    """Read the currently selected project from rio config."""
    try:
        config = get_rio_config()
        return config.get("project_id", "")
    except (RioNotConfiguredError, RioConfigMalformedError):
        return ""
