"""Tests for RIO device service — project listing, device listing, rosbag trigger."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
import pytest

from services.rio.rio_device_service import (
    _get_v2_client,
    list_projects,
    get_project_name_by_guid,
    list_online_devices,
    discover_rosbags,
    trigger_device_upload,
    get_device_timezone,
    RioDeviceError,
)


# ── _get_v2_client user-agent sanitization ───────────────────────────────────

class TestV2ClientSanitization:

    @patch("services.rio.rio_device_service.Configuration")
    @patch("services.rio.rio_device_service.get_rio_config")
    def test_user_agent_stripped_of_illegal_chars(self, mock_cfg_fn, mock_config_cls):
        mock_cfg_fn.return_value = {"auth_token": "tok", "project_id": "", "organization_id": ""}
        mock_cfg = MagicMock()
        mock_config_cls.return_value = mock_cfg
        mock_v2 = MagicMock()
        # Simulate the problematic user-agent produced by SDK 0.4.0 on Ubuntu
        mock_v2.c.headers = {
            "user-agent": "rio-sdk-v2;N/A;x86_64;Linux;6.8.0-106-generic #106~22.04.1-Ubuntu SMP\nPREEMPT Fri Mar  6 UTC "
        }
        mock_cfg.new_v2_client.return_value = mock_v2
        client = _get_v2_client()
        ua = client.c.headers["user-agent"]
        # Must not contain newlines or trailing whitespace (illegal per HTTP/1.1)
        assert "\n" not in ua
        assert "\r" not in ua
        assert not ua.endswith(" ")


# ── list_projects ────────────────────────────────────────────────────────────

class TestListProjects:

    def test_returns_filtered_site_code_projects_with_guids(self):
        mock_proj = MagicMock()
        mock_proj.metadata.name = "jpn-tok-001"
        mock_proj.metadata.guid = "project-abc"
        mock_proj.metadata.organizationGUID = "org-1"

        mock_other = MagicMock()
        mock_other.metadata.name = "random-project"
        mock_other.metadata.guid = "project-xyz"
        mock_other.metadata.organizationGUID = "org-1"

        with patch("services.rio.rio_device_service._get_v2_client") as mock_v2, \
             patch("services.rio.rio_device_service.walk_pages", return_value=iter([[mock_proj, mock_other]])):
            projects = list_projects()

        names = [p["name"] for p in projects]
        assert "jpn-tok-001" in names
        assert "random-project" not in names
        # Each project must have guid + organization_guid
        match = [p for p in projects if p["name"] == "jpn-tok-001"][0]
        assert match["guid"] == "project-abc"
        assert match["organization_guid"] == "org-1"

    def test_returns_rr_prefixed_projects_with_guids(self):
        mock_proj = MagicMock()
        mock_proj.metadata.name = "rr-test-env"
        mock_proj.metadata.guid = "project-rr1"
        mock_proj.metadata.organizationGUID = "org-2"

        with patch("services.rio.rio_device_service._get_v2_client") as mock_v2, \
             patch("services.rio.rio_device_service.walk_pages", return_value=iter([[mock_proj]])):
            projects = list_projects()

        names = [p["name"] for p in projects]
        assert "rr-test-env" in names

    def test_returns_sorted_list(self):
        projs = []
        for name in ["usa-chi-002", "jpn-tok-001", "rr-alpha"]:
            m = MagicMock()
            m.metadata.name = name
            m.metadata.guid = f"project-{name}"
            m.metadata.organizationGUID = "org-1"
            projs.append(m)

        with patch("services.rio.rio_device_service._get_v2_client") as mock_v2, \
             patch("services.rio.rio_device_service.walk_pages", return_value=iter([projs])):
            projects = list_projects()

        names = [p["name"] for p in projects]
        assert names == sorted(names)

    def test_get_project_name_by_guid_returns_name(self):
        proj = MagicMock()
        proj.metadata.name = "kao-iwt-001"
        proj.metadata.guid = "project-kao"

        with patch("services.rio.rio_device_service._get_v2_client"), \
             patch("services.rio.rio_device_service.walk_pages", return_value=iter([[proj]])):
            name = get_project_name_by_guid("project-kao")

        assert name == "kao-iwt-001"

    def test_get_project_name_by_guid_returns_empty_when_not_found(self):
        proj = MagicMock()
        proj.metadata.name = "ash-kki-001"
        proj.metadata.guid = "project-other"

        with patch("services.rio.rio_device_service._get_v2_client"), \
             patch("services.rio.rio_device_service.walk_pages", return_value=iter([[proj]])):
            name = get_project_name_by_guid("project-missing")

        assert name == ""

    def test_empty_projects(self):
        with patch("services.rio.rio_device_service._get_v2_client") as mock_v2, \
             patch("services.rio.rio_device_service.walk_pages", return_value=iter([])):
            projects = list_projects()

        assert projects == []

    def test_walk_pages_handles_multiple_pages(self):
        """Verify walk_pages is used to paginate through all RIO projects."""
        page1_proj = MagicMock()
        page1_proj.metadata.name = "jpn-tok-001"
        page1_proj.metadata.guid = "project-p1"
        page1_proj.metadata.organizationGUID = "org-1"

        page2_proj = MagicMock()
        page2_proj.metadata.name = "usa-chi-002"
        page2_proj.metadata.guid = "project-p2"
        page2_proj.metadata.organizationGUID = "org-2"

        with patch("services.rio.rio_device_service._get_v2_client") as mock_v2, \
             patch("services.rio.rio_device_service.walk_pages",
                   return_value=iter([[page1_proj], [page2_proj]])):
            projects = list_projects()

        names = [p["name"] for p in projects]
        assert "jpn-tok-001" in names
        assert "usa-chi-002" in names


# ── list_online_devices ──────────────────────────────────────────────────────

class TestListOnlineDevices:

    def test_returns_sorted_device_names(self):
        devices = []
        for name in ["robot-003", "robot-001", "robot-002"]:
            d = MagicMock()
            d.name = name
            devices.append(d)

        with patch("services.rio.rio_device_service._get_v1_client") as mock_v1:
            mock_v1.return_value.get_all_devices.return_value = devices
            result = list_online_devices("proj-guid")

        assert result == ["robot-001", "robot-002", "robot-003"]
        mock_v1.return_value.set_project.assert_called_once_with("proj-guid")

    def test_empty_devices(self):
        with patch("services.rio.rio_device_service._get_v1_client") as mock_v1:
            mock_v1.return_value.get_all_devices.return_value = []
            result = list_online_devices("proj-guid")

        assert result == []


# ── get_device_timezone ──────────────────────────────────────────────────────

class TestGetDeviceTimezone:

    def test_parses_timezone_correctly(self):
        mock_device = MagicMock()
        mock_device.uuid = "uuid-1"
        mock_device.execute_command.return_value = {"uuid-1": "JST +0900"}

        tz = get_device_timezone(mock_device)
        assert str(tz) == "JST"

    def test_falls_back_to_utc_on_error(self):
        mock_device = MagicMock()
        mock_device.uuid = "uuid-1"
        mock_device.execute_command.side_effect = Exception("connection failed")

        tz = get_device_timezone(mock_device)
        assert tz == timezone.utc


# ── discover_rosbags ─────────────────────────────────────────────────────────

class TestDiscoverRosbags:

    def test_returns_matching_bags(self):
        mock_device = MagicMock()
        mock_device.uuid = "uuid-1"

        # Call sequence in discover_rosbags:
        # 1. split_bag command (may succeed or fail)
        # 2. find command returning bag list
        # 3. get_device_timezone command
        mock_device.execute_command.side_effect = [
            {},  # split_bag command result
            {"uuid-1": (
                "/var/log/riouser/rosbag/2025-01-01-00-00-00.bag 2025-01-01-00-10-00 "
                "/var/log/riouser/rosbag/2025-01-01-00-15-00.bag 2025-01-01-00-25-00"
            )},  # find command
            {"uuid-1": "UTC +0000"},  # timezone command
        ]

        start = datetime(2024, 12, 31, 23, 55, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 1, 0, 12, 0, tzinfo=timezone.utc)

        bags = discover_rosbags(mock_device, start, end, "proj-guid")
        assert len(bags) >= 1
        assert "/var/log/riouser/rosbag/2025-01-01-00-00-00.bag" in [b.path for b in bags]

    def test_returns_empty_when_no_directory(self):
        mock_device = MagicMock()
        mock_device.uuid = "uuid-1"
        mock_device.execute_command.side_effect = [
            {},  # split_bag
            {"uuid-1": "find: /var/log/riouser/rosbag/: No such file or directory"},
        ]

        start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 1, 1, 0, 0, tzinfo=timezone.utc)

        bags = discover_rosbags(mock_device, start, end, "proj-guid")
        assert bags == []


# ── discover_rosbags returns BagInfo ─────────────────────────────────────────

class TestDiscoverRosbagsBagInfo:
    """discover_rosbags() must return List[BagInfo] with path + timestamps."""

    def _mock_device(self):
        mock_device = MagicMock()
        mock_device.uuid = "uuid-1"
        mock_device.execute_command.side_effect = [
            {},  # split_bag no-op
            {
                "uuid-1": (
                    "/var/log/riouser/rosbag/2025-01-01-10-09-41.bag "
                    "2025-01-01-10-48-46"
                )
            },  # find command: path + mtime
            {"uuid-1": "UTC +0000"},  # timezone command
        ]
        return mock_device

    def test_returns_bag_info_objects(self):
        from services.rio.rio_device_service import BagInfo

        mock_device = self._mock_device()
        start = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc)

        bags = discover_rosbags(mock_device, start, end, "proj-guid")
        assert len(bags) == 1
        assert isinstance(bags[0], BagInfo)

    def test_bag_info_has_correct_path(self):
        mock_device = self._mock_device()
        start = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc)

        bags = discover_rosbags(mock_device, start, end, "proj-guid")
        assert bags[0].path == "/var/log/riouser/rosbag/2025-01-01-10-09-41.bag"

    def test_bag_info_has_file_start_utc(self):
        from services.rio.rio_device_service import BagInfo

        mock_device = self._mock_device()
        start = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc)

        bags = discover_rosbags(mock_device, start, end, "proj-guid")
        assert bags[0].file_start == datetime(2025, 1, 1, 10, 9, 41, tzinfo=timezone.utc)

    def test_bag_info_has_file_end_datetime(self):
        from services.rio.rio_device_service import BagInfo

        mock_device = self._mock_device()
        start = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc)

        bags = discover_rosbags(mock_device, start, end, "proj-guid")
        # mtime "2025-01-01-10-48-46" with device UTC+0 → UTC 10:48:46
        assert bags[0].file_end == datetime(2025, 1, 1, 10, 48, 46, tzinfo=timezone.utc)


# ── trigger_device_upload ────────────────────────────────────────────────────

class TestTriggerDeviceUpload:

    def test_successful_upload(self):
        mock_device = MagicMock()
        mock_device.name = "robot-001"
        mock_device.uuid = "uuid-123"
        mock_device.status = "ONLINE"

        # Side effects: get_all_devices → [device]
        # discover: split_bag → {}, find → bags, tz → UTC
        # tar command → {}
        mock_device.execute_command.side_effect = [
            {},  # split_bag
            {"uuid-123": "/var/log/riouser/rosbag/2025-01-01-00-00-00.bag 2025-01-01-00-10-00"},
            {"uuid-123": "UTC +0000"},  # timezone
            {},  # tar command
        ]
        mock_device.upload_log_file.return_value = "upload-uuid-789"

        with patch("services.rio.rio_device_service._get_v1_client") as mock_v1:
            mock_v1.return_value.get_all_devices.return_value = [mock_device]
            mock_v1.return_value.set_project = MagicMock()

            result = trigger_device_upload(
                project_guid="proj-guid",
                organization_guid="org-guid",
                device_names=["robot-001"],
                start_time_epoch=1735689600,  # 2025-01-01T00:00:00Z
                end_time_epoch=1735690200,    # 2025-01-01T00:10:00Z
            )

        assert "robot-001" in result
        assert result["robot-001"]["status"] == "uploading"
        assert result["robot-001"]["request_uuid"] == "upload-uuid-789"
        assert "console.rapyuta.io" in result["robot-001"]["url"]

    def test_offline_device(self):
        mock_device = MagicMock()
        mock_device.name = "robot-offline"
        mock_device.uuid = "uuid-off"
        mock_device.status = "OFFLINE"

        with patch("services.rio.rio_device_service._get_v1_client") as mock_v1:
            mock_v1.return_value.get_all_devices.return_value = [mock_device]
            mock_v1.return_value.set_project = MagicMock()

            result = trigger_device_upload(
                project_guid="proj-guid",
                organization_guid="org-guid",
                device_names=["robot-offline"],
                start_time_epoch=1735689600,
                end_time_epoch=1735690200,
            )

        assert "robot-offline" in result
        assert result["robot-offline"]["status"] == "error"

    def test_no_matching_devices(self):
        mock_device = MagicMock()
        mock_device.name = "robot-other"

        with patch("services.rio.rio_device_service._get_v1_client") as mock_v1:
            mock_v1.return_value.get_all_devices.return_value = [mock_device]
            mock_v1.return_value.set_project = MagicMock()

            result = trigger_device_upload(
                project_guid="proj-guid",
                organization_guid="org-guid",
                device_names=["robot-001"],
                start_time_epoch=1735689600,
                end_time_epoch=1735690200,
            )

        assert result == {}

    def test_no_bags_found(self):
        mock_device = MagicMock()
        mock_device.name = "robot-001"
        mock_device.uuid = "uuid-123"
        mock_device.status = "ONLINE"

        mock_device.execute_command.side_effect = [
            {},  # split_bag
            {"uuid-123": "find: /var/log/riouser/rosbag/: No such file or directory"},
        ]

        with patch("services.rio.rio_device_service._get_v1_client") as mock_v1:
            mock_v1.return_value.get_all_devices.return_value = [mock_device]
            mock_v1.return_value.set_project = MagicMock()

            result = trigger_device_upload(
                project_guid="proj-guid",
                organization_guid="org-guid",
                device_names=["robot-001"],
                start_time_epoch=1735689600,
                end_time_epoch=1735690200,
            )

        assert result["robot-001"]["status"] == "error"
        assert "No rosbags" in result["robot-001"]["message"]

    def test_upload_exception_handled(self):
        mock_device = MagicMock()
        mock_device.name = "robot-001"
        mock_device.uuid = "uuid-123"
        mock_device.status = "ONLINE"

        mock_device.execute_command.side_effect = [
            {},  # split_bag
            {"uuid-123": "/var/log/riouser/rosbag/2025-01-01-00-00-00.bag 2025-01-01-00-10-00"},
            {"uuid-123": "UTC +0000"},  # timezone
            {},  # tar
        ]
        mock_device.upload_log_file.side_effect = Exception("Network timeout")

        with patch("services.rio.rio_device_service._get_v1_client") as mock_v1:
            mock_v1.return_value.get_all_devices.return_value = [mock_device]
            mock_v1.return_value.set_project = MagicMock()

            result = trigger_device_upload(
                project_guid="proj-guid",
                organization_guid="org-guid",
                device_names=["robot-001"],
                start_time_epoch=1735689600,
                end_time_epoch=1735690200,
            )

        assert result["robot-001"]["status"] == "error"
        assert "Network timeout" in result["robot-001"]["message"]


# ── Upload speed schema validation ───────────────────────────────────────────

class TestUploadSpeedSchema:

    def test_trigger_upload_request_accepts_speed(self):
        """max_upload_rate_mbps should be optional with default None."""
        from schemas.bag_analysis import RIOTriggerUploadRequest

        req = RIOTriggerUploadRequest(
            project_guid="p1",
            organization_guid="o1",
            device_names=["dev1"],
            start_time_epoch=1000,
            end_time_epoch=2000,
        )
        assert req.max_upload_rate_mbps is None

    def test_trigger_upload_request_explicit_speed(self):
        """max_upload_rate_mbps should accept a value within 1–200."""
        from schemas.bag_analysis import RIOTriggerUploadRequest

        req = RIOTriggerUploadRequest(
            project_guid="p1",
            organization_guid="o1",
            device_names=["dev1"],
            start_time_epoch=1000,
            end_time_epoch=2000,
            max_upload_rate_mbps=50,
        )
        assert req.max_upload_rate_mbps == 50

    def test_trigger_upload_request_rejects_zero_speed(self):
        """max_upload_rate_mbps=0 should be rejected (min is 1)."""
        from schemas.bag_analysis import RIOTriggerUploadRequest

        with pytest.raises(Exception):
            RIOTriggerUploadRequest(
                project_guid="p1",
                organization_guid="o1",
                device_names=["dev1"],
                start_time_epoch=1000,
                end_time_epoch=2000,
                max_upload_rate_mbps=0,
            )

    def test_trigger_upload_request_rejects_over_200(self):
        """max_upload_rate_mbps=201 should be rejected (max is 200)."""
        from schemas.bag_analysis import RIOTriggerUploadRequest

        with pytest.raises(Exception):
            RIOTriggerUploadRequest(
                project_guid="p1",
                organization_guid="o1",
                device_names=["dev1"],
                start_time_epoch=1000,
                end_time_epoch=2000,
                max_upload_rate_mbps=201,
            )

    def test_trigger_upload_request_accepts_boundary_values(self):
        """max_upload_rate_mbps should accept 1 and 200 (boundaries)."""
        from schemas.bag_analysis import RIOTriggerUploadRequest

        req1 = RIOTriggerUploadRequest(
            project_guid="p1",
            organization_guid="o1",
            device_names=["dev1"],
            start_time_epoch=1000,
            end_time_epoch=2000,
            max_upload_rate_mbps=1,
        )
        assert req1.max_upload_rate_mbps == 1

        req200 = RIOTriggerUploadRequest(
            project_guid="p1",
            organization_guid="o1",
            device_names=["dev1"],
            start_time_epoch=1000,
            end_time_epoch=2000,
            max_upload_rate_mbps=200,
        )
        assert req200.max_upload_rate_mbps == 200


# ── trigger_device_upload speed parameter ────────────────────────────────────

class TestUploadSpeedParameter:

    @patch("services.rio.rio_device_service._get_v1_client")
    def test_custom_speed_passed_to_logs_upload_request(self, mock_v1):
        """trigger_device_upload should pass max_upload_rate_bytes to LogsUploadRequest."""
        mock_device = MagicMock()
        mock_device.name = "robot-001"
        mock_device.uuid = "uuid-1"
        mock_device.status = "ONLINE"

        # discover_rosbags: split command + find command + timezone
        mock_device.execute_command.side_effect = [
            {},  # split_bag
            {"uuid-1": "/var/log/riouser/rosbag/2025-01-01-00-00-00.bag 2025-01-01-00-10-00"},
            {"uuid-1": "UTC +0000"},  # timezone
            {},  # tar command
        ]
        mock_device.upload_log_file.return_value = "req-uuid-1"

        mock_v1.return_value.get_all_devices.return_value = [mock_device]
        mock_v1.return_value.set_project = MagicMock()

        custom_rate_bytes = 10 * 1048576  # 10 MB/s

        with patch("services.rio.rio_device_service.LogsUploadRequest") as mock_req_cls:
            mock_req_cls.return_value = MagicMock()

            result = trigger_device_upload(
                project_guid="proj-guid",
                organization_guid="org-guid",
                device_names=["robot-001"],
                start_time_epoch=1735689600,
                end_time_epoch=1735690200,
                max_upload_rate_bytes=custom_rate_bytes,
            )

        # Verify LogsUploadRequest was called with our custom rate
        mock_req_cls.assert_called_once()
        call_kwargs = mock_req_cls.call_args
        assert call_kwargs[1]["max_upload_rate"] == custom_rate_bytes


# ── Background upload job system ─────────────────────────────────────────────

import time
import threading


class TestStartUploadJob:
    """Tests for the async background job-based upload system."""

    @patch("services.rio.rio_device_service._get_v1_client")
    def test_start_upload_job_returns_job_id(self, mock_v1):
        """start_upload_job should return a job_id string immediately."""
        from services.rio.rio_device_service import start_upload_job

        mock_v1.return_value.get_all_devices.return_value = []
        mock_v1.return_value.set_project = MagicMock()

        job_id = start_upload_job(
            project_guid="proj-guid",
            organization_guid="org-guid",
            device_names=["robot-001"],
            start_time_epoch=1735689600,
            end_time_epoch=1735690200,
            max_upload_rate_bytes=10 * 1048576,
        )
        assert isinstance(job_id, str)
        assert len(job_id) > 0

    @patch("services.rio.rio_device_service._get_v1_client")
    def test_start_upload_job_is_non_blocking(self, mock_v1):
        """start_upload_job should return within 2 seconds (not wait for uploads)."""
        from services.rio.rio_device_service import start_upload_job

        mock_device = MagicMock()
        mock_device.name = "robot-001"
        mock_device.uuid = "uuid-1"
        mock_device.status = "ONLINE"
        # Make execute_command slow to prove non-blocking
        mock_device.execute_command.side_effect = lambda *a, **kw: time.sleep(5)

        mock_v1.return_value.get_all_devices.return_value = [mock_device]
        mock_v1.return_value.set_project = MagicMock()

        t0 = time.monotonic()
        job_id = start_upload_job(
            project_guid="p", organization_guid="o",
            device_names=["robot-001"],
            start_time_epoch=1000, end_time_epoch=2000,
            max_upload_rate_bytes=10 * 1048576,
        )
        elapsed = time.monotonic() - t0
        assert elapsed < 2.0, f"start_upload_job blocked for {elapsed:.1f}s"
        assert isinstance(job_id, str)


class TestGetJobEvents:
    """Tests for polling job events."""

    @patch("services.rio.rio_device_service._get_v1_client")
    def test_get_job_events_returns_pending_for_new_job(self, mock_v1):
        """get_job_events should return pending events for a freshly-started job."""
        from services.rio.rio_device_service import start_upload_job, get_job_events

        mock_v1.return_value.get_all_devices.return_value = []
        mock_v1.return_value.set_project = MagicMock()

        job_id = start_upload_job(
            project_guid="p", organization_guid="o",
            device_names=["robot-001"],
            start_time_epoch=1000, end_time_epoch=2000,
            max_upload_rate_bytes=10 * 1048576,
        )
        # Give the thread a moment to emit events
        time.sleep(0.5)
        events = get_job_events(job_id)
        assert isinstance(events, list)

    def test_get_job_events_unknown_job_returns_empty(self):
        """get_job_events for a non-existent job_id should return empty list."""
        from services.rio.rio_device_service import get_job_events

        events = get_job_events("non-existent-job-id")
        assert events == []

    @patch("services.rio.rio_device_service._get_v1_client")
    def test_job_emits_link_ready_for_online_device(self, mock_v1):
        """Worker should emit a 'link_ready' event with a console URL."""
        from services.rio.rio_device_service import start_upload_job, get_job_events

        mock_device = MagicMock()
        mock_device.name = "robot-001"
        mock_device.uuid = "dev-uuid-1"
        mock_device.status = "ONLINE"
        # discover_rosbags: split (ignored) + find (no bags) + timezone
        mock_device.execute_command.side_effect = [
            {},  # split_bag
            {"dev-uuid-1": "No such file or directory"},  # find
        ]
        mock_v1.return_value.get_all_devices.return_value = [mock_device]
        mock_v1.return_value.set_project = MagicMock()

        job_id = start_upload_job(
            project_guid="proj-1", organization_guid="org-1",
            device_names=["robot-001"],
            start_time_epoch=1000, end_time_epoch=2000,
            max_upload_rate_bytes=10 * 1048576,
        )
        time.sleep(1.0)
        events = get_job_events(job_id)

        # Should have at least a link_ready event
        link_events = [e for e in events if e.get("event") == "link_ready"]
        assert len(link_events) == 1
        assert "console.rapyuta.io" in link_events[0]["url"]
        assert "dev-uuid-1" in link_events[0]["url"]

    @patch("services.rio.rio_device_service._get_v1_client")
    def test_job_emits_error_for_offline_device(self, mock_v1):
        """Worker should emit 'error' event for an offline device."""
        from services.rio.rio_device_service import start_upload_job, get_job_events

        mock_device = MagicMock()
        mock_device.name = "robot-002"
        mock_device.uuid = "dev-uuid-2"
        mock_device.status = "OFFLINE"

        mock_v1.return_value.get_all_devices.return_value = [mock_device]
        mock_v1.return_value.set_project = MagicMock()

        job_id = start_upload_job(
            project_guid="p", organization_guid="o",
            device_names=["robot-002"],
            start_time_epoch=1000, end_time_epoch=2000,
            max_upload_rate_bytes=10 * 1048576,
        )
        time.sleep(1.0)
        events = get_job_events(job_id)

        error_events = [e for e in events if e.get("event") == "error"]
        assert len(error_events) == 1
        assert "robot-002" in error_events[0]["device"]

    @patch("services.rio.rio_device_service._get_v1_client")
    def test_job_emits_done_when_all_devices_complete(self, mock_v1):
        """Worker should emit 'done' event after all devices finish."""
        from services.rio.rio_device_service import start_upload_job, get_job_events

        mock_v1.return_value.get_all_devices.return_value = []
        mock_v1.return_value.set_project = MagicMock()

        job_id = start_upload_job(
            project_guid="p", organization_guid="o",
            device_names=["nonexistent"],
            start_time_epoch=1000, end_time_epoch=2000,
            max_upload_rate_bytes=10 * 1048576,
        )
        time.sleep(1.0)
        events = get_job_events(job_id)

        done_events = [e for e in events if e.get("event") == "job_done"]
        assert len(done_events) == 1


class TestIsJobComplete:
    """Tests for is_job_complete helper."""

    @patch("services.rio.rio_device_service._get_v1_client")
    def test_completed_job(self, mock_v1):
        """is_job_complete returns True after all threads finish."""
        from services.rio.rio_device_service import start_upload_job, is_job_complete

        mock_v1.return_value.get_all_devices.return_value = []
        mock_v1.return_value.set_project = MagicMock()

        job_id = start_upload_job(
            project_guid="p", organization_guid="o",
            device_names=[],
            start_time_epoch=1000, end_time_epoch=2000,
            max_upload_rate_bytes=10 * 1048576,
        )
        time.sleep(1.0)
        assert is_job_complete(job_id) is True

    def test_unknown_job_is_complete(self):
        """Unknown job_id should be treated as complete (nothing to do)."""
        from services.rio.rio_device_service import is_job_complete

        assert is_job_complete("no-such-job") is True


# ── Multi-org list_projects tests ─────────────────────────────────────────────

class TestListProjectsMultiOrg:

    def test_list_projects_includes_extra_org(self):
        """Projects from RAPYUTA_EXTRA_ORGANIZATIONS are merged into results."""
        jp_proj = MagicMock()
        jp_proj.metadata.name = "jpn-tok-001"
        jp_proj.metadata.guid = "proj-jp"
        jp_proj.metadata.organizationGUID = "org-japan"

        us_proj = MagicMock()
        us_proj.metadata.name = "usa-chi-001"
        us_proj.metadata.guid = "proj-us"
        us_proj.metadata.organizationGUID = "org-usa"

        with patch("core.config.settings") as mock_settings, \
             patch("services.rio.rio_device_service._list_projects_for_org") as mock_extra, \
             patch("services.rio.rio_device_service._get_v2_client") as mock_v2, \
             patch("services.rio.rio_device_service.get_rio_config", return_value={"auth_token": "t", "organization_id": "", "project_id": "", "organization_name": "warehouse"}), \
             patch("services.rio.rio_device_service.walk_pages", return_value=iter([[jp_proj]])):
            mock_settings.rio_extra_organizations = "org-usa:US Warehouse"
            mock_extra.return_value = [us_proj]
            projects = list_projects()

        names = [p["name"] for p in projects]
        assert "jpn-tok-001" in names
        assert "usa-chi-001" in names

    def test_list_projects_attaches_org_name(self):
        """Each project dict must have an org_name key."""
        proj = MagicMock()
        proj.metadata.name = "jpn-tok-001"
        proj.metadata.guid = "proj-jp"
        proj.metadata.organizationGUID = "org-japan"

        with patch("core.config.settings") as mock_settings, \
             patch("services.rio.rio_device_service._get_v2_client") as mock_v2, \
             patch("services.rio.rio_device_service.get_rio_config", return_value={"auth_token": "t", "organization_id": "", "project_id": "", "organization_name": "warehouse"}), \
             patch("services.rio.rio_device_service.walk_pages", return_value=iter([[proj]])):
            mock_settings.rio_extra_organizations = ""
            projects = list_projects()

        assert "org_name" in projects[0]

    def test_deduplicates_by_guid_across_orgs(self):
        """Same project GUID from multiple orgs appears only once."""
        proj = MagicMock()
        proj.metadata.name = "jpn-tok-001"
        proj.metadata.guid = "proj-same"
        proj.metadata.organizationGUID = "org-jp"

        with patch("core.config.settings") as mock_settings, \
             patch("services.rio.rio_device_service._list_projects_for_org") as mock_extra, \
             patch("services.rio.rio_device_service._get_v2_client") as mock_v2, \
             patch("services.rio.rio_device_service.get_rio_config", return_value={"auth_token": "t", "organization_id": "", "project_id": "", "organization_name": "warehouse"}), \
             patch("services.rio.rio_device_service.walk_pages", return_value=iter([[proj]])):
            mock_settings.rio_extra_organizations = "org-us:US"
            mock_extra.return_value = [proj]
            projects = list_projects()

        assert len([p for p in projects if p["guid"] == "proj-same"]) == 1


# ── _list_projects_for_org tests ──────────────────────────────────────────────

class TestListProjectsForOrg:

    @patch("services.rio.rio_device_service.Configuration")
    @patch("services.rio.rio_device_service.get_rio_config")
    @patch("services.rio.rio_device_service.walk_pages")
    def test_uses_given_org_id(self, mock_walk, mock_cfg_fn, mock_config_cls):
        from services.rio.rio_device_service import _list_projects_for_org

        mock_cfg_fn.return_value = {"auth_token": "tok", "project_id": "p", "organization_id": "org-primary"}
        mock_cfg = MagicMock()
        mock_cfg.data = {}
        mock_config_cls.return_value = mock_cfg
        mock_v2 = MagicMock()
        mock_v2.c.headers = {"user-agent": "clean"}
        mock_cfg.new_v2_client.return_value = mock_v2

        mock_proj = MagicMock()
        mock_walk.return_value = iter([[mock_proj]])

        result = _list_projects_for_org("org-extra")

        assert mock_cfg.data["organization_id"] == "org-extra"
        assert mock_cfg.data["project_id"] == ""
        assert result == [mock_proj]

    @patch("services.rio.rio_device_service.Configuration")
    @patch("services.rio.rio_device_service.get_rio_config")
    @patch("services.rio.rio_device_service.walk_pages")
    def test_sanitizes_user_agent(self, mock_walk, mock_cfg_fn, mock_config_cls):
        from services.rio.rio_device_service import _list_projects_for_org

        mock_cfg_fn.return_value = {"auth_token": "tok", "project_id": "", "organization_id": ""}
        mock_cfg = MagicMock()
        mock_config_cls.return_value = mock_cfg
        mock_v2 = MagicMock()
        mock_v2.c.headers = {"user-agent": "sdk #106~22.04\nPREEMPT "}
        mock_cfg.new_v2_client.return_value = mock_v2
        mock_walk.return_value = iter([[]])

        _list_projects_for_org("org-extra")
        ua = mock_v2.c.headers["user-agent"]
        assert "\n" not in ua
        assert not ua.endswith(" ")


# ── get_project_name_by_guid multi-org tests ──────────────────────────────────

class TestGetProjectNameByGuid:

    def test_resolves_from_primary_org(self):
        proj = MagicMock()
        proj.metadata.guid = "proj-jp"
        proj.metadata.name = "jpn-tok-001"

        with patch("core.config.settings") as s, \
             patch("services.rio.rio_device_service._get_v2_client"), \
             patch("services.rio.rio_device_service.walk_pages", return_value=iter([[proj]])):
            s.rio_extra_organizations = ""
            result = get_project_name_by_guid("proj-jp")

        assert result == "jpn-tok-001"

    def test_resolves_from_extra_org_when_not_in_primary(self):
        us_proj = MagicMock()
        us_proj.metadata.guid = "proj-us"
        us_proj.metadata.name = "usa-chi-001"

        with patch("core.config.settings") as s, \
             patch("services.rio.rio_device_service._get_v2_client"), \
             patch("services.rio.rio_device_service._list_projects_for_org") as mock_extra, \
             patch("services.rio.rio_device_service.walk_pages", return_value=iter([[]])):
            s.rio_extra_organizations = "org-us:US"
            mock_extra.return_value = [us_proj]
            result = get_project_name_by_guid("proj-us")

        assert result == "usa-chi-001"

    def test_returns_empty_when_not_found_anywhere(self):
        with patch("core.config.settings") as s, \
             patch("services.rio.rio_device_service._get_v2_client"), \
             patch("services.rio.rio_device_service.walk_pages", return_value=iter([[]])):
            s.rio_extra_organizations = ""
            result = get_project_name_by_guid("proj-unknown")

        assert result == ""


# ── RIOProject schema org_name tests ──────────────────────────────────────────

class TestRIOProjectSchema:

    def test_org_name_field_accepted(self):
        from schemas.bag_analysis import RIOProject as Schema
        p = Schema(name="jpn-tok-001", guid="proj-jp", organization_guid="org-jp", org_name="warehouse")
        assert p.org_name == "warehouse"

    def test_org_name_defaults_to_empty_string(self):
        from schemas.bag_analysis import RIOProject as Schema
        p = Schema(name="jpn-tok-001", guid="proj-jp", organization_guid="org-jp")
        assert p.org_name == ""
