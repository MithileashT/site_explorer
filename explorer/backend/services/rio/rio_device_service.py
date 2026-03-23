"""
RIO Device Service — trigger rosbag uploads from RIO-managed devices.

Provides stateless functions to:
  - List projects accessible to the configured RIO user
  - List online devices in a project
  - Discover rosbags on a device within a time range
  - Trigger tar+compress+upload of rosbags from device to RIO cloud

Supports background parallel uploads with per-device event streaming.

Reuses auth from rio_service.get_rio_config() and matches the proven
upload pattern from rosbag_slack_app/rio_helper.py.
"""
from __future__ import annotations

import os
import re
import threading
import time
import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from rapyuta_io import Client as RioV1Client
from rapyuta_io.clients import LogsUploadRequest
from rapyuta_io.clients.model import Command
from rapyuta_io_sdk_v2.utils import walk_pages
from riocli.config import Configuration

from core.logging import get_logger
from .rio_service import get_rio_config

logger = get_logger(__name__)

FILE_DATE_FORMAT = "%Y_%m_%d_%H_%M_%S"
ROSBAG_DATE_FORMAT = "%Y-%m-%d-%H-%M-%S"
SITE_CODE_PATTERN = re.compile(r"^[a-zA-Z]{3}-[a-zA-Z]{3}-[0-9]{3}$")

# TTL for cleaning up old jobs (seconds)
_JOB_TTL = 7200  # 2 hours


@dataclass
class BagInfo:
    """Holds the path and parsed timestamps for a single discovered rosbag."""
    path: str
    file_start: datetime  # UTC, parsed from filename
    file_end: datetime    # device-local tz, parsed from mtime


def build_tar_filename(
    device_name: str,
    display_start: str,
    display_end: str,
    timezone_label: str,
    fallback_start: Optional[datetime] = None,
    fallback_end: Optional[datetime] = None,
) -> str:
    """Build a tar filename that reflects the user's timezone perspective.

    If display_start/display_end/timezone_label are provided (non-empty), uses
    them to produce:
        /tmp/rosbags_<start>_to_<end>_<tz>.tar.xz
    where colons and 'T' separators are replaced with dashes.

    Falls back to the old UTC-epoch-based format if display strings are missing.
    """
    if display_start and display_end and timezone_label:
        def _fmt(dt_local: str) -> str:
            # "2026-03-22T10:00" → "2026-03-22_10-00"
            return dt_local.replace("T", "_").replace(":", "-")

        return (
            f"/tmp/rosbags"
            f"_{_fmt(display_start)}"
            f"_to_{_fmt(display_end)}"
            f"_{timezone_label}.tar.xz"
        )

    # Fallback: legacy UTC-based naming
    assert fallback_start is not None and fallback_end is not None
    return (
        f"/tmp/{device_name}"
        f"-{fallback_start.strftime(FILE_DATE_FORMAT)}"
        f"-{fallback_end.strftime(FILE_DATE_FORMAT)}.tar.xz"
    )


def build_actual_tar_filename(
    device_name: str,
    site_name: str,
    bags: "List[BagInfo]",
    utc_offset_minutes: int,
) -> str:
    """Build a tar filename using the actual bag timestamps, shifted to user's TZ.

    The filename reflects the true data range (second-precision), not user-input times.
    Format: /tmp/{device_name}-{site_name}-YYYY_MM_DD_HH_MM_SS-YYYY_MM_DD_HH_MM_SS.tar.xz
    """
    offset = timedelta(minutes=utc_offset_minutes)
    actual_start_utc = min(b.file_start for b in bags)
    actual_end_utc = max(b.file_end.astimezone(timezone.utc) for b in bags)
    actual_start_local = actual_start_utc + offset
    actual_end_local = actual_end_utc + offset
    prefix = f"{device_name}-{site_name}" if site_name else device_name
    return (
        f"/tmp/{prefix}"
        f"-{actual_start_local.strftime(FILE_DATE_FORMAT)}"
        f"-{actual_end_local.strftime(FILE_DATE_FORMAT)}.tar.xz"
    )


class RioDeviceError(Exception):
    """Raised on RIO device operation failures."""


# ── Client factories ─────────────────────────────────────────────────────────

def _get_v1_client() -> RioV1Client:
    """Create a rapyuta_io v1 Client from current config."""
    config = get_rio_config()
    cfg = Configuration()
    cfg.data["auth_token"] = config["auth_token"]
    cfg.data["project_id"] = config.get("project_id", "")
    cfg.data["organization_id"] = config.get("organization_id", "")
    return cfg.new_client()


def _get_v2_client():
    """Create a rapyuta_io v2 Client from current config."""
    config = get_rio_config()
    cfg = Configuration()
    cfg.data["auth_token"] = config["auth_token"]
    cfg.data["project_id"] = config.get("project_id", "")
    cfg.data["organization_id"] = config.get("organization_id", "")
    client = cfg.new_v2_client()
    # SDK 0.4.0 bug: User-Agent includes platform.version() which can
    # contain chars illegal in HTTP headers (e.g. '#', newlines).
    raw_ua = client.c.headers.get("user-agent", "")
    client.c.headers["user-agent"] = re.sub(r"[^\x21-\x7E ]+", "", raw_ua).strip()
    return client


# ── Project / device listing ─────────────────────────────────────────────────

def _list_projects_for_org(org_id: str) -> List:
    """Return raw project objects scoped to the given organization ID.

    Uses the same auth_token as the primary config but overrides org context.
    project_id is cleared so the SDK does not restrict by project scope.
    """
    config = get_rio_config()
    cfg = Configuration()
    cfg.data["auth_token"] = config["auth_token"]
    cfg.data["organization_id"] = org_id
    cfg.data["project_id"] = ""
    v2 = cfg.new_v2_client()
    raw_ua = v2.c.headers.get("user-agent", "")
    v2.c.headers["user-agent"] = re.sub(r"[^\x21-\x7E ]+", "", raw_ua).strip()
    results: List = []
    for page in walk_pages(v2.list_projects):
        results.extend(page)
    return results


def list_projects() -> List[Dict[str, str]]:
    """List all site-code projects accessible to the configured RIO user.

    Queries the primary organization from config and any extra organizations
    listed in RAPYUTA_EXTRA_ORGANIZATIONS (format: "guid:Label" comma-separated).
    Results from all orgs are merged, deduplicated by project GUID, and sorted
    first by org_name then by project name.

    Each returned dict has: {name, guid, organization_guid, org_name}.
    """
    from core.config import settings  # local import avoids circular dependency

    # Primary org
    config = get_rio_config()
    primary_org_name = config.get("organization_name", "") or ""
    v2 = _get_v2_client()
    all_raw: List = []
    for page in walk_pages(v2.list_projects):
        for p in page:
            p._org_name = primary_org_name
            all_raw.append(p)

    # Extra orgs — parse "guid:Label" pairs
    for entry in settings.rio_extra_organizations.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            org_id, org_label = entry.split(":", 1)
            org_id = org_id.strip()
            org_label = org_label.strip()
        else:
            org_id = entry
            org_label = entry  # fallback: use guid as label
        try:
            for p in _list_projects_for_org(org_id):
                p._org_name = org_label
                all_raw.append(p)
        except Exception as exc:
            logger.warning("Failed to list projects for org %s: %s", org_id, exc)

    # Deduplicate by GUID (same project may be visible in multiple org scopes)
    seen: set = set()
    unique: List = []
    for p in all_raw:
        guid = getattr(p.metadata, "guid", "")
        if guid and guid not in seen:
            seen.add(guid)
            unique.append(p)

    return sorted(
        [
            {
                "name": p.metadata.name,
                "guid": p.metadata.guid,
                "organization_guid": getattr(p.metadata, "organizationGUID", ""),
                "org_name": getattr(p, "_org_name", ""),
            }
            for p in unique
            if SITE_CODE_PATTERN.match(p.metadata.name)
            or p.metadata.name.startswith("rr-")
        ],
        key=lambda x: (x["org_name"].lower(), x["name"].lower()),
    )


def get_project_name_by_guid(project_guid: str) -> str:
    """Resolve RIO project name from project GUID.

    Used as a backend fallback for tar naming when frontend does not send
    site_code. Returns empty string when the project cannot be resolved.
    Searches the primary org first, then any extra orgs from settings.
    """
    if not project_guid:
        return ""

    # Search primary org first
    try:
        v2 = _get_v2_client()
        for page in walk_pages(v2.list_projects):
            for project in page:
                meta = getattr(project, "metadata", None)
                if not meta:
                    continue
                if getattr(meta, "guid", "") == project_guid:
                    return getattr(meta, "name", "") or ""
    except Exception as exc:
        logger.warning("Failed to resolve project name for %s: %s", project_guid, exc)

    # Search extra orgs
    from core.config import settings
    extra_raw = (settings.rio_extra_organizations or "").strip()
    if extra_raw:
        for entry in extra_raw.split(","):
            entry = entry.strip()
            if not entry or ":" not in entry:
                continue
            org_id = entry.split(":", 1)[0].strip()
            if not org_id:
                continue
            try:
                for proj in _list_projects_for_org(org_id):
                    meta = getattr(proj, "metadata", None)
                    if not meta:
                        continue
                    if getattr(meta, "guid", "") == project_guid:
                        return getattr(meta, "name", "") or ""
            except Exception as exc:
                logger.warning("Failed to search org %s for project %s: %s", org_id, project_guid, exc)

    return ""


def list_online_devices(project_guid: str) -> List[str]:
    """List online device names for a given project."""
    v1 = _get_v1_client()
    v1.set_project(project_guid)
    devices = v1.get_all_devices(online_device=True)
    return sorted(d.name for d in devices)


# ── Device helpers ───────────────────────────────────────────────────────────

def get_device_timezone(device) -> timezone:
    """Get timezone from a RIO device via remote command."""
    command = Command(cmd='date +"%Z %z"', shell="/bin/bash", bg=False)
    try:
        output = device.execute_command(command)
        raw = output[device.uuid]
        parts = raw.split()
        tz = timezone(
            timedelta(
                hours=int(parts[1][:3]),
                minutes=int(parts[1][3:]),
            ),
            name=parts[0],
        )
        return tz
    except Exception as e:
        logger.warning("Failed to get device timezone: %s, defaulting to UTC", e)
        return timezone.utc


def get_device_timezone_by_name(project_guid: str, device_name: str) -> Dict[str, Any]:
    """Get timezone info for a device by name.

    Returns dict with timezone_name, utc_offset, utc_offset_minutes.
    Falls back to UTC if device is offline or timezone detection fails.
    """
    v1 = _get_v1_client()
    v1.set_project(project_guid)
    all_devices = v1.get_all_devices()
    device = next((d for d in all_devices if d.name == device_name), None)

    if device is None or str(device.status) != "ONLINE":
        return {"timezone_name": "UTC", "utc_offset": "+00:00", "utc_offset_minutes": 0}

    tz = get_device_timezone(device)
    offset = tz.utcoffset(None)
    total_seconds = int(offset.total_seconds())
    hours, remainder = divmod(abs(total_seconds), 3600)
    minutes = remainder // 60
    sign = "+" if total_seconds >= 0 else "-"
    offset_str = f"{sign}{hours:02d}:{minutes:02d}"

    return {
        "timezone_name": tz.tzname(None) or "UTC",
        "utc_offset": offset_str,
        "utc_offset_minutes": total_seconds // 60,
    }


def discover_rosbags(
    device,
    start_time: datetime,
    end_time: datetime,
    project_guid: str,
) -> List[str]:
    """Discover rosbag files on device within the given time range.

    Splits any actively-recording bags first, then searches the rosbag
    directory for .bag/.active files whose timestamps overlap the window.
    """
    # Split active bags first (best-effort, may fail)
    split_cmd = (
        "docker exec -i "
        '`dectl ps | awk \'$6 == "quay.io/rapyuta/rr_sootballs" {print $5}\'` '
        'bash -c "source install/setup.bash && rosservice call /split_bag"'
    )
    try:
        device.execute_command(
            Command(
                cmd=split_cmd,
                shell="/bin/bash",
                bg=False,
                run_async=True,
                timeout=300,
            )
        )
    except Exception:
        pass

    # Find bag files with their modification times
    find_cmd = (
        "stdbuf -o0 find /var/log/riouser/rosbag/ -type f "
        "\\( -iname \\*.bag -o -iname \\*.active \\)| "
        "sort -n | xargs -IFILENAME /bin/bash -c "
        f'"echo FILENAME && date -r FILENAME +{ROSBAG_DATE_FORMAT}"'
    )
    command = Command(cmd=find_cmd, shell="/bin/bash", bg=False)
    output = device.execute_command(command)
    raw = output[device.uuid]

    if "No such file or directory" in raw:
        return []

    tokens = raw.split()
    files = tokens[::2]
    mod_times = tokens[1::2]
    device_tz = get_device_timezone(device)

    matched: List[BagInfo] = []
    for path, mod_time in zip(files, mod_times):
        match = re.search(r"(\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})", path)
        if not match:
            continue
        # Bag filename timestamps are UTC
        file_start = datetime.strptime(
            match.group(1), ROSBAG_DATE_FORMAT
        ).replace(tzinfo=timezone.utc)
        # Modification time is in device-local timezone
        file_end = datetime.strptime(mod_time, ROSBAG_DATE_FORMAT).replace(
            tzinfo=device_tz
        )
        if file_start <= end_time and file_end >= start_time:
            matched.append(BagInfo(path=path, file_start=file_start, file_end=file_end))

    return matched

def discover_rosbags_by_name(
    project_guid: str,
    device_name: str,
    start_time_epoch: int,
    end_time_epoch: int,
) -> Dict[str, Any]:
    """Discover rosbags on a device without uploading.

    Returns dict with device_name, bags list, and count.
    """
    v1 = _get_v1_client()
    v1.set_project(project_guid)
    all_devices = v1.get_all_devices()
    device = next((d for d in all_devices if d.name == device_name), None)

    if device is None:
        raise RioDeviceError(f"Device '{device_name}' not found")
    if str(device.status) != "ONLINE":
        raise RioDeviceError(f"Device '{device_name}' is {device.status}")

    start_time = datetime.utcfromtimestamp(start_time_epoch).replace(tzinfo=timezone.utc)
    end_time = datetime.utcfromtimestamp(end_time_epoch).replace(tzinfo=timezone.utc)

    bags = discover_rosbags(device, start_time, end_time, project_guid)
    return {
        "device_name": device_name,
        "bags": [b.path for b in bags],
        "count": len(bags),
    }

# ── Upload trigger ───────────────────────────────────────────────────────────

def trigger_device_upload(
    project_guid: str,
    organization_guid: str,
    device_names: List[str],
    start_time_epoch: int,
    end_time_epoch: int,
    max_upload_rate_bytes: int = 1048576 * 10,
    display_start: str = "",
    display_end: str = "",
    timezone_label: str = "",
) -> Dict[str, Dict[str, Any]]:
    """DEPRECATED — use start_upload_job() for new code.

    Synchronous upload trigger kept for backward compatibility only.
    Does not support actual-bag-timestamp naming (uses user-input times).

    For each requested device that is online, discovers bags in the time
    range, creates a tar.xz archive, and triggers upload to RIO cloud.

    Returns dict keyed by device name with upload status per device:
      {device_name: {status, message, filename?, url?, request_uuid?}}
    """
    v1 = _get_v1_client()
    v1.set_project(project_guid)

    all_devices = v1.get_all_devices()
    target_set = set(device_names)
    devices = [d for d in all_devices if d.name in target_set]

    start_time = datetime.utcfromtimestamp(start_time_epoch).replace(
        tzinfo=timezone.utc
    )
    end_time = datetime.utcfromtimestamp(end_time_epoch).replace(
        tzinfo=timezone.utc
    )

    responses: Dict[str, Dict[str, Any]] = {}
    for device in devices:
        try:
            if str(device.status) != "ONLINE":
                responses[device.name] = {
                    "status": "error",
                    "message": f"Device is {device.status}",
                }
                continue

            bags = discover_rosbags(device, start_time, end_time, project_guid)
            if not bags:
                responses[device.name] = {
                    "status": "error",
                    "message": "No rosbags found in time range",
                }
                continue

            # Tar and compress on device
            tar_file = build_tar_filename(
                device_name=device.name,
                display_start=display_start,
                display_end=display_end,
                timezone_label=timezone_label,
                fallback_start=start_time,
                fallback_end=end_time,
            )
            tar_cmd = (
                f"tar -c -I 'xz -T0 -0' -f {tar_file} "
                f"--transform 's,^.*/,,g' {' '.join(b.path for b in bags)}"
            )
            device.execute_command(
                Command(cmd=tar_cmd, shell="/bin/bash", bg=False)
            )

            # Upload via RIO API
            upload_request = LogsUploadRequest(
                tar_file,
                file_name=os.path.basename(tar_file),
                override=False,
                purge_after=True,
                max_upload_rate=max_upload_rate_bytes,
                metadata={},
            )
            request_uuid = device.upload_log_file(
                upload_request=upload_request, retry_limit=5
            )

            url = (
                f"https://console.rapyuta.io/devices/{device.uuid}/manage"
                f"?org={organization_guid}&p={project_guid}"
                f"&size=10&page=1&sort=-createdAt&logId={request_uuid}"
            )

            responses[device.name] = {
                "status": "uploading",
                "message": f"Uploading {os.path.basename(tar_file)}",
                "filename": os.path.basename(tar_file),
                "url": url,
                "request_uuid": request_uuid,
            }

        except Exception as e:
            responses[device.name] = {
                "status": "error",
                "message": str(e),
            }
            logger.error("Upload failed for %s: %s", device.name, e)

    return responses


# ── Background job-based upload system ───────────────────────────────────────

# Thread-safe in-memory store: {job_id: _UploadJob}
_jobs: Dict[str, "_UploadJob"] = {}
_jobs_lock = threading.Lock()


class _UploadJob:
    """State for one upload job spanning multiple devices."""

    __slots__ = ("created_at", "events", "events_lock", "threads")

    def __init__(self) -> None:
        self.created_at: float = time.monotonic()
        self.events: List[Dict[str, Any]] = []
        self.events_lock = threading.Lock()
        self.threads: List[threading.Thread] = []

    def emit(self, event: Dict[str, Any]) -> None:
        with self.events_lock:
            self.events.append(event)

    def drain_events(self) -> List[Dict[str, Any]]:
        """Return all accumulated events and clear the buffer."""
        with self.events_lock:
            events = list(self.events)
            self.events.clear()
            return events

    def all_events_snapshot(self) -> List[Dict[str, Any]]:
        """Return copy of events without clearing (for SSE catch-up)."""
        with self.events_lock:
            return list(self.events)

    @property
    def complete(self) -> bool:
        return all(not t.is_alive() for t in self.threads)


def _cleanup_old_jobs() -> None:
    """Remove jobs older than _JOB_TTL."""
    cutoff = time.monotonic() - _JOB_TTL
    with _jobs_lock:
        expired = [jid for jid, j in _jobs.items() if j.created_at < cutoff]
        for jid in expired:
            del _jobs[jid]


def start_upload_job(
    project_guid: str,
    organization_guid: str,
    device_names: List[str],
    start_time_epoch: int,
    end_time_epoch: int,
    max_upload_rate_bytes: int = 1048576 * 10,
    display_start: str = "",
    display_end: str = "",
    timezone_label: str = "",
    utc_offset_minutes: Optional[int] = None,
    site_code: str = "",
) -> str:
    """Start a background upload job.  Returns job_id immediately.

    Each device is processed in its own thread with independent speed
    throttling.  Progress events are emitted into the job's event buffer
    and can be consumed via get_job_events().
    """
    _cleanup_old_jobs()

    job_id = str(_uuid.uuid4())
    job = _UploadJob()

    # Resolve devices once (shared across threads)
    v1 = _get_v1_client()
    v1.set_project(project_guid)
    all_devices = v1.get_all_devices()
    target_set = set(device_names)
    matched = [d for d in all_devices if d.name in target_set]

    start_time = datetime.utcfromtimestamp(start_time_epoch).replace(tzinfo=timezone.utc)
    end_time = datetime.utcfromtimestamp(end_time_epoch).replace(tzinfo=timezone.utc)
    resolved_site_code = (site_code or "").strip() or get_project_name_by_guid(project_guid)

    # Emit initial events for devices not found
    found_names = {d.name for d in matched}
    for name in device_names:
        if name not in found_names:
            job.emit({
                "event": "error",
                "device": name,
                "message": f"Device '{name}' not found in project",
            })

    # Launch one daemon thread per device
    for device in matched:
        t = threading.Thread(
            target=_upload_one_device,
            args=(job, device, organization_guid, project_guid,
                  start_time, end_time, max_upload_rate_bytes,
                  display_start, display_end, timezone_label,
                  utc_offset_minutes, resolved_site_code),
            daemon=True,
        )
        job.threads.append(t)
        t.start()

    # If no threads were spawned, emit job_done immediately
    if not job.threads:
        job.emit({"event": "job_done"})

    with _jobs_lock:
        _jobs[job_id] = job

    return job_id


def _upload_one_device(
    job: _UploadJob,
    device: Any,
    organization_guid: str,
    project_guid: str,
    start_time: datetime,
    end_time: datetime,
    max_upload_rate_bytes: int,
    display_start: str = "",
    display_end: str = "",
    timezone_label: str = "",
    utc_offset_minutes: Optional[int] = None,
    site_code: str = "",
) -> None:
    """Process a single device upload in its own thread.

    Emits events: link_ready, compressing, uploading, done, error.
    """
    name = device.name
    try:
        # 1. Emit console link immediately (before any work)
        url = (
            f"https://console.rapyuta.io/devices/{device.uuid}/manage"
            f"?org={organization_guid}&p={project_guid}"
            f"&size=10&page=1&sort=-createdAt"
        )
        job.emit({"event": "link_ready", "device": name, "url": url})

        # 2. Check online status
        if str(device.status) != "ONLINE":
            job.emit({
                "event": "error", "device": name,
                "message": f"Device is {device.status}",
            })
            return

        # 3. Discover rosbags
        job.emit({"event": "discovering", "device": name, "message": "Discovering rosbags…"})
        bags = discover_rosbags(device, start_time, end_time, project_guid)
        if not bags:
            job.emit({
                "event": "error", "device": name,
                "message": "No rosbags found in time range",
            })
            return

        # 4. Tar + compress on device
        job.emit({
            "event": "compressing", "device": name,
            "message": f"Compressing {len(bags)} bag(s)…",
        })
        tar_file: str
        if utc_offset_minutes is not None:
            # Use actual bag timestamps from discovered files
            tar_file = build_actual_tar_filename(name, site_code, bags, utc_offset_minutes)
        else:
            tar_file = build_tar_filename(
                device_name=name,
                display_start=display_start,
                display_end=display_end,
                timezone_label=timezone_label,
                fallback_start=start_time,
                fallback_end=end_time,
            )
        tar_cmd = (
            f"tar -c -I 'xz -T0 -0' -f {tar_file} "
            f"--transform 's,^.*/,,g' {' '.join(b.path for b in bags)}"
        )
        device.execute_command(Command(cmd=tar_cmd, shell="/bin/bash", bg=False))

        # 5. Upload via RIO API
        speed_mbps = max(1, max_upload_rate_bytes // 1048576)
        job.emit({
            "event": "uploading", "device": name,
            "message": f"Uploading {os.path.basename(tar_file)} at {speed_mbps} MB/s…",
        })
        upload_request = LogsUploadRequest(
            tar_file,
            file_name=os.path.basename(tar_file),
            override=False,
            purge_after=True,
            max_upload_rate=max_upload_rate_bytes,
            metadata={},
        )
        request_uuid = device.upload_log_file(
            upload_request=upload_request, retry_limit=5,
        )

        # Update URL with logId now that we have the request UUID
        url_with_log = (
            f"https://console.rapyuta.io/devices/{device.uuid}/manage"
            f"?org={organization_guid}&p={project_guid}"
            f"&size=10&page=1&sort=-createdAt&logId={request_uuid}"
        )
        job.emit({
            "event": "done", "device": name,
            "message": f"Upload queued — {os.path.basename(tar_file)}",
            "filename": os.path.basename(tar_file),
            "url": url_with_log,
            "request_uuid": request_uuid,
        })

    except Exception as exc:
        job.emit({
            "event": "error", "device": name,
            "message": str(exc),
        })
        logger.error("Upload job failed for %s: %s", name, exc)
    finally:
        # Check if all threads are done → emit job_done
        # Small delay so sibling threads can also finish
        time.sleep(0.1)
        if job.complete:
            job.emit({"event": "job_done"})


def get_job_events(job_id: str) -> List[Dict[str, Any]]:
    """Drain buffered events for a job.  Returns [] for unknown jobs."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        return []
    return job.drain_events()


def is_job_complete(job_id: str) -> bool:
    """Check if all device threads for a job have finished."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        return True
    return job.complete
