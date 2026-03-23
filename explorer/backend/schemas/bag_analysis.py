"""
schemas/bag_analysis.py — Pydantic models for the ROS Bag Log Analyzer.
"""
from __future__ import annotations
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


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
    bag_path:       str
    site_id:        Optional[str]
    topic:          str                 # pose topic used
    total_points:   int                 # cleaned count before sub-sampling
    raw_count:      int = 0             # raw count before outlier removal
    points:         List[TrajectoryPoint]
    error:          Optional[str] = None
    frame_id:       Optional[str] = None  # coordinate frame ("map" or "odom")
    bag_start_time: Optional[float] = None  # bag true start time (Unix seconds)
    bag_end_time:   Optional[float] = None  # bag true end time (Unix seconds)


class BagTopicInfo(BaseModel):
    topic:   str
    msgtype: str
    count:   int
    is_pose: bool = False
    is_nav:  bool = False
    nav_role: str = ""
    nav_description: str = ""


class BagTopicsResponse(BaseModel):
    bag_path: str
    topics:   List[BagTopicInfo]


class NavTopicStatus(BaseModel):
    topic:       str
    role:        str
    description: str
    available:   bool
    msgtype:     str = ""
    count:       int = 0


class NavTopicsResponse(BaseModel):
    bag_path:   str
    nav_topics: List[NavTopicStatus]


# ── RIO Bag Fetch ──────────────────────────────────────────────────────────────

class RIOFetchRequest(BaseModel):
    shared_url:       Optional[str] = None
    device:           Optional[str] = None
    filename:         Optional[str] = None
    project_override: Optional[str] = None


class RIOFetchResponse(BaseModel):
    bag_path:        str
    filename:        str
    size_mb:         float
    source:          str   # "shared_url" or "device_upload"
    extracted_bags:  Optional[List[str]] = None  # present when archive was extracted


class RIOStatusResponse(BaseModel):
    configured:        bool
    has_token:         bool
    has_organization:  bool
    has_project:       bool
    rio_cli_available: bool
    organization:      str = ""
    project:           str = ""


# ── RIO Device Upload ─────────────────────────────────────────────────────────

class RIOProject(BaseModel):
    name:              str
    guid:              str
    organization_guid: str
    org_name:          str = ""


class RIOProjectsResponse(BaseModel):
    projects: List[RIOProject]


class RIODevicesRequest(BaseModel):
    project_guid: str


class RIODevicesResponse(BaseModel):
    devices:      List[str]
    project_guid: str


class RIOTriggerUploadRequest(BaseModel):
    project_guid:      str
    organization_guid: str
    device_names:      List[str]
    start_time_epoch:  int
    end_time_epoch:    int
    max_upload_rate_mbps: Optional[int] = Field(default=None, ge=1, le=200)
    # Human-readable display strings for tar filename (user's local timezone)
    display_start:    Optional[str] = None   # e.g. "2026-03-22T10:00"
    display_end:      Optional[str] = None   # e.g. "2026-03-22T11:00"
    timezone_label:   Optional[str] = None   # e.g. "JST", "IST", "UTC"
    utc_offset_minutes: Optional[int] = None  # e.g. 540 for JST, -300 for EST
    site_code:        Optional[str] = None   # e.g. "ash-kki-001" — RIO project name


class RIODeviceUploadStatus(BaseModel):
    status:       str                    # "uploading" | "error"
    message:      str
    filename:     Optional[str] = None
    url:          Optional[str] = None
    request_uuid: Optional[str] = None


class RIOTriggerUploadResponse(BaseModel):
    results: Dict[str, RIODeviceUploadStatus]


class RIOUploadJobResponse(BaseModel):
    job_id: str


class RIODeviceTimezoneRequest(BaseModel):
    project_guid: str
    device_name: str


class RIODeviceTimezoneResponse(BaseModel):
    device_name: str
    timezone_name: str       # e.g. "JST", "UTC"
    utc_offset: str          # e.g. "+09:00", "+00:00"
    utc_offset_minutes: int  # e.g. 540, 0 — for frontend epoch math


class RIODiscoverBagsRequest(BaseModel):
    project_guid: str
    device_name: str
    start_time_epoch: int
    end_time_epoch: int


class RIODiscoverBagsResponse(BaseModel):
    device_name: str
    bags: List[str]
    count: int
