"""Tests for the device timezone endpoint."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


class TestDeviceTimezoneEndpoint:
    """Tests for POST /api/v1/bags/rio/device-timezone."""

    @patch("services.rio.rio_device_service.get_device_timezone_by_name")
    def test_returns_timezone_for_online_device(self, mock_tz, client):
        mock_tz.return_value = {"timezone_name": "JST", "utc_offset": "+09:00", "utc_offset_minutes": 540}
        resp = client.post("/api/v1/bags/rio/device-timezone", json={
            "project_guid": "proj-123",
            "device_name": "oksbot24",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["timezone_name"] == "JST"
        assert data["utc_offset"] == "+09:00"
        assert data["utc_offset_minutes"] == 540

    @patch("services.rio.rio_device_service.get_device_timezone_by_name")
    def test_returns_utc_when_device_offline(self, mock_tz, client):
        mock_tz.return_value = {"timezone_name": "UTC", "utc_offset": "+00:00", "utc_offset_minutes": 0}
        resp = client.post("/api/v1/bags/rio/device-timezone", json={
            "project_guid": "proj-123",
            "device_name": "oksbot99",
        })
        assert resp.status_code == 200
        assert resp.json()["timezone_name"] == "UTC"
