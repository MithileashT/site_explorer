"""
app/routes/sitemap.py
─────────────────────
Interactive site map endpoints.
Serves sootballs_sites data: map images, spots, racks, regions,
robot lists, and ROS bag upload for the sitemap page.
"""
from __future__ import annotations

import os
import pathlib
import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from core.config import settings
from core.logging import get_logger
from services.ros.log_extractor import ROSLogExtractor
from services.sitemap.git_manager import GitRepoManager
from services.sitemap.service import SiteMapService

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/sitemap", tags=["sitemap"])

_svc: Optional[SiteMapService] = None
_git_mgr: Optional[GitRepoManager] = None

# ── Bag upload constants ───────────────────────────────────────────────────────
ALLOWED_BAG_EXTENSIONS = {".bag", ".db3"}
MAX_BAG_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB


def _get_git() -> GitRepoManager:
    global _git_mgr
    if _git_mgr is None:
        _git_mgr = GitRepoManager(settings.sootballs_repo_root)
    return _git_mgr


def _get_svc() -> SiteMapService:
    global _svc
    if _svc is None:
        _svc = SiteMapService(settings.sootballs_sites_root, _get_git())
    return _svc


class BranchOverrideRequest(BaseModel):
    branch: str


# ── Branch endpoints (MUST come before /{site_id}/... to avoid path conflicts) ─

@router.get("/branches")
def list_branches():
    """List all remote branch names available for branch override."""
    return _get_git().list_all_remote_branches()


@router.post("/sync")
def sync_repo():
    """
    Run ``git fetch origin --prune`` to update remote refs.
    Returns the number of site-specific branches found.
    """
    git = _get_git()
    git.fetch(force=True)
    branches = git.list_site_branches()
    return {"branches_found": len(branches)}


@router.get("/{site_id}/branch")
def get_site_branch(site_id: str):
    """
    Return branch resolution info for a site:
    which branch is used, whether it is site-specific or main,
    whether a manual override is active, the last commit, and
    the filtered list of available branches (main + valid site branches only).
    """
    git  = _get_git()
    svc  = _get_svc()
    ref  = git.resolve_branch(site_id)
    short = ref.replace("origin/", "", 1)
    site_branches = git.list_site_branches()
    site_ids = [s["id"] for s in svc.list_sites()]
    return {
        "branch":             short,
        "ref":                ref,
        "is_site_specific":   short in site_branches,
        "is_override":        git.is_override(site_id),
        "last_commit":        git.get_last_commit(ref),
        "available_branches": git.list_clean_branches(site_ids),
    }


@router.post("/{site_id}/branch")
def set_site_branch(site_id: str, body: BranchOverrideRequest):
    """Override which branch to use when loading data for *site_id*."""
    git  = _get_git()
    svc  = _get_svc()
    git.set_override(site_id, body.branch)
    ref   = git.resolve_branch(site_id)
    short = ref.replace("origin/", "", 1)
    site_branches = git.list_site_branches()
    site_ids = [s["id"] for s in svc.list_sites()]
    return {
        "branch":             short,
        "ref":                ref,
        "is_site_specific":   short in site_branches,
        "is_override":        True,
        "last_commit":        git.get_last_commit(ref),
        "available_branches": git.list_clean_branches(site_ids),
    }


@router.delete("/{site_id}/branch")
def clear_site_branch(site_id: str):
    """Remove the branch override for *site_id* (revert to auto-detect)."""
    git  = _get_git()
    svc  = _get_svc()
    git.clear_override(site_id)
    ref   = git.resolve_branch(site_id)
    short = ref.replace("origin/", "", 1)
    site_branches = git.list_site_branches()
    site_ids = [s["id"] for s in svc.list_sites()]
    return {
        "branch":             short,
        "ref":                ref,
        "is_site_specific":   short in site_branches,
        "is_override":        False,
        "last_commit":        git.get_last_commit(ref),
        "available_branches": git.list_clean_branches(site_ids),
    }


# ── Branch cleanup ─────────────────────────────────────────────────────────────

@router.get("/cleanup/plan")
def get_cleanup_plan():
    """
    Dry-run: return which remote-tracking refs would be removed and which
    would be kept.  Nothing is modified.

    A branch is *valid* iff its name is ``main`` or it exactly matches
    a known site ID (e.g. ``mncyok001``).  All other branches (feature
    branches, hotfixes, typos, CI scratch branches …) are *invalid*.
    """
    git      = _get_git()
    svc      = _get_svc()
    site_ids = [s["id"] for s in svc.list_sites()]
    return git.get_branch_cleanup_plan(site_ids)


@router.post("/cleanup")
def run_cleanup():
    """
    Execute the branch cleanup:
    - Keep ``main`` and any branch named after a known site ID.
    - Delete local remote-tracking refs for every other branch.

    **Safe**: only ``refs/remotes/origin/*`` local refs are deleted.
    The actual branches on the remote server are untouched.
    Site configs and working-tree files are not affected.
    """
    git      = _get_git()
    svc      = _get_svc()
    site_ids = [s["id"] for s in svc.list_sites()]
    result   = git.prune_invalid_remote_refs(site_ids)
    logger.info(
        "Branch cleanup: removed=%d kept=%d errors=%d",
        len(result["removed"]), len(result["kept"]), len(result["errors"]),
    )
    return result


# ── Sites ──────────────────────────────────────────────────────────────────────

@router.get("/sites")
def list_sites():
    """List all available sites in the sootballs_sites repository."""
    return _get_svc().list_sites()


@router.get("/markers")
def get_all_markers():
    """
    Return AR marker poses for **all** sites, each entry annotated with
    ``site_id``.  Sites without ``markers.yaml`` are silently skipped.

    Response shape::

        {
          "markers": [{"site_id": "actsgm001", "id": 0, "x": 2.2, ...}, ...],
          "site_count": 12,
          "total": 250
        }
    """
    return _get_svc().get_all_markers()


@router.get("/{site_id}/map")
def get_site_map(site_id: str, dark_mode: bool = Query(True)):
    """
    Return the site's navigation map as a base64-encoded PNG together with
    its coordinate metadata (resolution, origin, width, height).
    """
    svc  = _get_svc()
    meta = svc.get_map_meta(site_id)
    img  = svc.get_map_image(site_id, dark_mode)
    if img is None:
        raise HTTPException(404, f"No map image found for site '{site_id}'")

    native_res = float(meta.get("resolution", 0.05))
    served_w = int(img.get("width", 0) or 0)
    served_h = int(img.get("height", 0) or 0)

    # Prefer explicit native image dimensions from the service. If unavailable,
    # fall back to metadata dimensions for backward compatibility.
    native_size = svc.get_native_map_size(site_id)
    if native_size is not None:
        native_w, native_h = native_size
    else:
        native_w = int(meta.get("width", 0) or 0)
        native_h = int(meta.get("height", 0) or 0)

    effective_res = native_res
    if served_w > 0 and served_h > 0 and native_w > 0 and native_h > 0:
        scale_x = served_w / native_w
        scale_y = served_h / native_h
        if scale_x > 0 and scale_y > 0:
            # Map rendering should be uniformly scaled. If not, use X scale
            # as the primary conversion factor and emit a warning.
            if abs(scale_x - scale_y) > 1e-6:
                logger.warning(
                    "get_site_map(%s): non-uniform map scaling native=%dx%d served=%dx%d "
                    "(sx=%.6f sy=%.6f)",
                    site_id,
                    native_w,
                    native_h,
                    served_w,
                    served_h,
                    scale_x,
                    scale_y,
                )
            effective_res = native_res / scale_x

    return {
        "resolution": effective_res,
        "origin":     meta["origin"],
        "width":      img["width"],
        "height":     img["height"],
        "b64":        img["b64"],
    }


@router.get("/{site_id}/data")
def get_site_data(site_id: str):
    """
    Return parsed site fixtures: spots, racks, regions, robots, nodes, edges.
    """
    return _get_svc().get_site_data(site_id)


@router.get("/{site_id}/markers")
def get_markers(site_id: str):
    """
    Return AR marker poses from config/param/markers.yaml.
    Positions are in world coordinates (metres, ROS map frame).
    Yaw is in radians.
    """
    return _get_svc().get_markers(site_id)


# ── Bag upload for sitemap page ────────────────────────────────────────────────

def _save_sitemap_bag(file: UploadFile) -> tuple[str, int]:
    """Save an uploaded bag file; returns (absolute path, byte count)."""
    upload_dir = pathlib.Path(settings.bag_upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    original = pathlib.Path(file.filename or "upload.bag")
    suffix = original.suffix.lower()
    if suffix not in ALLOWED_BAG_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {suffix!r}. Use .bag or .db3")

    safe_stem = re.sub(r"[^\w.\-]+", "_", original.stem).strip("_")[:80] or "upload"
    dest = upload_dir / f"{safe_stem}{suffix}"
    if dest.exists():
        dest = upload_dir / f"{safe_stem}_{uuid.uuid4().hex[:8]}{suffix}"

    content = file.file.read()
    if len(content) > MAX_BAG_UPLOAD_BYTES:
        raise HTTPException(413, "File exceeds 500 MB limit.")
    with open(dest, "wb") as fh:
        fh.write(content)

    logger.info("Saved sitemap bag: %s (%d bytes)", dest, len(content))
    return str(dest), len(content)


def _detect_site(logs: list[dict]) -> str:
    """Try to auto-detect site ID from log entries."""
    try:
        sites = _get_svc().list_sites()
    except Exception:
        return ""
    site_ids = [s["id"] for s in sites]
    if not site_ids:
        return ""

    text_block = " ".join(
        f"{entry.get('node_name', '')} {entry.get('message', '')}"
        for entry in logs[:500]
    ).lower()

    for sid in site_ids:
        if sid.lower() in text_block:
            return sid
    return ""


def _get_bag_topics(bag_path: str) -> list[dict]:
    """Extract topic list with message counts from a bag file."""
    try:
        from rosbags.highlevel import AnyReader
        from pathlib import Path as P
        topics = []
        with AnyReader([P(bag_path)]) as reader:
            for conn in reader.connections:
                count = sum(
                    1 for c, _, _ in reader.messages([conn])
                )
                topics.append({
                    "name": conn.topic,
                    "type": conn.msgtype,
                    "count": count,
                })
        return topics
    except Exception as exc:
        logger.warning("_get_bag_topics(%s): %s", bag_path, exc)
        return []


@router.post("/bags/upload")
async def upload_sitemap_bag(
    file: UploadFile = File(...),
    site_id: str = Form(""),
):
    """Upload a ROS bag (.bag/.db3) for the sitemap page.
    Extracts logs, topics, and auto-detected site.
    """
    bag_path, nbytes = _save_sitemap_bag(file)

    extractor = ROSLogExtractor(bag_path)
    try:
        logs = extractor.extract()
    except Exception as exc:
        logger.warning("Log extraction failed for %s: %s", bag_path, exc)
        logs = []

    duration_secs = 0.0
    if len(logs) >= 2:
        duration_secs = logs[-1]["timestamp"] - logs[0]["timestamp"]

    error_count = sum(1 for l in logs if l.get("log_level") in ("ERROR", "FATAL"))
    warning_count = sum(1 for l in logs if l.get("log_level") == "WARN")

    detected_site = _detect_site(logs)
    topics = _get_bag_topics(bag_path)

    return {
        "bag_path": bag_path,
        "filename": file.filename,
        "size_mb": round(nbytes / (1024 * 1024), 2),
        "site_id": site_id,
        "detected_site": detected_site,
        "site_mismatch": bool(detected_site and site_id and detected_site != site_id),
        "duration_secs": round(duration_secs, 3),
        "total_messages": len(logs),
        "topics": topics,
        "topics_count": len(topics),
        "error_count": error_count,
        "warning_count": warning_count,
    }


@router.get("/bags/topics/messages")
def get_topic_messages(
    bag_path: str = Query(...),
    topic: str = Query(...),
    from_ts: Optional[float] = Query(None),
    to_ts: Optional[float] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    """Return the last N messages from a specific topic."""
    if not os.path.exists(bag_path):
        raise HTTPException(404, f"Bag not found: {bag_path}")

    try:
        from rosbags.highlevel import AnyReader
        from pathlib import Path as P
        messages = []
        with AnyReader([P(bag_path)]) as reader:
            connections = [c for c in reader.connections if c.topic == topic]
            if not connections:
                raise HTTPException(404, f"Topic '{topic}' not found in bag")
            for conn, timestamp_ns, rawdata in reader.messages(connections):
                ts = timestamp_ns / 1_000_000_000.0
                if from_ts is not None and ts < from_ts:
                    continue
                if to_ts is not None and ts > to_ts:
                    continue
                msg = reader.deserialize(rawdata, conn.msgtype)
                messages.append({
                    "timestamp": ts,
                    "type": conn.msgtype,
                    "data": str(msg)[:2000],
                })
                if len(messages) >= limit:
                    break
        return {"topic": topic, "messages": messages, "count": len(messages)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_topic_messages(%s, %s): %s", bag_path, topic, exc)
        raise HTTPException(422, f"Could not read topic messages: {exc}")


@router.get("/bags/logs")
def get_bag_logs(
    bag_path: str = Query(...),
    level: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    from_ts: Optional[float] = Query(None),
    to_ts: Optional[float] = Query(None),
    limit: int = Query(2000, ge=1, le=10000),
):
    """Return log entries from a bag, with optional filters."""
    if not os.path.exists(bag_path):
        raise HTTPException(404, f"Bag not found: {bag_path}")

    extractor = ROSLogExtractor(bag_path)
    try:
        logs = extractor.extract()
    except Exception as exc:
        raise HTTPException(422, f"Could not read bag: {exc}")

    if from_ts is not None:
        logs = [l for l in logs if l["timestamp"] >= from_ts]
    if to_ts is not None:
        logs = [l for l in logs if l["timestamp"] <= to_ts]
    if level:
        levels = {lv.strip().upper() for lv in level.split(",")}
        logs = [l for l in logs if l.get("log_level", "") in levels]
    if search:
        search_lower = search.lower()
        logs = [l for l in logs if search_lower in l.get("message", "").lower()
                or search_lower in l.get("node_name", "").lower()]

    return {
        "logs": [
            {
                "timestamp": l["timestamp"],
                "datetime": l.get("datetime", ""),
                "level": l.get("log_level", "INFO"),
                "node": l.get("node_name", ""),
                "message": l.get("message", ""),
            }
            for l in logs[:limit]
        ],
        "total": len(logs),
    }


@router.get("/bags/list")
def list_bags():
    """Return all uploaded bag files."""
    upload_dir = pathlib.Path(settings.bag_upload_dir)
    if not upload_dir.exists():
        return []
    result = []
    for p in sorted(upload_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in ALLOWED_BAG_EXTENSIONS:
            stat = p.stat()
            result.append({
                "filename": p.name,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "upload_time": stat.st_mtime,
            })
    return result


@router.delete("/bags/{filename}")
def delete_bag(filename: str):
    """Delete a bag file from the upload directory."""
    safe = pathlib.PurePosixPath(filename).name
    if safe != filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    upload_dir = pathlib.Path(settings.bag_upload_dir)
    target = upload_dir / safe
    if not target.exists():
        raise HTTPException(404, f"Bag not found: {filename}")
    target.unlink()
    logger.info("Deleted bag: %s", target)
    return {"deleted": filename}

