"""Tests for the discover-bags preview endpoint."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


class TestDiscoverPreview:
    @patch("services.rio.rio_device_service.discover_rosbags_by_name")
    def test_returns_discovered_bags(self, mock_discover, client):
        mock_discover.return_value = {
            "device_name": "oksbot24",
            "bags": [
                "/var/log/riouser/rosbag/2025-06-01-10-00-00.bag",
                "/var/log/riouser/rosbag/2025-06-01-10-05-00.bag",
            ],
            "count": 2,
        }
        resp = client.post("/api/v1/bags/rio/discover-bags", json={
            "project_guid": "proj-123",
            "device_name": "oksbot24",
            "start_time_epoch": 1748764800,
            "end_time_epoch": 1748768400,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["bags"]) == 2

    @patch("services.rio.rio_device_service.discover_rosbags_by_name")
    def test_returns_empty_when_no_bags(self, mock_discover, client):
        mock_discover.return_value = {
            "device_name": "oksbot24",
            "bags": [],
            "count": 0,
        }
        resp = client.post("/api/v1/bags/rio/discover-bags", json={
            "project_guid": "proj-123",
            "device_name": "oksbot24",
            "start_time_epoch": 1748764800,
            "end_time_epoch": 1748768400,
        })
        assert resp.status_code == 200
        assert resp.json()["count"] == 0
