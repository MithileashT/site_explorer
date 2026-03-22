"""
services/ros/trajectory_extractor.py
──────────────────────────────────────
Extracts AMR trajectory (pose sequence) from ROS1 (.bag) and ROS2 (.db3) bag
files using the rosbags AnyReader which handles both formats transparently.

Supported pose topics (checked in priority order) — map-frame topics first:
  /amcl_pose                         geometry_msgs/PoseWithCovarianceStamped
  /robot_pose                        geometry_msgs/PoseStamped
  /agent_pose                        geometry_msgs/PoseStamped
  /localization/particle_pose        geometry_msgs/PoseWithCovarianceStamped
  /ndt_pose                          geometry_msgs/PoseStamped
  /current_pose                      geometry_msgs/PoseStamped
  /pose                              geometry_msgs/PoseStamped
  /edge_broadcaster/agent_poses      geometry_msgs/PoseArray (first element)
  /move_base_flex/navigate/feedback  (feedback.current_pose.pose)
  /lwm/agent_status                  (nav_status.mrrp_destination)
  /odom                              nav_msgs/Odometry

The extractor picks the first topic (by priority) that is present in the bag
and returns up to `max_points` evenly sub-sampled pose records.

Features:
  - Outlier removal (teleport jumps > threshold)
  - Optional Savitzky-Golay smoothing
  - Topic listing with message counts

AnyReader is imported at module level so it can be patched in tests.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.logging import get_logger

logger = get_logger(__name__)

try:
    from rosbags.highlevel import AnyReader
except ImportError:
    AnyReader = None  # type: ignore[assignment,misc]

# Topics checked in priority order; first match wins.
# Map-frame topics are prioritised over odom-frame topics so that the
# trajectory coordinates already match the map origin / resolution.
POSE_TOPICS_PRIORITY: List[str] = [
    "/amcl_pose",                           # map frame — AMCL localisation
    "/robot_pose",                          # map frame — fleet manager pose
    "/agent_pose",                          # map frame — agent localisation
    "/localization/particle_pose",          # map frame — particle filter
    "/ndt_pose",                            # map frame — NDT localisation
    "/current_pose",                        # map frame — common alias
    "/pose",                                # map frame — generic pose
    "/edge_broadcaster/agent_poses",        # map frame — PoseArray (first pose)
    "/move_base_flex/navigate/feedback",    # map frame — MBF navigate feedback
    "/lwm/agent_status",                    # map frame — LWM agent status
    "/odom",                                # odom frame — last resort ⚠
]

# Topics known to publish in the odom frame (not map-aligned).
_ODOM_FRAME_TOPICS: set[str] = {"/odom"}

# ── Fixed navigation topics for trajectory analysis ──────────────────────────
# These 6 topics represent the full AMR navigation pipeline.
NAV_TOPICS_FIXED: List[Dict[str, str]] = [
    {"topic": "/move_base_flex/navigate/goal", "role": "Goal", "description": "Navigation goal sent to MBF action server"},
    {"topic": "/move_base_flex/GlobalPlanner/plan", "role": "Global Plan", "description": "Global path computed by planner"},
    {"topic": "/move_base_flex/DWAPlannerROS/local_plan", "role": "Local Plan", "description": "Local obstacle avoidance path (DWA)"},
    {"topic": "/cmd_vel", "role": "Velocity Command", "description": "Velocity commands sent to motors"},
    {"topic": "/move_base_flex/navigate/feedback", "role": "Nav Feedback", "description": "Real-time navigation progress + current pose"},
    {"topic": "/move_base_flex/navigate/result", "role": "Nav Result", "description": "Navigation action result and error code"},
]

# Minimum number of points needed to form a meaningful trajectory
MIN_TRAJECTORY_POINTS = 2
DEFAULT_MAX_POINTS = 4000

# Outlier removal: skip point if it teleports > this distance (metres) from previous
OUTLIER_JUMP_THRESHOLD = 2.0


def _quat_to_yaw(x: float, y: float, z: float, w: float) -> float:
    """Convert quaternion (z-up convention) to yaw angle in radians."""
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _extract_frame_id(msg: Any) -> Optional[str]:
    """Extract header.frame_id from a ROS message if available."""
    try:
        if hasattr(msg, "header") and hasattr(msg.header, "frame_id"):
            return str(msg.header.frame_id)
    except (AttributeError, TypeError):
        pass
    return None


def _extract_pose_from_msg(msg: Any, topic: str) -> Optional[tuple[float, float, float]]:
    """
    Parse x, y, yaw from a ROS message whose type depends on the topic.

    Returns (x, y, yaw_rad) or None if the message layout is unrecognised.
    """
    try:
        # MBF navigate feedback: feedback.current_pose.pose
        if topic == "/move_base_flex/navigate/feedback":
            fb = getattr(msg, "feedback", None)
            if fb is not None:
                cp = getattr(fb, "current_pose", None)
                if cp is not None:
                    pose = getattr(cp, "pose", cp)
                    pos = pose.position
                    ori = pose.orientation
                    yaw = _quat_to_yaw(ori.x, ori.y, ori.z, ori.w)
                    return float(pos.x), float(pos.y), yaw

        # Action goal (NavigateActionGoal): goal.target_pose.pose
        if topic == "/move_base_flex/navigate/goal":
            goal = getattr(msg, "goal", None)
            if goal is not None:
                tp = getattr(goal, "target_pose", None)
                if tp is not None:
                    pose = getattr(tp, "pose", tp)
                    pos = pose.position
                    ori = pose.orientation
                    yaw = _quat_to_yaw(ori.x, ori.y, ori.z, ori.w)
                    return float(pos.x), float(pos.y), yaw

        # Action result (NavigateActionResult): result.pose or nested
        if topic == "/move_base_flex/navigate/result":
            res = getattr(msg, "result", None)
            if res is not None:
                # Try result.pose.position (PoseStamped-like)
                rpose = getattr(res, "pose", None)
                if rpose is not None:
                    pos = getattr(rpose, "position", None)
                    ori = getattr(rpose, "orientation", None)
                    if pos is not None and ori is not None:
                        yaw = _quat_to_yaw(ori.x, ori.y, ori.z, ori.w)
                        return float(pos.x), float(pos.y), yaw

        # LWM agent status: nav_status.mrrp_destination (Pose)
        if topic == "/lwm/agent_status":
            ns = getattr(msg, "nav_status", None)
            if ns is not None:
                dest = getattr(ns, "mrrp_destination", None)
                if dest is not None:
                    pos = dest.position
                    ori = dest.orientation
                    yaw = _quat_to_yaw(ori.x, ori.y, ori.z, ori.w)
                    return float(pos.x), float(pos.y), yaw

        # nav_msgs/Path: array of PoseStamped — use last waypoint (endpoint)
        if hasattr(msg, "poses") and hasattr(msg.poses, "__len__") and len(msg.poses) > 0:
            first_el = msg.poses[0]
            if hasattr(first_el, "pose") and hasattr(first_el.pose, "position"):
                last_ps = msg.poses[-1]
                pos = last_ps.pose.position
                ori = last_ps.pose.orientation
                yaw = _quat_to_yaw(ori.x, ori.y, ori.z, ori.w)
                return float(pos.x), float(pos.y), yaw

        # PoseArray: use first pose in the array (edge_broadcaster/agent_poses)
        if hasattr(msg, "poses") and hasattr(msg.poses, "__len__"):
            poses_arr = msg.poses
            if len(poses_arr) > 0:
                pose = poses_arr[0]
                pos = pose.position
                ori = pose.orientation
                yaw = _quat_to_yaw(ori.x, ori.y, ori.z, ori.w)
                return float(pos.x), float(pos.y), yaw

        # nav_msgs/Odometry  pose.pose.position / pose.pose.orientation
        if hasattr(msg, "pose") and hasattr(msg.pose, "pose"):
            pos = msg.pose.pose.position
            ori = msg.pose.pose.orientation
            yaw = _quat_to_yaw(ori.x, ori.y, ori.z, ori.w)
            return float(pos.x), float(pos.y), yaw

        # geometry_msgs/PoseStamped  pose.position / pose.orientation
        if hasattr(msg, "pose") and hasattr(msg.pose, "position"):
            pos = msg.pose.position
            ori = msg.pose.orientation
            yaw = _quat_to_yaw(ori.x, ori.y, ori.z, ori.w)
            return float(pos.x), float(pos.y), yaw

        # geometry_msgs/Pose (direct)  position / orientation
        if hasattr(msg, "position") and hasattr(msg, "orientation"):
            pos = msg.position
            ori = msg.orientation
            yaw = _quat_to_yaw(ori.x, ori.y, ori.z, ori.w)
            return float(pos.x), float(pos.y), yaw

    except (AttributeError, TypeError, ValueError) as exc:
        logger.debug("_extract_pose_from_msg(%s) failed: %s", topic, exc)

    return None


def _subsample(items: List[Any], max_count: int) -> List[Any]:
    """Return a uniformly sub-sampled list of at most `max_count` items."""
    if len(items) <= max_count:
        return items
    step = len(items) / max_count
    return [items[round(i * step)] for i in range(max_count)]


def _remove_outliers(
    points: List[Dict[str, float]], threshold: float = OUTLIER_JUMP_THRESHOLD
) -> List[Dict[str, float]]:
    """Remove points that jump > threshold metres from the previous point (TF jumps)."""
    if len(points) < 2:
        return points
    cleaned: List[Dict[str, float]] = [points[0]]
    for pt in points[1:]:
        prev = cleaned[-1]
        dx = pt["x"] - prev["x"]
        dy = pt["y"] - prev["y"]
        dist = math.sqrt(dx * dx + dy * dy)
        if dist <= threshold:
            cleaned.append(pt)
    return cleaned


def _smooth_trajectory(
    points: List[Dict[str, float]], window: int = 5
) -> List[Dict[str, float]]:
    """Apply simple moving-average smoothing to x,y coordinates.

    Uses a symmetric window around each point.  Preserves first/last points
    exactly and keeps yaw/timestamp unchanged.
    """
    n = len(points)
    if n < window:
        return points
    half = window // 2
    smoothed: List[Dict[str, float]] = []
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        count = hi - lo
        sx = sum(points[j]["x"] for j in range(lo, hi)) / count
        sy = sum(points[j]["y"] for j in range(lo, hi)) / count
        smoothed.append({
            "x": sx,
            "y": sy,
            "yaw": points[i]["yaw"],
            "timestamp": points[i]["timestamp"],
        })
    return smoothed


class TrajectoryExtractor:
    """
    Extracts AMR pose trajectory from ROS1 or ROS2 bag files.

    Usage::

        extractor = TrajectoryExtractor("amr01.bag")
        result    = extractor.extract(max_points=3000)
        # result["points"] -> list of {"x", "y", "yaw", "timestamp"}
        # result["topic"]  -> topic name that was used
        # result["total"]  -> raw count before sub-sampling
    """

    def __init__(self, bag_path: str) -> None:
        self.bag_path = bag_path

    def extract(
        self,
        max_points: int = DEFAULT_MAX_POINTS,
        topic_override: Optional[str] = None,
        smooth: bool = True,
    ) -> Dict[str, Any]:
        """
        Extract trajectory from the bag.

        Returns a dict with keys:
          - ``points``: list[dict]  - each has x, y, yaw, timestamp
          - ``topic``:  str         - topic that was read
          - ``total``:  int         - raw point count before sub-sampling
          - ``error``:  str | None  - error message if extraction failed
          - ``raw_count``: int      - raw count before outlier removal
        """
        if AnyReader is None:
            return self._error("rosbags library is not installed.")

        bag = Path(self.bag_path)
        if not bag.exists():
            return self._error(f"Bag file not found: {self.bag_path}")

        bag_start_time: Optional[float] = None
        bag_end_time: Optional[float] = None

        try:
            with AnyReader([bag]) as reader:
                available = {c.topic for c in reader.connections}

                # Capture the true bag time range from all connections
                try:
                    bag_start_time = reader.start_time / 1_000_000_000.0
                    bag_end_time = reader.end_time / 1_000_000_000.0
                except Exception:
                    pass  # not all readers expose start/end_time

                # Determine which topic to read
                if topic_override and topic_override in available:
                    chosen_topic = topic_override
                else:
                    chosen_topic = next(
                        (t for t in POSE_TOPICS_PRIORITY if t in available),
                        None,
                    )

                if chosen_topic is None:
                    avail_str = ", ".join(sorted(available)[:20])
                    return self._error(
                        f"No pose topic found in bag. Checked: "
                        f"{POSE_TOPICS_PRIORITY}. Available: {avail_str}"
                    )

                connections = [
                    c for c in reader.connections if c.topic == chosen_topic
                ]
                raw_points: List[Dict[str, float]] = []

                frame_id: Optional[str] = None

                for connection, timestamp_ns, rawdata in reader.messages(
                    connections=connections
                ):
                    msg = reader.deserialize(rawdata, connection.msgtype)
                    # Capture frame_id from the first message
                    if frame_id is None:
                        frame_id = _extract_frame_id(msg)
                    result = _extract_pose_from_msg(msg, chosen_topic)
                    if result is None:
                        continue
                    wx, wy, yaw = result
                    # Skip NaN / Inf values that sometimes appear at bag start
                    if not (math.isfinite(wx) and math.isfinite(wy)):
                        continue
                    raw_points.append(
                        {
                            "x":         wx,
                            "y":         wy,
                            "yaw":       yaw,
                            "timestamp": timestamp_ns / 1_000_000_000.0,
                        }
                    )

        except Exception as exc:
            logger.exception(
                "TrajectoryExtractor.extract failed for %s", self.bag_path
            )
            return self._error(str(exc))

        total_raw = len(raw_points)
        if total_raw < MIN_TRAJECTORY_POINTS:
            return self._error(
                f"Only {total_raw} valid pose sample(s) found in topic {chosen_topic!r}."
                " A minimum of 2 is required to draw a trajectory."
            )

        # Sort by timestamp — bag messages can arrive out of order
        raw_points.sort(key=lambda p: p["timestamp"])

        # Remove outlier jumps (TF frame switches, teleportation artefacts)
        cleaned = _remove_outliers(raw_points)
        removed_outliers = total_raw - len(cleaned)
        if removed_outliers > 0:
            logger.info(
                "TrajectoryExtractor: removed %d outlier jump(s) from %s",
                removed_outliers, bag.name,
            )

        # Apply smoothing if requested and we have enough points
        if smooth and len(cleaned) >= 5:
            cleaned = _smooth_trajectory(cleaned)

        total = len(cleaned)
        if total < MIN_TRAJECTORY_POINTS:
            return self._error(
                f"Only {total} valid pose(s) remain after outlier removal "
                f"(from {total_raw} raw) in topic {chosen_topic!r}."
            )

        sampled = _subsample(cleaned, max_points)

        # Determine the coordinate frame; warn if it's odom (not map-aligned)
        is_odom = chosen_topic in _ODOM_FRAME_TOPICS or (
            frame_id is not None and "odom" in frame_id.lower()
        )
        if is_odom:
            logger.warning(
                "TrajectoryExtractor: %s uses odom-frame topic %s "
                "(frame_id=%s). Coordinates may not align with the map.",
                bag.name, chosen_topic, frame_id,
            )

        logger.info(
            "TrajectoryExtractor: %s - %d raw -> %d cleaned -> %d sampled from %s (frame=%s)",
            bag.name,
            total_raw,
            total,
            len(sampled),
            chosen_topic,
            frame_id or "unknown",
        )
        # Fallback: if bag-level times are unavailable, use pose timestamps
        if bag_start_time is None and sampled:
            bag_start_time = sampled[0]["timestamp"]
        if bag_end_time is None and sampled:
            bag_end_time = sampled[-1]["timestamp"]

        return {
            "points":         sampled,
            "topic":          chosen_topic,
            "total":          total,
            "raw_count":      total_raw,
            "error":          None,
            "frame_id":       frame_id or ("odom" if is_odom else "map"),
            "bag_start_time": bag_start_time,
            "bag_end_time":   bag_end_time,
        }

    def list_topics(self) -> List[Dict[str, Any]]:
        """List all topics in the bag with message types and counts.

        Returns a list of dicts: {topic, msgtype, count, is_pose}.
        """
        if AnyReader is None:
            return []

        bag = Path(self.bag_path)
        if not bag.exists():
            return []

        try:
            with AnyReader([bag]) as reader:
                topic_info: Dict[str, Dict[str, Any]] = {}
                for conn in reader.connections:
                    key = conn.topic
                    if key not in topic_info:
                        topic_info[key] = {
                            "topic": key,
                            "msgtype": conn.msgtype,
                            "count": 0,
                            "is_pose": key in POSE_TOPICS_PRIORITY,
                        }
                    topic_info[key]["count"] += conn.msgcount if hasattr(conn, "msgcount") else 0
        except Exception as exc:
            logger.warning("list_topics failed for %s: %s", self.bag_path, exc)
            return []

        # Enrich with navigation topic metadata
        nav_meta = {nt["topic"]: nt for nt in NAV_TOPICS_FIXED}
        for key, info in topic_info.items():
            if key in nav_meta:
                info["is_nav"] = True
                info["nav_role"] = nav_meta[key]["role"]
                info["nav_description"] = nav_meta[key]["description"]
            else:
                info["is_nav"] = False
                info["nav_role"] = ""
                info["nav_description"] = ""

        # Sort: pose topics first (in priority order), then the rest alphabetically
        pose_set = set(POSE_TOPICS_PRIORITY)
        pose_keys = [t for t in POSE_TOPICS_PRIORITY if t in topic_info]
        other_keys = sorted(k for k in topic_info if k not in pose_set)
        return [topic_info[k] for k in pose_keys + other_keys]

    @staticmethod
    def _error(msg: str) -> Dict[str, Any]:
        logger.warning("TrajectoryExtractor: %s", msg)
        return {"points": [], "topic": "", "total": 0, "raw_count": 0, "error": msg, "frame_id": None, "bag_start_time": None, "bag_end_time": None}
