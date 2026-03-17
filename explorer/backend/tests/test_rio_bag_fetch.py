"""Tests for RIO bag fetch endpoints and service."""
import sys
import os
import json
import subprocess

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock
import pathlib
import pytest
from fastapi.testclient import TestClient
from app.main import app
from services.rio.rio_service import (
    RioNotConfiguredError, RioConfigMalformedError,
    _sanitize_filename, _validate_shared_url, _validate_safe_name,
)

client = TestClient(app)

_VALID_URL = "https://gaapiserver.apps.rapyuta.io/sharedurl/abc123"


# ── GET /api/v1/bags/rio/status ──────────────────────────────────────────────

class TestRIOStatus:

    def test_status_when_configured(self):
        fake = {"auth_token": "t", "organization_id": "org-1", "project_id": "proj-1"}
        with patch("app.routes.bags.rio_service.get_rio_config", return_value=fake), \
             patch("app.routes.bags.rio_service.is_rio_cli_available", return_value=True):
            resp = client.get("/api/v1/bags/rio/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True
        assert data["has_token"] is True
        assert data["has_organization"] is True
        assert data["has_project"] is True
        assert data["rio_cli_available"] is True
        assert data["organization"] == "org-1"
        assert data["project"] == "proj-1"
        assert "auth_token" not in data

    def test_status_when_not_configured(self):
        with patch("app.routes.bags.rio_service.get_rio_config",
                    side_effect=RioNotConfiguredError("not configured")), \
             patch("app.routes.bags.rio_service.is_rio_cli_available", return_value=False):
            resp = client.get("/api/v1/bags/rio/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False
        assert data["rio_cli_available"] is False

    def test_status_malformed_config(self):
        with patch("app.routes.bags.rio_service.get_rio_config",
                    side_effect=RioConfigMalformedError("malformed")), \
             patch("app.routes.bags.rio_service.is_rio_cli_available", return_value=True):
            resp = client.get("/api/v1/bags/rio/status")
        assert resp.status_code == 200
        assert resp.json()["configured"] is False


# ── POST /api/v1/bags/rio/fetch — shared URL ────────────────────────────────

class TestRIOFetchSharedURL:

    def test_fetch_shared_url_success(self, tmp_path):
        fake_bag = tmp_path / "test_robot.bag"
        fake_bag.write_bytes(b"\x00" * 2048)

        with patch("app.routes.bags.rio_service.download_shared_url", return_value=fake_bag):
            resp = client.post("/api/v1/bags/rio/fetch", json={"shared_url": _VALID_URL})
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "test_robot.bag"
        assert data["source"] == "shared_url"
        assert data["size_mb"] == pytest.approx(2048 / (1024 * 1024), abs=0.01)

    def test_fetch_invalid_url(self):
        with patch("app.routes.bags.rio_service.download_shared_url",
                    side_effect=ValueError("URL must be a gaapiserver shared URL.")):
            resp = client.post("/api/v1/bags/rio/fetch",
                               json={"shared_url": "https://evil.com/malicious"})
        assert resp.status_code == 400

    def test_fetch_not_configured(self):
        with patch("app.routes.bags.rio_service.download_shared_url",
                    side_effect=RioNotConfiguredError("RIO not configured.")):
            resp = client.post("/api/v1/bags/rio/fetch", json={"shared_url": _VALID_URL})
        assert resp.status_code == 503

    def test_fetch_upstream_error(self):
        with patch("app.routes.bags.rio_service.download_shared_url",
                    side_effect=RuntimeError("Upstream error: 404 Not Found")):
            resp = client.post("/api/v1/bags/rio/fetch", json={"shared_url": _VALID_URL})
        assert resp.status_code == 502

    def test_fetch_malformed_config(self):
        with patch("app.routes.bags.rio_service.download_shared_url",
                    side_effect=RioConfigMalformedError("malformed")):
            resp = client.post("/api/v1/bags/rio/fetch", json={"shared_url": _VALID_URL})
        assert resp.status_code == 503

    def test_fetch_with_project_override(self, tmp_path):
        fake_bag = tmp_path / "robot.bag"
        fake_bag.write_bytes(b"\x00" * 512)

        with patch("app.routes.bags.rio_service.download_shared_url", return_value=fake_bag) as mock:
            resp = client.post("/api/v1/bags/rio/fetch",
                               json={"shared_url": _VALID_URL, "project_override": "dhl-001"})
        assert resp.status_code == 200
        mock.assert_called_once_with(_VALID_URL, project_override="dhl-001")


# ── POST /api/v1/bags/rio/fetch — device upload ─────────────────────────────

class TestRIOFetchDevice:

    def test_fetch_device_success(self, tmp_path):
        fake_bag = tmp_path / "oksbot24_upload.bag"
        fake_bag.write_bytes(b"\x00" * 4096)

        with patch("app.routes.bags.rio_service.download_device_upload", return_value=fake_bag):
            resp = client.post("/api/v1/bags/rio/fetch",
                               json={"device": "oksbot24", "filename": "test.bag"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "device_upload"

    def test_fetch_device_no_rio_cli(self):
        with patch("app.routes.bags.rio_service.download_device_upload",
                    side_effect=FileNotFoundError("rio CLI is not installed")):
            resp = client.post("/api/v1/bags/rio/fetch",
                               json={"device": "bot1", "filename": "f.bag"})
        assert resp.status_code == 503

    def test_fetch_device_timeout(self):
        with patch("app.routes.bags.rio_service.download_device_upload",
                    side_effect=subprocess.TimeoutExpired(cmd="rio", timeout=300)):
            resp = client.post("/api/v1/bags/rio/fetch",
                               json={"device": "bot1", "filename": "f.bag"})
        assert resp.status_code == 504

    def test_fetch_device_invalid_name(self):
        with patch("app.routes.bags.rio_service.download_device_upload",
                    side_effect=ValueError("Invalid device name.")):
            resp = client.post("/api/v1/bags/rio/fetch",
                               json={"device": "../evil", "filename": "f.bag"})
        assert resp.status_code == 400


# ── POST /api/v1/bags/rio/fetch — validation ────────────────────────────────

class TestRIOFetchValidation:

    def test_both_url_and_device_rejected(self):
        resp = client.post("/api/v1/bags/rio/fetch", json={
            "shared_url": _VALID_URL, "device": "bot1", "filename": "f.bag"
        })
        assert resp.status_code == 422

    def test_neither_url_nor_device_rejected(self):
        resp = client.post("/api/v1/bags/rio/fetch", json={})
        assert resp.status_code == 422

    def test_device_without_filename_rejected(self):
        resp = client.post("/api/v1/bags/rio/fetch", json={"device": "bot1"})
        assert resp.status_code == 422


# ── Service unit tests ───────────────────────────────────────────────────────

class TestRIOServiceURL:

    def test_validate_url_rejects_non_gaapiserver(self):
        with pytest.raises(ValueError, match="gaapiserver"):
            _validate_shared_url("https://evil.com/sharedurl/abc")

    def test_validate_url_accepts_gaapiserver(self):
        _validate_shared_url(_VALID_URL)

    def test_validate_url_rejects_partial(self):
        with pytest.raises(ValueError):
            _validate_shared_url("https://gaapiserver.io/notshared")


class TestRIOServiceSanitize:

    def test_sanitize_normal(self):
        assert _sanitize_filename("robot24.bag") == "robot24.bag"

    def test_sanitize_strips_paths(self):
        assert _sanitize_filename("/etc/passwd") == "passwd"
        assert _sanitize_filename("../../etc/shadow") == "shadow"

    def test_sanitize_rejects_null(self):
        with pytest.raises(ValueError):
            _sanitize_filename("file\x00name.bag")

    def test_sanitize_rejects_empty(self):
        with pytest.raises(ValueError):
            _sanitize_filename("")

    def test_sanitize_caps_length(self):
        long_name = "a" * 300 + ".bag"
        result = _sanitize_filename(long_name)
        assert len(result) <= 200


class TestRIOServiceSafeName:

    def test_valid_device_name(self):
        _validate_safe_name("oksbot24", "device")

    def test_valid_filename(self):
        _validate_safe_name("robot_20260318.bag", "filename")

    def test_rejects_path_traversal(self):
        with pytest.raises(ValueError):
            _validate_safe_name("../evil", "device")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError):
            _validate_safe_name("my device", "device")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            _validate_safe_name("", "device")


class TestGetRioConfig:

    def test_config_from_file(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "auth_token": "tok_from_file",
            "organization_id": "org-file",
            "project_id": "proj-file",
        }))
        with patch("services.rio.rio_service.settings") as ms, \
             patch.dict(os.environ, {}, clear=True):
            ms.rio_config_path = str(config_file)
            from services.rio.rio_service import get_rio_config
            result = get_rio_config()
        assert result["auth_token"] == "tok_from_file"
        assert result["organization_id"] == "org-file"

    def test_raises_when_no_token(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"organization_id": "org"}))
        with patch("services.rio.rio_service.settings") as ms, \
             patch.dict(os.environ, {}, clear=True), \
             patch("services.rio.rio_service._LEGACY_TOKEN_FILE", tmp_path / "nonexistent"):
            ms.rio_config_path = str(config_file)
            from services.rio.rio_service import get_rio_config
            with pytest.raises(RioNotConfiguredError):
                get_rio_config()

    def test_raises_on_malformed_json(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text("{bad json")
        with patch("services.rio.rio_service.settings") as ms, \
             patch.dict(os.environ, {}, clear=True):
            ms.rio_config_path = str(config_file)
            from services.rio.rio_service import get_rio_config
            with pytest.raises(RioConfigMalformedError):
                get_rio_config()
