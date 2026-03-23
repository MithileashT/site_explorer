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
_VALID_URL_V2 = "https://api.rapyuta.io/v2/devices/fileuploads/sharedurls/sharedurl-d6stlaisq6es73a74rag/"


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
                    side_effect=ValueError("URL must be a Rapyuta IO shared URL")):
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

    def test_validate_url_rejects_non_rapyuta(self):
        with pytest.raises(ValueError, match="Rapyuta IO shared URL"):
            _validate_shared_url("https://evil.com/sharedurl/abc")

    def test_validate_url_accepts_gaapiserver(self):
        _validate_shared_url(_VALID_URL)

    def test_validate_url_accepts_api_rapyuta_io(self):
        _validate_shared_url(_VALID_URL_V2)

    def test_validate_url_rejects_partial(self):
        with pytest.raises(ValueError):
            _validate_shared_url("https://gaapiserver.io/notshared")

    def test_validate_url_rejects_non_https(self):
        with pytest.raises(ValueError):
            _validate_shared_url("http://api.rapyuta.io/v2/devices/fileuploads/sharedurls/x/")

    def test_validate_url_rejects_spoofed_domain(self):
        with pytest.raises(ValueError):
            _validate_shared_url("https://api.rapyuta.io.evil.com/sharedurls/x/")


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


class TestSharedURLWithoutAuth:
    """Shared URLs should work even when RIO is not configured (no auth token)."""

    def test_download_succeeds_without_rio_config(self, tmp_path):
        """download_shared_url should proceed when get_rio_config raises."""
        fake_resp = MagicMock()
        fake_resp.headers = {"Content-Disposition": 'filename="robot.bag"'}
        fake_resp.read.return_value = b"\x00" * 1024
        fake_resp.__enter__ = MagicMock(return_value=fake_resp)
        fake_resp.__exit__ = MagicMock(return_value=False)

        with patch("services.rio.rio_service.get_rio_config",
                    side_effect=RioNotConfiguredError("not configured")), \
             patch("services.rio.rio_service._opener") as mock_opener, \
             patch("services.rio.rio_service.settings") as ms:
            ms.bag_upload_dir = str(tmp_path)
            mock_opener.open.return_value = fake_resp
            from services.rio.rio_service import download_shared_url
            result = download_shared_url(_VALID_URL)

        assert result.exists()
        assert result.stat().st_size == 1024

    def test_download_without_auth_does_not_send_bearer(self, tmp_path):
        """When no auth is available, no Authorization header should be sent."""
        fake_resp = MagicMock()
        fake_resp.headers = {"Content-Disposition": 'filename="robot.bag"'}
        fake_resp.read.return_value = b"\x00" * 512
        fake_resp.__enter__ = MagicMock(return_value=fake_resp)
        fake_resp.__exit__ = MagicMock(return_value=False)

        with patch("services.rio.rio_service.get_rio_config",
                    side_effect=RioNotConfiguredError("not configured")), \
             patch("services.rio.rio_service._opener") as mock_opener, \
             patch("services.rio.rio_service.settings") as ms:
            ms.bag_upload_dir = str(tmp_path)
            mock_opener.open.return_value = fake_resp
            from services.rio.rio_service import download_shared_url
            download_shared_url(_VALID_URL)

        # Inspect the Request object passed to opener.open
        req_obj = mock_opener.open.call_args[0][0]
        assert req_obj.get_header("Authorization") is None

    def test_route_fetch_no_config_succeeds(self, tmp_path):
        """POST /rio/fetch with shared URL shouldn't fail with 503 when no config."""
        fake_bag = tmp_path / "robot.bag"
        fake_bag.write_bytes(b"\x00" * 2048)

        with patch("app.routes.bags.rio_service.download_shared_url", return_value=fake_bag):
            resp = client.post("/api/v1/bags/rio/fetch", json={"shared_url": _VALID_URL})
        assert resp.status_code == 200
        assert resp.json()["source"] == "shared_url"


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


# ── Archive extraction in rio_fetch route ───────────────────────────────────

class TestRIOFetchArchiveExtraction:
    """Tests that rio_fetch auto-extracts tar archives."""

    def test_tar_xz_extracted_returns_bag_path(self, tmp_path):
        """When download returns a .tar.xz, the route extracts .bag files."""
        import tarfile
        # Create a tar.xz with a .bag inside
        bag_file = tmp_path / "robot.bag"
        bag_file.write_bytes(b"ROSBAG data")
        archive = tmp_path / "download.tar.xz"
        with tarfile.open(archive, "w:xz") as t:
            t.add(bag_file, arcname="robot.bag")

        with patch("app.routes.bags.rio_service.download_shared_url", return_value=archive), \
             patch("app.routes.bags.settings") as ms:
            ms.bag_upload_dir = str(tmp_path / "bags")
            resp = client.post("/api/v1/bags/rio/fetch", json={
                "shared_url": _VALID_URL,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["bag_path"].endswith(".bag")
        assert data["extracted_bags"] is not None
        assert len(data["extracted_bags"]) == 1

    def test_plain_bag_no_extraction(self):
        """When download returns a .bag file, no extraction happens."""
        fake_path = pathlib.Path("/tmp/test_plain.bag")
        fake_path.write_bytes(b"ROSBAG data")
        try:
            with patch("app.routes.bags.rio_service.download_shared_url", return_value=fake_path):
                resp = client.post("/api/v1/bags/rio/fetch", json={
                    "shared_url": _VALID_URL,
                })
            assert resp.status_code == 200
            data = resp.json()
            assert data["extracted_bags"] is None
        finally:
            fake_path.unlink(missing_ok=True)

    def test_archive_with_no_bags_returns_422(self, tmp_path):
        """When archive has no .bag/.db3 files, return 422."""
        import tarfile
        txt_file = tmp_path / "readme.txt"
        txt_file.write_bytes(b"no bags here")
        archive = tmp_path / "empty.tar.gz"
        with tarfile.open(archive, "w:gz") as t:
            t.add(txt_file, arcname="readme.txt")

        with patch("app.routes.bags.rio_service.download_shared_url", return_value=archive), \
             patch("app.routes.bags.settings") as ms:
            ms.bag_upload_dir = str(tmp_path / "bags")
            resp = client.post("/api/v1/bags/rio/fetch", json={
                "shared_url": _VALID_URL,
            })

        assert resp.status_code == 422
        assert "no .bag" in resp.json()["detail"].lower()


# ── GET /api/v1/bags/rio/projects ────────────────────────────────────────────

class TestRIOProjects:

    def test_list_projects_success(self):
        with patch("app.routes.bags.rio_device_service.list_projects",
                    return_value=[
                        {"name": "jpn-tok-001", "guid": "project-abc", "organization_guid": "org-1"},
                        {"name": "rr-test", "guid": "project-rr1", "organization_guid": "org-2"},
                    ]):
            resp = client.get("/api/v1/bags/rio/projects")
        assert resp.status_code == 200
        data = resp.json()
        names = [p["name"] for p in data["projects"]]
        assert "jpn-tok-001" in names
        assert "rr-test" in names
        # Verify guid and organization_guid are present
        match = [p for p in data["projects"] if p["name"] == "jpn-tok-001"][0]
        assert match["guid"] == "project-abc"
        assert match["organization_guid"] == "org-1"

    def test_list_projects_empty(self):
        with patch("app.routes.bags.rio_device_service.list_projects",
                    return_value=[]):
            resp = client.get("/api/v1/bags/rio/projects")
        assert resp.status_code == 200
        assert resp.json()["projects"] == []

    def test_list_projects_error(self):
        with patch("app.routes.bags.rio_device_service.list_projects",
                    side_effect=Exception("RIO not configured")):
            resp = client.get("/api/v1/bags/rio/projects")
        assert resp.status_code == 503


# ── POST /api/v1/bags/rio/devices ────────────────────────────────────────────

class TestRIODevices:

    def test_list_devices_success(self):
        with patch("app.routes.bags.rio_device_service.list_online_devices",
                    return_value=["robot-001", "robot-002"]):
            resp = client.post("/api/v1/bags/rio/devices",
                               json={"project_guid": "pg-123"})
        assert resp.status_code == 200
        data = resp.json()
        assert "robot-001" in data["devices"]
        assert data["project_guid"] == "pg-123"

    def test_list_devices_empty(self):
        with patch("app.routes.bags.rio_device_service.list_online_devices",
                    return_value=[]):
            resp = client.post("/api/v1/bags/rio/devices",
                               json={"project_guid": "pg-123"})
        assert resp.status_code == 200
        assert resp.json()["devices"] == []

    def test_list_devices_error(self):
        with patch("app.routes.bags.rio_device_service.list_online_devices",
                    side_effect=Exception("Connection failed")):
            resp = client.post("/api/v1/bags/rio/devices",
                               json={"project_guid": "pg-123"})
        assert resp.status_code == 503


# ── POST /api/v1/bags/rio/trigger-upload ─────────────────────────────────────

class TestRIOTriggerUpload:

    def test_trigger_upload_success(self):
        with patch("app.routes.bags.rio_device_service.start_upload_job",
                    return_value="job-uuid-123"):
            resp = client.post("/api/v1/bags/rio/trigger-upload", json={
                "project_guid": "pg-123",
                "organization_guid": "og-456",
                "device_names": ["robot-001"],
                "start_time_epoch": 1704067200,
                "end_time_epoch": 1704067800,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "job-uuid-123"

    def test_trigger_upload_with_errors(self):
        with patch("app.routes.bags.rio_device_service.start_upload_job",
                    return_value="job-uuid-456"):
            resp = client.post("/api/v1/bags/rio/trigger-upload", json={
                "project_guid": "pg-123",
                "organization_guid": "og-456",
                "device_names": ["robot-001", "robot-002"],
                "start_time_epoch": 1704067200,
                "end_time_epoch": 1704067800,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data

    def test_trigger_upload_service_failure(self):
        with patch("app.routes.bags.rio_device_service.start_upload_job",
                    side_effect=Exception("RIO auth failed")):
            resp = client.post("/api/v1/bags/rio/trigger-upload", json={
                "project_guid": "pg-123",
                "organization_guid": "og-456",
                "device_names": ["robot-001"],
                "start_time_epoch": 1704067200,
                "end_time_epoch": 1704067800,
            })
        assert resp.status_code == 503

    def test_trigger_upload_with_display_fields(self):
        """Request schema accepts display_start/end and timezone_label."""
        with patch("app.routes.bags.rio_device_service.start_upload_job",
                    return_value="job-uuid-789"):
            resp = client.post("/api/v1/bags/rio/trigger-upload", json={
                "project_guid": "pg-123",
                "organization_guid": "og-456",
                "device_names": ["robot-001"],
                "start_time_epoch": 1704067200,
                "end_time_epoch": 1704067800,
                "display_start": "2026-03-22T10:00",
                "display_end": "2026-03-22T11:00",
                "timezone_label": "JST",
            })
        assert resp.status_code == 200

    def test_trigger_upload_without_display_fields_still_works(self):
        """Existing callers without display fields still work (fields are optional)."""
        with patch("app.routes.bags.rio_device_service.start_upload_job",
                    return_value="job-uuid-000"):
            resp = client.post("/api/v1/bags/rio/trigger-upload", json={
                "project_guid": "pg-123",
                "organization_guid": "og-456",
                "device_names": ["robot-001"],
                "start_time_epoch": 1704067200,
                "end_time_epoch": 1704067800,
            })
        assert resp.status_code == 200

    def test_trigger_upload_passes_site_code(self):
        """site_code from request is forwarded to start_upload_job."""
        with patch("app.routes.bags.rio_device_service.start_upload_job",
                    return_value="job-uuid-site") as mock_job:
            resp = client.post("/api/v1/bags/rio/trigger-upload", json={
                "project_guid": "pg-123",
                "organization_guid": "og-456",
                "device_names": ["amr06"],
                "start_time_epoch": 1704067200,
                "end_time_epoch": 1704067800,
                "utc_offset_minutes": 540,
                "site_code": "ash-kki-001",
            })
        assert resp.status_code == 200
        mock_job.assert_called_once()
        _, kwargs = mock_job.call_args
        assert kwargs["site_code"] == "ash-kki-001"


# ── build_tar_filename ────────────────────────────────────────────────────────

class TestBuildTarFilename:
    """Unit tests for build_tar_filename()."""

    def test_jst_filename(self):
        from services.rio.rio_device_service import build_tar_filename
        name = build_tar_filename(
            device_name="my-robot",
            display_start="2026-03-22T10:00",
            display_end="2026-03-22T11:00",
            timezone_label="JST",
        )
        assert name == "/tmp/rosbags_2026-03-22_10-00_to_2026-03-22_11-00_JST.tar.xz"

    def test_ist_filename(self):
        from services.rio.rio_device_service import build_tar_filename
        name = build_tar_filename(
            device_name="amr-001",
            display_start="2026-03-22T15:30",
            display_end="2026-03-22T16:30",
            timezone_label="IST",
        )
        assert name == "/tmp/rosbags_2026-03-22_15-30_to_2026-03-22_16-30_IST.tar.xz"

    def test_utc_filename(self):
        from services.rio.rio_device_service import build_tar_filename
        name = build_tar_filename(
            device_name="robot-x",
            display_start="2026-03-22T01:00",
            display_end="2026-03-22T02:00",
            timezone_label="UTC",
        )
        assert name == "/tmp/rosbags_2026-03-22_01-00_to_2026-03-22_02-00_UTC.tar.xz"

    def test_colons_replaced(self):
        from services.rio.rio_device_service import build_tar_filename
        name = build_tar_filename(
            device_name="bot",
            display_start="2026-03-22T10:00",
            display_end="2026-03-22T10:30",
            timezone_label="PT",
        )
        assert ":" not in name

    def test_falls_back_to_utc_epoch_when_display_missing(self):
        from services.rio.rio_device_service import build_tar_filename
        from datetime import datetime, timezone
        start_utc = datetime(2026, 3, 22, 1, 0, tzinfo=timezone.utc)
        end_utc = datetime(2026, 3, 22, 2, 0, tzinfo=timezone.utc)
        name = build_tar_filename(
            device_name="bot",
            display_start="",
            display_end="",
            timezone_label="",
            fallback_start=start_utc,
            fallback_end=end_utc,
        )
        assert "2026_03_22_01_00_00" in name
        assert "2026_03_22_02_00_00" in name


# ── build_actual_tar_filename ─────────────────────────────────────────────────

class TestBuildActualTarFilename:
    """Unit tests for build_actual_tar_filename()."""

    def _make_bag(self, path: str, start, end):
        from services.rio.rio_device_service import BagInfo
        return BagInfo(path=path, file_start=start, file_end=end)

    def test_basic_filename(self):
        from datetime import datetime, timezone
        from services.rio.rio_device_service import build_actual_tar_filename

        bags = [
            self._make_bag(
                "/var/log/riouser/rosbag/2026-03-22-10-09-41.bag",
                datetime(2026, 3, 22, 10, 9, 41, tzinfo=timezone.utc),
                datetime(2026, 3, 22, 10, 48, 46, tzinfo=timezone.utc),
            )
        ]
        name = build_actual_tar_filename("amr06", "kao-iwt-001", bags, utc_offset_minutes=0)
        assert name == "/tmp/amr06-kao-iwt-001-2026_03_22_10_09_41-2026_03_22_10_48_46.tar.xz"

    def test_jst_offset(self):
        from datetime import datetime, timezone
        from services.rio.rio_device_service import build_actual_tar_filename

        # UTC 01:09:41 → JST (UTC+9) = 10:09:41
        bags = [
            self._make_bag(
                "/var/log/riouser/rosbag/2026-03-22-01-09-41.bag",
                datetime(2026, 3, 22, 1, 9, 41, tzinfo=timezone.utc),
                datetime(2026, 3, 22, 1, 48, 46, tzinfo=timezone.utc),
            )
        ]
        name = build_actual_tar_filename("amr06", "kao-iwt-001", bags, utc_offset_minutes=540)
        assert name == "/tmp/amr06-kao-iwt-001-2026_03_22_10_09_41-2026_03_22_10_48_46.tar.xz"

    def test_multi_bag_spans(self):
        from datetime import datetime, timezone
        from services.rio.rio_device_service import build_actual_tar_filename

        bags = [
            self._make_bag(
                "/var/log/2026-03-22-10-05-00.bag",
                datetime(2026, 3, 22, 10, 5, 0, tzinfo=timezone.utc),
                datetime(2026, 3, 22, 10, 30, 0, tzinfo=timezone.utc),
            ),
            self._make_bag(
                "/var/log/2026-03-22-10-30-00.bag",
                datetime(2026, 3, 22, 10, 30, 0, tzinfo=timezone.utc),
                datetime(2026, 3, 22, 10, 55, 0, tzinfo=timezone.utc),
            ),
        ]
        name = build_actual_tar_filename("robot", "site", bags, utc_offset_minutes=0)
        assert "2026_03_22_10_05_00" in name
        assert "2026_03_22_10_55_00" in name

    def test_no_colons_in_filename(self):
        from datetime import datetime, timezone
        from services.rio.rio_device_service import build_actual_tar_filename

        bags = [
            self._make_bag(
                "/var/log/2026-03-22-10-00-00.bag",
                datetime(2026, 3, 22, 10, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 3, 22, 11, 0, 0, tzinfo=timezone.utc),
            )
        ]
        name = build_actual_tar_filename("bot", "site", bags, utc_offset_minutes=0)
        assert ":" not in name

    def test_no_site_name_omits_site_segment(self):
        """When site_name is empty, filename should not have double dash or empty segment."""
        from datetime import datetime, timezone
        from services.rio.rio_device_service import build_actual_tar_filename

        bags = [
            self._make_bag(
                "/var/log/2026-03-22-10-00-00.bag",
                datetime(2026, 3, 22, 10, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 3, 22, 11, 0, 0, tzinfo=timezone.utc),
            )
        ]
        name = build_actual_tar_filename("robot001", "", bags, utc_offset_minutes=0)
        assert name == "/tmp/robot001-2026_03_22_10_00_00-2026_03_22_11_00_00.tar.xz"
        assert "--" not in name
