"""
schemas/bag_analysis.py — Pydantic models for the ROS Bag Log Analyzer.
"""
from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel


class BagLogAnalysisRequest(BaseModel):
    bag_path:          str
    window_start:      Optional[float] = None  # Unix ts — filter range start
    window_end:        Optional[float] = None  # Unix ts — filter range end
    issue_description: str = ""


class LogEntry(BaseModel):
    timestamp: float
    datetime:  str
    level:     str    # INFO / WARN / ERROR / FATAL / DEBUG
    node:      str    # ROS node name
    message:   str


class BagLogAnalysisResponse(BaseModel):
    status:           str
    bag_path:         str
    duration_secs:    float
    total_messages:   int
    error_count:      int
    warning_count:    int
    log_entries:      List[LogEntry]
    engine_hypothesis: str = ""
    llm_summary:      str = ""  # combined LLM analysis markdown
    # Actual tokens reported back by the LLM API (0 when using Ollama)
    actual_prompt_tokens:     int = 0
    actual_completion_tokens: int = 0
    actual_total_tokens:      int = 0
    cost_usd:                 float = 0.0


class TimelineBucket(BaseModel):
    t_start:     float
    t_end:       float
    count:       int
    error_count: int
    warn_count:  int


class BagTimeline(BaseModel):
    bag_path: str
    buckets:  List[TimelineBucket]


class MapDiffRequest(BaseModel):
    bag_path:       str
    site_id:        Optional[str] = None
    topic_override: Optional[str] = None


class MapDiffResponse(BaseModel):
    iou_score:     float   # 0.0 – 1.0
    diff_image_b64: str    # raw base64 PNG (no data: prefix)
    message:       str = ""


# ── Trajectory ─────────────────────────────────────────────────────────────────

class TrajectoryRequest(BaseModel):
    bag_path:       str
    site_id:        Optional[str] = None
    max_points:     int = 4000          # subsample cap
    topic_override: Optional[str] = None
    smooth:         bool = True         # apply path smoothing


class TrajectoryPoint(BaseModel):
    x:         float  # world-frame metres
    y:         float  # world-frame metres
    yaw:       float  # radians
    timestamp: float  # Unix time (seconds)


class TrajectoryResponse(BaseModel):
    bag_path:     str
    site_id:      Optional[str]
    topic:        str                 # pose topic used
    total_points: int                 # cleaned count before sub-sampling
    raw_count:    int = 0             # raw count before outlier removal
    points:       List[TrajectoryPoint]
    error:        Optional[str] = None
    frame_id:     Optional[str] = None  # coordinate frame ("map" or "odom")


class BagTopicInfo(BaseModel):
    topic:   str
    msgtype: str
    count:   int
    is_pose: bool = False


class BagTopicsResponse(BaseModel):
    bag_path: str
    topics:   List[BagTopicInfo]
