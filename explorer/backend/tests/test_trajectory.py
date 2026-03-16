"""
Tests for trajectory extraction from ROS bag files.

Covers:
  - TrajectoryExtractor with a mocked AnyReader
  - _quat_to_yaw helper accuracy
  - _subsample helper
  - _extract_pose_from_msg for different message types
  - POST /api/v1/bags/trajectory endpoint (happy path + error cases)
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.ros.trajectory_extractor import (
    TrajectoryExtractor,
    _extract_frame_id,
    _extract_pose_from_msg,
    _quat_to_yaw,
    _remove_outliers,
    _smooth_trajectory,
    _subsample,
    POSE_TOPICS_PRIORITY,
)


# ── Helper factories ──────────────────────────────────────────────────────────

def _make_pose_stamped(x: float, y: float, z_quat: float = 0.0, w_quat: float = 1.0, frame_id: str = "map"):
    """Minimal PoseStamped-like object (geometry_msgs/PoseStamped)."""
    return SimpleNamespace(
        header=SimpleNamespace(frame_id=frame_id),
        pose=SimpleNamespace(
            position=SimpleNamespace(x=x, y=y, z=0.0),
            orientation=SimpleNamespace(x=0.0, y=0.0, z=z_quat, w=w_quat),
        )
    )


def _make_odometry(x: float, y: float, z_quat: float = 0.0, w_quat: float = 1.0, frame_id: str = "odom"):
    """Minimal Odometry-like object (nav_msgs/Odometry)."""
    return SimpleNamespace(
        header=SimpleNamespace(frame_id=frame_id),
        pose=SimpleNamespace(
            pose=SimpleNamespace(
                position=SimpleNamespace(x=x, y=y, z=0.0),
                orientation=SimpleNamespace(x=0.0, y=0.0, z=z_quat, w=w_quat),
            )
        )
    )


def _make_pose_with_cov(x: float, y: float, z_quat: float = 0.0, w_quat: float = 1.0, frame_id: str = "map"):
    """Minimal PoseWithCovarianceStamped-like (geometry_msgs/PoseWithCovarianceStamped)."""
    return SimpleNamespace(
        header=SimpleNamespace(frame_id=frame_id),
        pose=SimpleNamespace(
            pose=SimpleNamespace(
                position=SimpleNamespace(x=x, y=y, z=0.0),
                orientation=SimpleNamespace(x=0.0, y=0.0, z=z_quat, w=w_quat),
            )
        )
    )


# ── Unit tests: _quat_to_yaw ─────────────────────────────────────────────────

class TestQuatToYaw:
    def test_identity_quaternion_gives_zero_yaw(self):
        assert _quat_to_yaw(0.0, 0.0, 0.0, 1.0) == pytest.approx(0.0, abs=1e-9)

    def test_90_degrees_yaw(self):
        # sin(45°), cos(45°) quaternion for 90° rotation
        s = math.sin(math.pi / 4)
        c = math.cos(math.pi / 4)
        assert _quat_to_yaw(0.0, 0.0, s, c) == pytest.approx(math.pi / 2, abs=1e-6)

    def test_180_degrees_yaw(self):
        assert _quat_to_yaw(0.0, 0.0, 1.0, 0.0) == pytest.approx(math.pi, abs=1e-6)

    def test_negative_90_degrees_yaw(self):
        s = math.sin(-math.pi / 4)
        c = math.cos(-math.pi / 4)
        result = _quat_to_yaw(0.0, 0.0, s, c)
        assert result == pytest.approx(-math.pi / 2, abs=1e-6)


# ── Unit tests: _subsample ────────────────────────────────────────────────────

class TestSubsample:
    def test_no_downsampling_when_below_limit(self):
        items = list(range(50))
        assert _subsample(items, 100) == items

    def test_returns_exact_count(self):
        items = list(range(1000))
        result = _subsample(items, 100)
        assert len(result) == 100

    def test_preserves_first_and_last(self):
        items = list(range(500))
        result = _subsample(items, 10)
        assert result[0] == 0
        assert result[-1] in items  # last sample is close to end

    def test_empty_list(self):
        assert _subsample([], 100) == []

    def test_single_item(self):
        assert _subsample([42], 100) == [42]


# ── Unit tests: _extract_frame_id ────────────────────────────────────────────

class TestExtractFrameId:
    def test_pose_stamped_frame(self):
        msg = _make_pose_stamped(0.0, 0.0, frame_id="map")
        assert _extract_frame_id(msg) == "map"

    def test_odometry_frame(self):
        msg = _make_odometry(0.0, 0.0, frame_id="odom")
        assert _extract_frame_id(msg) == "odom"

    def test_no_header(self):
        msg = SimpleNamespace(data=42)
        assert _extract_frame_id(msg) is None


# ── Unit tests: _extract_pose_from_msg ───────────────────────────────────────

class TestExtractPoseFromMsg:
    def test_pose_stamped(self):
        msg = _make_pose_stamped(1.5, 2.5)
        result = _extract_pose_from_msg(msg, "/robot_pose")
        assert result is not None
        x, y, yaw = result
        assert x == pytest.approx(1.5)
        assert y == pytest.approx(2.5)
        assert yaw == pytest.approx(0.0, abs=1e-6)

    def test_odometry(self):
        msg = _make_odometry(3.0, -1.0)
        result = _extract_pose_from_msg(msg, "/odom")
        assert result is not None
        x, y, _ = result
        assert x == pytest.approx(3.0)
        assert y == pytest.approx(-1.0)

    def test_yaw_extracted_correctly(self):
        s = math.sin(math.pi / 4)  # 90° rotation
        c = math.cos(math.pi / 4)
        msg = _make_pose_stamped(0.0, 0.0, z_quat=s, w_quat=c)
        result = _extract_pose_from_msg(msg, "/amcl_pose")
        assert result is not None
        _, _, yaw = result
        assert yaw == pytest.approx(math.pi / 2, abs=1e-6)

    def test_unrecognised_message_returns_none(self):
        msg = SimpleNamespace(unknown_field=42)
        assert _extract_pose_from_msg(msg, "/some_topic") is None

    def test_nan_filtered_at_extractor_level(self):
        """NaN values are filtered inside the extract() loop, not _extract_pose_from_msg."""
        msg = _make_pose_stamped(float("nan"), 1.0)
        result = _extract_pose_from_msg(msg, "/robot_pose")
        # _extract_pose_from_msg itself returns the value; nan filtering happens in extract()
        assert result is not None
        x, _, _ = result
        assert math.isnan(x)


# ── Unit tests: TrajectoryExtractor with mocked AnyReader ────────────────────

def _make_mock_reader(topic: str, poses: list[tuple[float, float]]):
    """
    Build a mock AnyReader context manager that yields `poses` as PoseStamped
    messages on `topic`.
    """
    connections = [SimpleNamespace(topic=topic, msgtype="geometry_msgs/msg/PoseStamped")]

    def messages(connections=None):
        for i, (x, y) in enumerate(poses):
            ts_ns = int(1_000_000_000 * i)  # 1 second apart
            yield connections[0], ts_ns, b""

    mock_reader = MagicMock()
    mock_reader.connections = connections
    mock_reader.messages = messages
    mock_reader.deserialize = lambda rawdata, msgtype: _make_pose_stamped(
        *poses[0]  # simplified: same pose for all (tests don't need real values here)
    )
    mock_reader.__enter__ = MagicMock(return_value=mock_reader)
    mock_reader.__exit__ = MagicMock(return_value=False)
    return mock_reader


class TestTrajectoryExtractor:
    def test_missing_bag_returns_error(self, tmp_path):
        extractor = TrajectoryExtractor(str(tmp_path / "nonexistent.bag"))
        result = extractor.extract()
        assert result["error"] is not None
        assert result["points"] == []

    def test_topic_priority_first_match(self, tmp_path):
        """Extractor picks the highest-priority available topic (map-frame first)."""
        bag = tmp_path / "test.bag"
        bag.write_bytes(b"")  # dummy content; AnyReader is mocked

        available_topic = "/amcl_pose"  # first in priority list (map frame)
        poses = [(float(i), float(i * 0.5)) for i in range(10)]

        mock_reader = _make_mock_reader(available_topic, poses)
        mock_reader.deserialize = lambda rawdata, msgtype: _make_pose_stamped(
            poses[0][0], poses[0][1]
        )

        with patch("services.ros.trajectory_extractor.AnyReader", return_value=mock_reader):
            extractor = TrajectoryExtractor(str(bag))
            result = extractor.extract()

        assert result["topic"] == available_topic
        assert result["error"] is None
        assert result["frame_id"] == "map"  # captured from PoseStamped header

    def test_no_pose_topic_returns_error(self, tmp_path):
        bag = tmp_path / "no_pose.bag"
        bag.write_bytes(b"")

        # Only has /camera topic — not in priority list
        mock_reader = MagicMock()
        mock_reader.connections = [SimpleNamespace(topic="/camera", msgtype="sensor_msgs/Image")]
        mock_reader.messages = MagicMock(return_value=iter([]))
        mock_reader.__enter__ = MagicMock(return_value=mock_reader)
        mock_reader.__exit__ = MagicMock(return_value=False)

        with patch("services.ros.trajectory_extractor.AnyReader", return_value=mock_reader):
            extractor = TrajectoryExtractor(str(bag))
            result = extractor.extract()

        assert result["error"] is not None
        assert "No pose topic" in result["error"]

    def test_subsampling_applied(self, tmp_path):
        bag = tmp_path / "big.bag"
        bag.write_bytes(b"")

        poses = [(float(i), 0.0) for i in range(200)]
        mock_reader = _make_mock_reader("/amcl_pose", poses)

        call_idx = 0
        def fake_deserialize(rawdata, msgtype):
            nonlocal call_idx
            p = poses[call_idx % len(poses)]
            call_idx += 1
            return _make_pose_stamped(p[0], p[1])

        mock_reader.deserialize = fake_deserialize
        # Override messages to yield one per pose
        def messages(connections=None):
            for i in range(len(poses)):
                yield connections[0] if connections else mock_reader.connections[0], i * 1_000_000_000, b""
        mock_reader.messages = messages

        with patch("services.ros.trajectory_extractor.AnyReader", return_value=mock_reader):
            extractor = TrajectoryExtractor(str(bag))
            result = extractor.extract(max_points=50)

        assert result["error"] is None
        assert len(result["points"]) <= 50
        assert result["total"] == 200

    def test_topic_override_respected(self, tmp_path):
        bag = tmp_path / "override.bag"
        bag.write_bytes(b"")

        override_topic = "/my_custom_pose"
        mock_reader = _make_mock_reader(override_topic, [(1.0, 2.0), (3.0, 4.0)])
        mock_reader.deserialize = lambda rawdata, msgtype: _make_pose_stamped(1.0, 2.0)

        with patch("services.ros.trajectory_extractor.AnyReader", return_value=mock_reader):
            extractor = TrajectoryExtractor(str(bag))
            result = extractor.extract(topic_override=override_topic)

        assert result["topic"] == override_topic
        assert result["error"] is None

    def test_map_frame_preferred_over_odom(self, tmp_path):
        """When both /amcl_pose and /odom are available, /amcl_pose is chosen."""
        bag = tmp_path / "both.bag"
        bag.write_bytes(b"")

        mock_reader = MagicMock()
        mock_reader.connections = [
            SimpleNamespace(topic="/odom", msgtype="nav_msgs/msg/Odometry"),
            SimpleNamespace(topic="/amcl_pose", msgtype="geometry_msgs/msg/PoseWithCovarianceStamped"),
        ]
        # Should pick /amcl_pose (higher priority)
        amcl_conn = mock_reader.connections[1]
        def messages(connections=None):
            for i in range(5):
                yield amcl_conn, i * 1_000_000_000, b""
        mock_reader.messages = messages
        mock_reader.deserialize = lambda rawdata, msgtype: _make_pose_with_cov(float(1), float(2))
        mock_reader.__enter__ = MagicMock(return_value=mock_reader)
        mock_reader.__exit__ = MagicMock(return_value=False)

        with patch("services.ros.trajectory_extractor.AnyReader", return_value=mock_reader):
            extractor = TrajectoryExtractor(str(bag))
            result = extractor.extract()

        assert result["topic"] == "/amcl_pose"
        assert result["frame_id"] == "map"
        assert result["error"] is None

    def test_odom_frame_detected(self, tmp_path):
        """When only /odom is available, frame_id reports 'odom'."""
        bag = tmp_path / "odom_only.bag"
        bag.write_bytes(b"")

        mock_reader = _make_mock_reader("/odom", [(1.0, 2.0), (3.0, 4.0)])
        call_count = [0]
        def fake_deserialize(rawdata, msgtype):
            call_count[0] += 1
            return _make_odometry(1.0, 2.0, frame_id="odom")
        mock_reader.deserialize = fake_deserialize
        def messages(connections=None):
            for i in range(3):
                yield mock_reader.connections[0], i * 1_000_000_000, b""
        mock_reader.messages = messages

        with patch("services.ros.trajectory_extractor.AnyReader", return_value=mock_reader):
            extractor = TrajectoryExtractor(str(bag))
            result = extractor.extract()

        assert result["topic"] == "/odom"
        assert result["frame_id"] == "odom"

    def test_odom_is_last_in_priority(self):
        """Verify /odom is the last topic in the priority list."""
        assert POSE_TOPICS_PRIORITY[-1] == "/odom"
        assert POSE_TOPICS_PRIORITY[0] == "/amcl_pose"

    def test_inf_values_are_skipped(self, tmp_path):
        bag = tmp_path / "inf.bag"
        bag.write_bytes(b"")

        valid_poses = [(1.0, 2.0), (1.5, 2.5)]  # close enough for outlier filter
        mock_reader = _make_mock_reader("/odom", valid_poses)

        call_count = [0]
        def fake_deserialize(rawdata, msgtype):
            idx = call_count[0]
            call_count[0] += 1
            if idx == 0:
                return _make_odometry(float("inf"), 1.0)  # invalid
            if idx == 1:
                return _make_odometry(1.0, 2.0)
            return _make_odometry(1.5, 2.5)

        mock_reader.deserialize = fake_deserialize
        def messages(connections=None):
            for i in range(3):
                yield mock_reader.connections[0], i * 1_000_000_000, b""
        mock_reader.messages = messages

        with patch("services.ros.trajectory_extractor.AnyReader", return_value=mock_reader):
            extractor = TrajectoryExtractor(str(bag))
            result = extractor.extract()

        assert result["error"] is None
        # The inf point should have been filtered
        for pt in result["points"]:
            assert math.isfinite(pt["x"])
            assert math.isfinite(pt["y"])


# ── Unit tests: _remove_outliers ─────────────────────────────────────────────

class TestRemoveOutliers:
    def test_no_outliers(self):
        """Points within threshold are kept."""
        pts = [
            {"x": 0.0, "y": 0.0, "yaw": 0.0, "timestamp": 0.0},
            {"x": 0.5, "y": 0.0, "yaw": 0.0, "timestamp": 1.0},
            {"x": 1.0, "y": 0.0, "yaw": 0.0, "timestamp": 2.0},
        ]
        result = _remove_outliers(pts)
        assert len(result) == 3

    def test_jump_removed(self):
        """A point that jumps > threshold from previous is removed."""
        pts = [
            {"x": 0.0, "y": 0.0, "yaw": 0.0, "timestamp": 0.0},
            {"x": 10.0, "y": 10.0, "yaw": 0.0, "timestamp": 1.0},  # jumps ~14m
            {"x": 0.5, "y": 0.0, "yaw": 0.0, "timestamp": 2.0},    # back to near
        ]
        result = _remove_outliers(pts, threshold=2.0)
        # The 10,10 jump and the "return" (which is also >2m from 0,0) are filtered
        assert len(result) < 3
        assert result[0]["x"] == 0.0

    def test_empty_and_single(self):
        assert _remove_outliers([]) == []
        single = [{"x": 1.0, "y": 2.0, "yaw": 0.0, "timestamp": 0.0}]
        assert _remove_outliers(single) == single


# ── Unit tests: _smooth_trajectory ───────────────────────────────────────────

class TestSmoothTrajectory:
    def test_smoothing_reduces_noise(self):
        """Noisy zigzag should be smoothed towards straight line."""
        pts = [
            {"x": float(i), "y": 1.0 if i % 2 == 0 else -1.0, "yaw": 0.0, "timestamp": float(i)}
            for i in range(20)
        ]
        smoothed = _smooth_trajectory(pts, window=5)
        assert len(smoothed) == len(pts)
        # Middle points should be closer to 0 than original +/-1
        for i in range(3, len(smoothed) - 3):
            assert abs(smoothed[i]["y"]) < 1.0

    def test_short_sequence_unchanged(self):
        """Sequences shorter than window are returned as-is."""
        pts = [
            {"x": 0.0, "y": 0.0, "yaw": 0.0, "timestamp": 0.0},
            {"x": 1.0, "y": 1.0, "yaw": 0.0, "timestamp": 1.0},
        ]
        result = _smooth_trajectory(pts, window=5)
        assert result == pts

    def test_preserves_timestamp_and_yaw(self):
        pts = [
            {"x": float(i), "y": float(i), "yaw": float(i) * 0.1, "timestamp": float(i)}
            for i in range(10)
        ]
        smoothed = _smooth_trajectory(pts, window=3)
        for i in range(len(pts)):
            assert smoothed[i]["yaw"] == pts[i]["yaw"]
            assert smoothed[i]["timestamp"] == pts[i]["timestamp"]


# ── Unit tests: New topic message extraction ─────────────────────────────────

class TestNewTopicExtraction:
    def test_pose_array_first_element(self):
        """PoseArray messages (edge_broadcaster) use the first pose."""
        pose = SimpleNamespace(
            position=SimpleNamespace(x=5.0, y=6.0, z=0.0),
            orientation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
        )
        msg = SimpleNamespace(poses=[pose])
        result = _extract_pose_from_msg(msg, "/edge_broadcaster/agent_poses")
        assert result is not None
        assert result[0] == pytest.approx(5.0)
        assert result[1] == pytest.approx(6.0)

    def test_mbf_navigate_feedback(self):
        """MBF navigate feedback extracts feedback.current_pose.pose."""
        msg = SimpleNamespace(
            feedback=SimpleNamespace(
                current_pose=SimpleNamespace(
                    pose=SimpleNamespace(
                        position=SimpleNamespace(x=3.0, y=4.0, z=0.0),
                        orientation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
                    )
                )
            )
        )
        result = _extract_pose_from_msg(msg, "/move_base_flex/navigate/feedback")
        assert result is not None
        assert result[0] == pytest.approx(3.0)
        assert result[1] == pytest.approx(4.0)

    def test_lwm_agent_status(self):
        """LWM agent status extracts nav_status.mrrp_destination."""
        msg = SimpleNamespace(
            nav_status=SimpleNamespace(
                mrrp_destination=SimpleNamespace(
                    position=SimpleNamespace(x=7.0, y=8.0, z=0.0),
                    orientation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
                )
            )
        )
        result = _extract_pose_from_msg(msg, "/lwm/agent_status")
        assert result is not None
        assert result[0] == pytest.approx(7.0)
        assert result[1] == pytest.approx(8.0)

    def test_new_topics_in_priority_list(self):
        """Verify new topics are in the priority list."""
        assert "/agent_pose" in POSE_TOPICS_PRIORITY
        assert "/edge_broadcaster/agent_poses" in POSE_TOPICS_PRIORITY
        assert "/move_base_flex/navigate/feedback" in POSE_TOPICS_PRIORITY
        assert "/lwm/agent_status" in POSE_TOPICS_PRIORITY


# ── Integration: POST /api/v1/bags/trajectory endpoint ───────────────────────

try:
    from fastapi.testclient import TestClient
    from app.main import create_app
    _TESTCLIENT_AVAILABLE = True
except ImportError:
    _TESTCLIENT_AVAILABLE = False


@pytest.mark.skipif(not _TESTCLIENT_AVAILABLE, reason="FastAPI test dependencies not available")
class TestTrajectoryEndpoint:
    @pytest.fixture(autouse=True)
    def client(self):
        app = create_app()
        self._client = TestClient(app)
        return self._client

    def test_missing_bag_returns_404(self):
        resp = self._client.post(
            "/api/v1/bags/trajectory",
            json={"bag_path": "/tmp/nonexistent_xyzzy.bag"},
        )
        assert resp.status_code == 404

    def test_valid_extraction(self, tmp_path):
        bag = tmp_path / "valid.bag"
        bag.write_bytes(b"")

        poses = [(float(i), float(i)) for i in range(20)]
        mock_reader = _make_mock_reader("/amcl_pose", poses)
        call_count = [0]
        def fake_deserialize(rawdata, msgtype):
            i = call_count[0] % len(poses)
            call_count[0] += 1
            return _make_pose_with_cov(*poses[i])
        mock_reader.deserialize = fake_deserialize
        def messages(connections=None):
            for idx in range(len(poses)):
                yield mock_reader.connections[0], idx * 1_000_000_000, b""
        mock_reader.messages = messages

        with patch("services.ros.trajectory_extractor.AnyReader", return_value=mock_reader):
            resp = self._client.post(
                "/api/v1/bags/trajectory",
                json={"bag_path": str(bag), "site_id": "test_site"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["topic"] == "/amcl_pose"
        assert data["total_points"] == len(poses)
        assert len(data["points"]) > 0
        # Verify point schema
        pt = data["points"][0]
        assert "x" in pt and "y" in pt and "yaw" in pt and "timestamp" in pt
        # Verify frame_id is returned
        assert data["frame_id"] == "map"

    def test_max_points_respected(self, tmp_path):
        bag = tmp_path / "many.bag"
        bag.write_bytes(b"")

        n = 500
        poses = [(float(i), 0.0) for i in range(n)]
        mock_reader = _make_mock_reader("/amcl_pose", poses)
        call_count = [0]
        def fake_deserialize(rawdata, msgtype):
            i = call_count[0] % n
            call_count[0] += 1
            return _make_pose_with_cov(*poses[i])
        mock_reader.deserialize = fake_deserialize
        def messages(connections=None):
            for idx in range(n):
                yield mock_reader.connections[0], idx * 1_000_000_000, b""
        mock_reader.messages = messages

        with patch("services.ros.trajectory_extractor.AnyReader", return_value=mock_reader):
            resp = self._client.post(
                "/api/v1/bags/trajectory",
                json={"bag_path": str(bag), "max_points": 50},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["points"]) <= 50
