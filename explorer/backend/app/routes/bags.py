"""
app/routes/bags.py — ROS bag upload, timeline, log analysis, map diff.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import os
import pathlib
import re
import uuid

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from core.config import settings
from core.logging import get_logger
from schemas.bag_analysis import (
    BagLogAnalysisRequest, BagLogAnalysisResponse, BagTimeline, MapDiffRequest,
    MapDiffResponse, LogEntry, TimelineBucket,
    TrajectoryRequest, TrajectoryResponse, TrajectoryPoint,
    BagTopicInfo, BagTopicsResponse,
    NavTopicStatus, NavTopicsResponse,
    RIOFetchRequest, RIOFetchResponse, RIOStatusResponse,
    RIOProject, RIOProjectsResponse, RIODevicesRequest, RIODevicesResponse,
    RIOTriggerUploadRequest, RIOTriggerUploadResponse, RIODeviceUploadStatus,
    RIOUploadJobResponse,
    RIODeviceTimezoneRequest, RIODeviceTimezoneResponse,
    RIODiscoverBagsRequest, RIODiscoverBagsResponse,
)
from services.ros.log_extractor import ROSLogExtractor
from services.ros.log_analyzer_engine import LogAnalyzerEngine
from services.ros.map_processor import process_bag_for_changes
from services.ros.trajectory_extractor import TrajectoryExtractor
from services.rio import rio_service
from services.rio import rio_device_service
from services.rio.rio_service import (
    RioNotConfiguredError, RioConfigMalformedError,
    is_bag_archive, extract_bag_archive,
)

logger = get_logger(__name__)
router = APIRouter()

_llm_service  = None
_site_manager = None

ALLOWED_EXTENSIONS = {".bag", ".db3"}
MAX_UPLOAD_BYTES    = 600 * 1024 * 1024  # 600 MB
MAX_LOG_ENTRIES     = 2_000              # max log lines returned to the UI


def _validate_bag_extension(bag_path: str) -> None:
    """Raise 422 if the file is not a supported bag format (.bag/.db3)."""
    ext = pathlib.Path(bag_path).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            422,
            f"Unsupported file type: {ext!r}. "
            "Expected a .bag or .db3 file. "
            "If this is an archive (.tar.xz), re-fetch it via the RIO panel "
            "which now auto-extracts bags from archives.",
        )


def register_singletons(llm, site_mgr):
    global _llm_service, _site_manager
    _llm_service  = llm
    _site_manager = site_mgr


def _save_upload(file: UploadFile) -> tuple[str, int]:
    """Save an uploaded bag file; returns (absolute path, byte count).

    The file is stored using the sanitised original filename so users can
    identify their bags in the UI.  On collision a short hex suffix is appended
    to keep the name recognisable while avoiding overwrites.
    """
    upload_dir = pathlib.Path(settings.bag_upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    original = pathlib.Path(file.filename or "upload.bag")
    suffix = original.suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {suffix!r}. Use .bag or .db3")

    # Sanitise: keep word chars, dots, hyphens; collapse sequences of
    # other chars to a single underscore; limit stem length to 80 chars.
    safe_stem = re.sub(r"[^\w.\-]+", "_", original.stem).strip("_")[:80] or "upload"
    dest = upload_dir / f"{safe_stem}{suffix}"
    if dest.exists():
        dest = upload_dir / f"{safe_stem}_{uuid.uuid4().hex[:8]}{suffix}"

    content = file.file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File exceeds 600 MB limit.")
    with open(dest, "wb") as fh:
        fh.write(content)

    logger.info("Saved bag: %s (%d bytes)", dest, len(content))
    return str(dest), len(content)


def _map_log(raw: dict) -> LogEntry:
    """Map extractor's internal dict (log_level/node_name) to LogEntry schema."""
    return LogEntry(
        timestamp = raw["timestamp"],
        datetime  = raw.get("datetime", ""),
        level     = raw.get("log_level", "INFO"),
        node      = raw.get("node_name", ""),
        message   = raw.get("message",   ""),
    )


def _map_bucket(b: dict) -> TimelineBucket:
    """Map extractor's internal bucket dict to TimelineBucket schema."""
    return TimelineBucket(
        t_start     = b["from_ts"],
        t_end       = b["to_ts"],
        count       = b["total"],
        error_count = b["error"],
        warn_count  = b["warn"],
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/api/v1/bags/upload", tags=["bags"])
async def upload_bag(file: UploadFile = File(...)):
    bag_path, nbytes = _save_upload(file)
    return {
        "bag_path": bag_path,
        "size_mb":  round(nbytes / (1024 * 1024), 2),
    }


@router.get("/api/v1/bags/timeline", tags=["bags"])
def bag_timeline(
    bag_path:  str = Query(...),
    n_buckets: int = Query(300, ge=10, le=1000),
):
    if not os.path.exists(bag_path):
        raise HTTPException(404, f"Bag not found: {bag_path}")
    _validate_bag_extension(bag_path)

    try:
        extractor = ROSLogExtractor(bag_path)
        logs      = extractor.extract()
        raw_bkts  = extractor.get_timeline_buckets(logs, n_buckets)
    except Exception as e:
        logger.error("bag_timeline(%s): %s", bag_path, e)
        raise HTTPException(422, f"Could not read bag timeline: {e}")

    return BagTimeline(
        bag_path = bag_path,
        buckets  = [_map_bucket(b) for b in raw_bkts],
    )


@router.post("/api/v1/bags/analyze", tags=["bags"])
def analyze_bag_logs(req: BagLogAnalysisRequest):
    if not os.path.exists(req.bag_path):
        raise HTTPException(404, f"Bag not found: {req.bag_path}")
    _validate_bag_extension(req.bag_path)

    # ── 1. Extract logs and apply optional window filter ──────────────────────
    extractor = ROSLogExtractor(req.bag_path)
    all_logs  = extractor.extract()

    if req.window_start is not None and req.window_end is not None:
        filtered = [l for l in all_logs
                    if req.window_start <= l["timestamp"] <= req.window_end]
    else:
        filtered = all_logs

    # ── 2. Compute summary stats ─────────────────────────────────────────────
    duration_secs = 0.0
    if all_logs:
        duration_secs = all_logs[-1]["timestamp"] - all_logs[0]["timestamp"]

    error_count   = sum(1 for l in filtered if l["log_level"] in ("ERROR", "FATAL"))
    warning_count = sum(1 for l in filtered if l["log_level"] == "WARN")

    # ── 3. Rule-based anomaly detection ──────────────────────────────────────
    engine_hypothesis: str  = ""
    try:
        engine        = LogAnalyzerEngine(req.bag_path)
        engine_result = engine.analyze()
        engine_hypothesis = engine_result.get("summary", {}).get("hypothesis", "")
    except Exception as e:
        logger.warning("LogAnalyzerEngine failed: %s", e)

    # ── 4. LLM analysis ───────────────────────────────────────────────────────
    llm_summary = ""
    if _llm_service and filtered:
        incident_ts = (
            (req.window_start + req.window_end) / 2
            if req.window_start is not None and req.window_end is not None
            else (all_logs[0]["timestamp"] if all_logs else 0.0)
        )
        incident_dt = datetime.datetime.utcfromtimestamp(incident_ts).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        try:
            sections = _llm_service.generate_log_incident_summary(
                robot_name        = os.path.basename(req.bag_path),
                incident_time     = incident_dt,
                filtered_logs     = filtered,
                priority_logs     = extractor.priority_logs(filtered),
                issue_description = req.issue_description,
                engine_hypothesis = engine_hypothesis,
            )
            llm_summary = "\n\n".join(
                f"### {k.replace('_', ' ').title()}\n{v}"
                for k, v in sections.items() if v
            )
        except Exception as e:
            logger.error("LLM analysis failed: %s", e)

    # ── 5. Build response ─────────────────────────────────────────────────────
    usage = getattr(_llm_service, "last_usage", {})
    return BagLogAnalysisResponse(
        status            = "ok",
        bag_path          = req.bag_path,
        duration_secs     = round(duration_secs, 3),
        total_messages    = len(all_logs),
        error_count       = error_count,
        warning_count     = warning_count,
        log_entries       = [_map_log(l) for l in filtered[:MAX_LOG_ENTRIES]],
        engine_hypothesis = engine_hypothesis,
        llm_summary       = llm_summary,
        actual_prompt_tokens     = usage.get("prompt_tokens", 0),
        actual_completion_tokens = usage.get("completion_tokens", 0),
        actual_total_tokens      = usage.get("total_tokens", 0),
        cost_usd                 = usage.get("cost_usd", 0.0),
    )


@router.post("/api/v1/bags/mapdiff", tags=["bags"])
def map_diff(req: MapDiffRequest):
    """Compare a bag's map against the reference site map."""
    if not os.path.exists(req.bag_path):
        raise HTTPException(404, f"Bag not found: {req.bag_path}")

    if not _site_manager:
        raise HTTPException(503, "Site manager not available.")

    map_data = _site_manager.get_map_image(req.site_id or "", dark_mode=False) if req.site_id else None
    if not map_data:
        # Return a neutral response when there is no reference map
        return MapDiffResponse(iou_score=0.0, diff_image_b64="", message="No reference map available.")

    cfg = _site_manager.get_config(req.site_id) if req.site_id else {}

    try:
        b64_raw = map_data["b64"].split(",")[-1]
        diff_b64, score = process_bag_for_changes(
            bag_path         = pathlib.Path(req.bag_path),
            original_map_b64 = b64_raw,
            resolution       = cfg.get("resolution", 0.05),
            origin           = cfg.get("origin", [0.0, 0.0, 0.0]),
        )
    except Exception as e:
        logger.error("map_diff failed: %s", e)
        raise HTTPException(500, str(e))

    if diff_b64 is None:
        raise HTTPException(500, "Map diff computation failed.")

    return MapDiffResponse(
        iou_score      = round(min(1.0, max(0.0, score / 100.0)), 4),
        diff_image_b64 = diff_b64,          # raw base64, no data: prefix
        message        = f"IoU score: {score:.1f}%",
    )


@router.post("/api/v1/bags/trajectory", tags=["bags"])
def extract_trajectory(req: TrajectoryRequest):
    """Extract AMR trajectory path from a ROS bag and return world-frame poses."""
    if not os.path.exists(req.bag_path):
        raise HTTPException(404, f"Bag not found: {req.bag_path}")

    max_pts = max(2, min(10_000, req.max_points))
    extractor = TrajectoryExtractor(req.bag_path)
    result = extractor.extract(
        max_points=max_pts,
        topic_override=req.topic_override,
        smooth=req.smooth,
    )

    if result["error"] and not result["points"]:
        raise HTTPException(422, result["error"])

    points = [
        TrajectoryPoint(
            x=p["x"], y=p["y"], yaw=p["yaw"], timestamp=p["timestamp"]
        )
        for p in result["points"]
    ]

    return TrajectoryResponse(
        bag_path       = req.bag_path,
        site_id        = req.site_id,
        topic          = result["topic"],
        total_points   = result["total"],
        raw_count      = result.get("raw_count", result["total"]),
        points         = points,
        error          = result["error"],
        frame_id       = result.get("frame_id"),
        bag_start_time = result.get("bag_start_time"),
        bag_end_time   = result.get("bag_end_time"),
    )


@router.get("/api/v1/bags/topics", tags=["bags"])
def list_bag_topics(bag_path: str = Query(...)):
    """List all topics in a ROS bag with message types and counts."""
    if not os.path.exists(bag_path):
        raise HTTPException(404, f"Bag not found: {bag_path}")

    extractor = TrajectoryExtractor(bag_path)
    topics = extractor.list_topics()

    return BagTopicsResponse(
        bag_path=bag_path,
        topics=[BagTopicInfo(**t) for t in topics],
    )


@router.get("/api/v1/bags/nav-topics", tags=["bags"])
def list_nav_topics(bag_path: str = Query(...)):
    """Return status of the 6 fixed navigation topics for a bag."""
    if not os.path.exists(bag_path):
        raise HTTPException(404, f"Bag not found: {bag_path}")

    from services.ros.trajectory_extractor import NAV_TOPICS_FIXED

    extractor = TrajectoryExtractor(bag_path)
    all_topics = extractor.list_topics()
    available_map = {t["topic"]: t for t in all_topics}

    nav_statuses = []
    for nt in NAV_TOPICS_FIXED:
        found = available_map.get(nt["topic"])
        nav_statuses.append(NavTopicStatus(
            topic=nt["topic"],
            role=nt["role"],
            description=nt["description"],
            available=found is not None,
            msgtype=found["msgtype"] if found else "",
            count=found["count"] if found else 0,
        ))

    return NavTopicsResponse(bag_path=bag_path, nav_topics=nav_statuses)


# ── RIO Bag Fetch ─────────────────────────────────────────────────────────────

@router.get("/api/v1/bags/rio/status", tags=["bags"])
def rio_status():
    """Return RIO CLI configuration status."""
    try:
        config = rio_service.get_rio_config()
        configured = True
        has_token = bool(config["auth_token"])
        has_org = bool(config["organization_id"])
        has_proj = bool(config["project_id"])
        organization = config["organization_id"]
        project = config["project_id"]
    except (RioNotConfiguredError, RioConfigMalformedError):
        configured = has_token = has_org = has_proj = False
        organization = project = ""

    return RIOStatusResponse(
        configured=configured,
        has_token=has_token,
        has_organization=has_org,
        has_project=has_proj,
        rio_cli_available=rio_service.is_rio_cli_available(),
        organization=organization,
        project=project,
    )


@router.post("/api/v1/bags/rio/fetch", tags=["bags"])
def rio_fetch(req: RIOFetchRequest):
    """Download a bag from RIO (shared URL or device upload)."""
    import subprocess

    has_url = bool(req.shared_url)
    has_device = bool(req.device and req.filename)

    if has_url == has_device:
        raise HTTPException(422, "Provide either shared_url, or device + filename.")

    try:
        if has_url:
            dest = rio_service.download_shared_url(
                req.shared_url,
                project_override=req.project_override or "",
            )
            source = "shared_url"
        else:
            dest = rio_service.download_device_upload(
                device=req.device,
                filename=req.filename,
                project_override=req.project_override or "",
            )
            source = "device_upload"
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RioNotConfiguredError as e:
        raise HTTPException(503, str(e))
    except RioConfigMalformedError as e:
        raise HTTPException(503, str(e))
    except FileNotFoundError as e:
        raise HTTPException(503, str(e))
    except subprocess.TimeoutExpired:
        raise HTTPException(
            504,
            f"Device download timed out after {settings.rio_download_timeout} seconds.",
        )
    except RuntimeError as e:
        raise HTTPException(502, str(e))

    size_bytes = dest.stat().st_size

    # If the downloaded file is a tar archive, extract .bag/.db3 files from it
    extracted_bags: list[str] | None = None
    if is_bag_archive(dest):
        bags_dir = pathlib.Path(settings.bag_upload_dir)
        extracted = extract_bag_archive(dest, bags_dir)
        if extracted:
            extracted_bags = [str(p) for p in extracted]
            dest = extracted[0]  # primary bag = first (sorted by name)
            size_bytes = dest.stat().st_size
        else:
            raise HTTPException(
                422,
                "Archive downloaded but contained no .bag or .db3 files.",
            )

    return RIOFetchResponse(
        bag_path=str(dest),
        filename=dest.name,
        size_mb=round(size_bytes / (1024 * 1024), 2),
        source=source,
        extracted_bags=extracted_bags,
    )


# ── RIO Device Upload ────────────────────────────────────────────────────────

@router.get("/api/v1/bags/rio/projects", tags=["bags"])
def rio_projects():
    """List RIO projects accessible to the configured user."""
    try:
        raw = rio_device_service.list_projects()
        projects = [RIOProject(**p) for p in raw]
        return RIOProjectsResponse(projects=projects)
    except Exception as e:
        logger.error("rio_projects failed: %s", e)
        raise HTTPException(503, str(e))


@router.post("/api/v1/bags/rio/devices", tags=["bags"])
def rio_devices(req: RIODevicesRequest):
    """List online devices in a RIO project."""
    try:
        devices = rio_device_service.list_online_devices(req.project_guid)
        return RIODevicesResponse(devices=devices, project_guid=req.project_guid)
    except Exception as e:
        logger.error("rio_devices failed: %s", e)
        raise HTTPException(503, str(e))


@router.post("/api/v1/bags/rio/trigger-upload", tags=["bags"])
def rio_trigger_upload(req: RIOTriggerUploadRequest):
    """Trigger rosbag upload from RIO devices (background job).

    Returns a job_id immediately.  Connect to the SSE endpoint
    /api/v1/bags/rio/upload-status/{job_id} to receive progress events.
    """
    try:
        rate_bytes = (req.max_upload_rate_mbps or 10) * 1048576
        job_id = rio_device_service.start_upload_job(
            project_guid=req.project_guid,
            organization_guid=req.organization_guid,
            device_names=req.device_names,
            start_time_epoch=req.start_time_epoch,
            end_time_epoch=req.end_time_epoch,
            max_upload_rate_bytes=rate_bytes,
            display_start=req.display_start or "",
            display_end=req.display_end or "",
            timezone_label=req.timezone_label or "",
            utc_offset_minutes=req.utc_offset_minutes,
            site_code=req.site_code or "",
        )
        return RIOUploadJobResponse(job_id=job_id)
    except Exception as e:
        logger.error("rio_trigger_upload failed: %s", e)
        raise HTTPException(503, str(e))


@router.post("/api/v1/bags/rio/device-timezone", tags=["bags"])
def rio_device_timezone(req: RIODeviceTimezoneRequest):
    """Get the timezone of a RIO device (via SSH date command)."""
    try:
        result = rio_device_service.get_device_timezone_by_name(
            req.project_guid, req.device_name,
        )
        return RIODeviceTimezoneResponse(device_name=req.device_name, **result)
    except Exception as e:
        logger.error("rio_device_timezone failed: %s", e)
        raise HTTPException(503, str(e))


@router.post("/api/v1/bags/rio/discover-bags", tags=["bags"])
def rio_discover_bags(req: RIODiscoverBagsRequest):
    """Preview which rosbags would be uploaded for a given time range."""
    try:
        result = rio_device_service.discover_rosbags_by_name(
            project_guid=req.project_guid,
            device_name=req.device_name,
            start_time_epoch=req.start_time_epoch,
            end_time_epoch=req.end_time_epoch,
        )
        return RIODiscoverBagsResponse(**result)
    except rio_device_service.RioDeviceError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        logger.error("rio_discover_bags failed: %s", e)
        raise HTTPException(503, str(e))


@router.get("/api/v1/bags/rio/upload-status/{job_id}", tags=["bags"])
async def rio_upload_status(job_id: str):
    """SSE stream — sends per-device progress events for an upload job.

    Events are newline-delimited JSON objects with an 'event' field.
    The stream ends after emitting a 'job_done' event.
    """
    async def event_generator():
        while True:
            events = rio_device_service.get_job_events(job_id)
            for ev in events:
                yield f"data: {json.dumps(ev)}\n\n"
                if ev.get("event") == "job_done":
                    return
            # Also check completion in case job_done was already drained
            if not events and rio_device_service.is_job_complete(job_id):
                yield f"data: {json.dumps({'event': 'job_done'})}\n\n"
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

