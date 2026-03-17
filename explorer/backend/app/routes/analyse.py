"""Route for the combined Log + Slack AI analysis endpoint."""
from __future__ import annotations

import time
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, List

from fastapi import APIRouter, HTTPException

from core.logging import get_logger
from schemas.analyse import AnalyseRequest, AnalyseResponse
from services.ai.llm_service import TokenLimitError

logger = get_logger(__name__)
router = APIRouter()

_llm_service = None
_slack_service = None


def register_singletons(llm_service, slack_service) -> None:
    global _llm_service, _slack_service
    _llm_service = llm_service
    _slack_service = slack_service


# ── Helper functions for log processing ─────────────────────────────────────


def _format_ts_ms(ts_ms: int) -> str:
    """Convert epoch milliseconds to human-readable ISO-like timestamp."""
    try:
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{ts_ms % 1000:03d}"
    except (ValueError, OSError, OverflowError):
        return str(ts_ms)


def _deduplicate_logs(entries: List[Dict[str, str]]) -> List[str]:
    """Deduplicate log entries, grouping identical messages with counts.

    Each entry dict has keys: ts_ms, level, host, dep, msg.
    Returns formatted log line strings with counts for duplicates.
    """
    # Group by (level, host, dep, message_normalized)
    groups: Dict[tuple, dict] = {}
    ordered_keys: list = []

    for e in entries:
        # Normalize: strip leading level tags like [ERROR] from message
        msg = e["msg"].strip()
        key = (e["level"].upper(), e["host"], e["dep"], msg)

        if key not in groups:
            groups[key] = {
                "first_ts": e["ts_ms"],
                "last_ts": e["ts_ms"],
                "count": 1,
                "level": e["level"],
                "host": e["host"],
                "dep": e["dep"],
                "msg": msg,
            }
            ordered_keys.append(key)
        else:
            groups[key]["count"] += 1
            groups[key]["last_ts"] = e["ts_ms"]

    result: List[str] = []
    for key in ordered_keys:
        g = groups[key]
        ts = _format_ts_ms(g["first_ts"])
        prefix = f"[{ts}] [{g['level']}] [{g['host']}/{g['dep']}]"
        if g["count"] > 1:
            last_ts = _format_ts_ms(g["last_ts"])
            result.append(f"{prefix} (×{g['count']}, {ts}→{last_ts}) {g['msg']}")
        else:
            result.append(f"{prefix} {g['msg']}")

    return result


def _filter_logs_by_time_range(
    entries: List[Dict],
    from_ms: int | None,
    to_ms: int | None,
) -> List[Dict]:
    """Filter log entries to only those within [from_ms, to_ms]."""
    if from_ms is None and to_ms is None:
        return entries
    result = []
    for e in entries:
        ts = e["ts_ms"]
        if from_ms is not None and ts < from_ms:
            continue
        if to_ms is not None and ts > to_ms:
            continue
        result.append(e)
    return result


def _cap_lines_for_token_budget(lines: List[str], max_chars: int = 18000) -> List[str]:
    """Cap deduplicated log lines to stay within a character budget.

    Prioritises keeping lines in order; stops adding once the budget is hit.
    """
    kept: List[str] = []
    total = 0
    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        if total + line_len > max_chars:
            break
        kept.append(line)
        total += line_len
    return kept


# ── Token estimation & chunking ─────────────────────────────────────────────

_CHARS_PER_TOKEN = 4  # Conservative estimate for English text
_MAX_PROMPT_TOKENS = 10000  # Conservative budget to stay well within 30K TPM
_MAX_RETRIES = 3  # Maximum 429 retry attempts


def _estimate_tokens(text: str) -> int:
    """Rough token count estimate (~4 chars per token for English text)."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _chunk_log_lines(lines: List[str], max_chars_per_chunk: int) -> List[List[str]]:
    """Split log lines into chunks, each within the character budget."""
    if not lines:
        return [[]]
    chunks: List[List[str]] = []
    current: List[str] = []
    current_size = 0
    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        if current_size + line_len > max_chars_per_chunk and current:
            chunks.append(current)
            current = []
            current_size = 0
        current.append(line)
        current_size += line_len
    if current:
        chunks.append(current)
    return chunks if chunks else [[]]


def _merge_chunk_summaries(
    summaries: List[str], analysed_entries: int, total_raw: int
) -> str:
    """Merge summaries from chunked analysis into a single output."""
    n = len(summaries)
    if n == 0:
        return "No analysis could be performed — logs exceeded token limits."
    if n == 1:
        return (
            f"> **Partial analysis:** Due to log volume, analysis was performed on a "
            f"subset of {analysed_entries} of {total_raw} total log entries.\n\n"
            + summaries[0]
        )
    parts = [
        f"> **Chunked analysis:** Logs were too large for a single pass. "
        f"Analysis was split into {n} segments covering "
        f"{analysed_entries} of {total_raw} total entries.\n"
    ]
    for i, s in enumerate(summaries, 1):
        parts.append(f"\n---\n### Segment {i} of {n}\n\n{s}")
    return "\n".join(parts)


def _build_log_stats(entries: List[Dict[str, str]]) -> str:
    """Build a concise statistical summary of log entries for the LLM."""
    if not entries:
        return ""

    level_counts = Counter(e["level"].upper() for e in entries)
    host_counts = Counter(e["host"] for e in entries if e["host"])
    msg_counts = Counter(e["msg"].strip() for e in entries)

    lines = ["LOG STATISTICS:"]
    lines.append(f"- Total entries: {len(entries)}")

    level_parts = []
    for lvl in ("ERROR", "FATAL", "WARN", "WARNING", "INFO", "DEBUG"):
        if lvl in level_counts:
            level_parts.append(f"{lvl}: {level_counts[lvl]}")
    if level_parts:
        lines.append(f"- By level: {', '.join(level_parts)}")

    if host_counts:
        top_hosts = host_counts.most_common(5)
        lines.append(f"- Hosts: {', '.join(f'{h} ({c})' for h, c in top_hosts)}")

    # Top error/warning patterns
    error_msgs = Counter()
    for e in entries:
        if e["level"].upper() in ("ERROR", "FATAL", "WARN", "WARNING"):
            # Take just the first 80 chars for pattern grouping
            error_msgs[e["msg"].strip()[:80]] += 1
    if error_msgs:
        lines.append("- Top error/warning patterns:")
        for msg, count in error_msgs.most_common(5):
            lines.append(f"  • \"{msg}\" ({count}x)")

    return "\n".join(lines)


@router.post(
    "/api/v1/investigate/analyse",
    tags=["investigation"],
    response_model=AnalyseResponse,
)
def analyse_logs_and_slack(req: AnalyseRequest) -> AnalyseResponse:
    """Combined AI analysis of Grafana logs + optional Slack thread."""
    if _llm_service is None:
        raise HTTPException(503, "LLM service not available.")

    from services.ai.slack_investigation_service import (
        SlackInvestigationService,
        parse_slack_thread_url,
    )
    from core.config import settings
    import requests as http_requests

    MAX_IMAGES = 4
    ollama_host = settings.ollama_host.rstrip("/")
    text_model = settings.ollama_text_model
    vision_model = settings.ollama_vision_model

    # ── Fetch Slack thread if URL provided ──────────────────────────────────
    slack_text = ""
    slack_images: list[str] = []
    slack_msg_count = 0

    if req.slack_thread_url and _slack_service:
        try:
            from schemas.slack_investigation import SlackThreadInvestigationRequest

            ref = parse_slack_thread_url(req.slack_thread_url)
            messages, attachments = _slack_service._fetch_thread_messages(
                ref, include_bots=False, max_messages=200
            )
            slack_msg_count = len(messages)

            thread_lines: list[str] = []
            for msg in messages:
                line = f"[{msg.datetime}] {msg.user}: {msg.text}"
                for idx, block in enumerate(msg.log_blocks, 1):
                    line += f"\n  [Log block {idx}]\n{block[:2000]}"
                thread_lines.append(line)
            slack_text = "\n\n".join(thread_lines)

            for att in attachments:
                if att.filetype == "image" and att.b64_image:
                    slack_images.append(att.b64_image)

        except (ValueError, RuntimeError) as exc:
            logger.warning("Slack fetch skipped: %s", exc)
            slack_text = f"[Slack thread could not be fetched: {exc}]"
        except Exception as exc:
            logger.error("Slack fetch failed: %s", exc, exc_info=True)
            slack_text = f"[Slack thread error: {exc}]"

    # ── Build log summary ───────────────────────────────────────────────────
    raw_entries: list[dict] = []
    for entry in req.logs[:2000]:
        lvl = entry.level or entry.labels.get("detected_level", "")
        dep = entry.deployment or entry.labels.get("deployment_name", "")
        host = entry.hostname or entry.labels.get("hostname", "")
        raw_entries.append({
            "ts_ms": entry.timestamp_ms,
            "level": lvl,
            "host": host,
            "dep": dep,
            "msg": entry.message[:500],
        })

    # ── Apply analysis time-range filter ─────────────────────────────────────
    filtered_entries = _filter_logs_by_time_range(
        raw_entries, req.analysis_from_ms, req.analysis_to_ms
    )

    # Generate statistics before dedup for accurate counts
    log_stats = _build_log_stats(filtered_entries)
    # Deduplicate for the LLM prompt
    log_lines = _deduplicate_logs(filtered_entries)
    # Cap to stay within token budget (~18K chars ≈ ~5K tokens)
    log_lines = _cap_lines_for_token_budget(log_lines, max_chars=18000)

    # ── Model selection ─────────────────────────────────────────────────────
    has_images = len(slack_images) > 0

    # Determine the active provider from LLMService
    active_provider = _llm_service.active_provider if hasattr(_llm_service, "active_provider") else {}
    using_openai = active_provider.get("type") == "openai"

    if using_openai:
        # OpenAI: use the active model; images handled via OpenAI's vision API
        model = f"openai:{active_provider.get('model', settings.openai_model)}"
        model_display = active_provider.get("model", settings.openai_model)
    else:
        # Ollama: existing model selection logic
        def _installed_models() -> list[str]:
            try:
                resp = http_requests.get(f"{ollama_host}/api/tags", timeout=5)
                resp.raise_for_status()
                return [m.get("name", "") for m in resp.json().get("models", [])]
            except Exception:
                return []

        installed = _installed_models()

        if has_images:
            vp = vision_model.split(":", 1)[0]
            if any(vp in n for n in installed):
                model = vision_model
            else:
                model = text_model
                has_images = False
        else:
            model = text_model

        tp = model.split(":", 1)[0]
        if not any(tp in n for n in installed):
            raise HTTPException(503, f"Model '{model}' not installed. Pull it with: ollama pull {model}")
        model_display = model

    # ── Build prompt ────────────────────────────────────────────────────────
    # If no Slack data, use log-only analysis sections
    has_slack_data = bool(slack_text and slack_text.strip() and not slack_text.startswith("[Slack"))

    analysis_guidance = (
        "ANALYSIS APPROACH:\n"
        "1. First review the LOG STATISTICS to understand error distribution and patterns.\n"
        "2. Identify the most significant errors — frequency and severity indicate importance.\n"
        "3. Look for temporal patterns: did errors start at a specific time? Do they repeat?\n"
        "4. Check for cascading failures: did one error trigger others?\n"
        "5. Note which hosts/deployments are most affected.\n"
        "6. Quote exact error messages as evidence (without timestamps).\n\n"
    )

    if has_slack_data:
        system = (
            "You are a senior SRE producing a structured incident summary for a warehouse robotics team.\n"
            "Analyse the operational logs AND the Slack incident thread with respect to the ISSUE DESCRIPTION provided.\n\n"
            "STRICT RULES:\n"
            "- Do NOT include any Slack timestamps or dates from the thread.\n"
            "- Do NOT include any URLs, rosbag links, or file paths.\n"
            "- Do NOT copy sentences directly; fully rephrase everything.\n"
            "- Do NOT mention user names or Slack handles; write impersonally.\n"
            "- Do NOT write long paragraphs; use ONLY concise bullet points (- item).\n"
            "- Focus every bullet on meaningful technical insight tied to the issue.\n"
            "- You MAY quote exact log lines (without timestamps) as evidence.\n"
            "- For repeated errors shown as (×N), explain the pattern and its significance.\n\n"
            + analysis_guidance
            + "Use EXACTLY these five markdown sections:\n\n"
            "## Issue Overview\n"
            "- (concise bullets describing the incident in context of the issue description)\n\n"
            "## Key Observations\n"
            "- (specific technical findings from logs AND Slack, quoting error messages)\n"
            "- (note error frequencies and patterns from the statistics)\n\n"
            "## Root Cause Analysis\n"
            "- (contributing factors identified or suspected)\n"
            "- (state uncertainty explicitly: 'Likely…', 'Unconfirmed…')\n"
            "- (explain the chain of events if a cascading failure is detected)\n\n"
            "## Actions Taken / Suggested Fixes\n"
            "- (actions performed or proposed during the incident)\n\n"
            "## Current Status / Risks\n"
            "- (resolution state and remaining risks)\n"
        )
    else:
        system = (
            "You are a senior SRE producing a structured log analysis for a warehouse robotics team.\n"
            "Analyse the operational logs with respect to the ISSUE DESCRIPTION provided.\n\n"
            "STRICT RULES:\n"
            "- Do NOT include any URLs or file paths.\n"
            "- Do NOT write long paragraphs; use ONLY concise bullet points (- item).\n"
            "- Focus every bullet on meaningful technical insight tied to the issue.\n"
            "- You MAY quote exact log lines as evidence.\n"
            "- For repeated errors shown as (×N), explain the pattern and its significance.\n\n"
            + analysis_guidance
            + "Use EXACTLY these five markdown sections:\n\n"
            "## Issue Overview\n"
            "- (concise bullets describing the incident)\n\n"
            "## Key Observations\n"
            "- (specific error messages, patterns, anomalies from logs)\n"
            "- (note error frequencies and which hosts/deployments are affected)\n\n"
            "## Root Cause Analysis\n"
            "- (contributing factors; state uncertainty explicitly)\n"
            "- (explain the chain of events if a cascading failure is detected)\n\n"
            "## Recommended Actions\n"
            "- (specific, actionable recommendations based on log evidence)\n"
            "- (prioritize by severity: critical fixes first)\n\n"
            "## Current Status / Risks\n"
            "- (current state assessment and remaining risks)\n"
        )

    user_content = f"ISSUE DESCRIPTION:\n{req.issue_description}\n\n"

    if req.site_id:
        user_content += f"SITE: {req.site_id}\n"
    if req.env:
        user_content += f"ENVIRONMENT: {req.env}\n"
    if req.hostname:
        user_content += f"HOSTNAME: {req.hostname}\n"
    if req.deployment:
        user_content += f"DEPLOYMENT: {req.deployment}\n"
    if req.time_from or req.time_to:
        user_content += f"TIME RANGE: {req.time_from or '?'} → {req.time_to or '?'}\n\n"

    # Include statistics summary first so LLM understands the data shape
    if log_stats:
        user_content += log_stats + "\n\n"

    # ── Reusable parts for building the user prompt ─────────────────────────
    user_meta = user_content  # metadata prefix (without logs/slack)

    slack_section = ""
    if slack_text:
        slack_section += f"SLACK THREAD ({slack_msg_count} messages)\n"
        slack_section += "-" * 60 + "\n"
        slack_section += slack_text[:8000]
        slack_section += "\n"

    filter_note = ""
    if req.analysis_from_ms or req.analysis_to_ms:
        f_str = _format_ts_ms(req.analysis_from_ms) if req.analysis_from_ms else "start"
        t_str = _format_ts_ms(req.analysis_to_ms) if req.analysis_to_ms else "end"
        filter_note = f" (filtered to {f_str} → {t_str})"

    def assemble_user_content(lines_to_use: List[str]) -> str:
        """Build the full user content with the given log lines."""
        content = user_meta
        if lines_to_use:
            content += (
                f"DEDUPLICATED LOGS ({len(lines_to_use)} unique entries "
                f"from {len(filtered_entries)} filtered / "
                f"{len(raw_entries)} total){filter_note}\n"
            )
            content += "-" * 60 + "\n"
            content += "\n".join(lines_to_use)
            content += "\n\n"
        content += slack_section
        if not lines_to_use and not slack_text:
            content += "[No logs or Slack data provided — analyse based on the issue description only.]\n"
        return content

    # ── Pre-emptive token budget check ──────────────────────────────────────
    max_tok = 2000
    current_lines = list(log_lines)
    user_content = assemble_user_content(current_lines)
    est_tokens = _estimate_tokens(system + user_content) + max_tok
    partial = False

    logger.info(
        "Token estimate: ~%d tokens (prompt) + %d (max output) = ~%d total | "
        "logs: %d raw → %d filtered → %d deduped | budget: %d",
        est_tokens - max_tok, max_tok, est_tokens,
        len(raw_entries), len(filtered_entries), len(log_lines),
        _MAX_PROMPT_TOKENS,
    )

    if est_tokens > _MAX_PROMPT_TOKENS:
        # Calculate how many chars logs can use
        overhead_chars = len(system) + len(user_meta) + len(slack_section)
        avail_chars = max(
            2000,
            _MAX_PROMPT_TOKENS * _CHARS_PER_TOKEN - overhead_chars - max_tok * _CHARS_PER_TOKEN,
        )
        current_lines = _cap_lines_for_token_budget(log_lines, max_chars=avail_chars)
        if len(current_lines) < len(log_lines):
            partial = True
        user_content = assemble_user_content(current_lines)
        logger.info(
            "Token budget: est=%d > max=%d, capped logs from %d to %d lines",
            est_tokens, _MAX_PROMPT_TOKENS, len(log_lines), len(current_lines),
        )

    # ── Call LLM with retry on token-limit errors ───────────────────────────
    def build_chat_messages(content: str) -> list[dict]:
        msgs: list[dict] = [{"role": "system", "content": system}]
        umsg: dict = {"role": "user", "content": content}
        if has_images:
            umsg["images"] = slack_images[:MAX_IMAGES]
        msgs.append(umsg)
        return msgs

    summary = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            chat_messages = build_chat_messages(user_content)
            summary = _llm_service.chat(
                messages=chat_messages,
                max_tokens=max_tok,
                temperature=0.2,
                model_override=model if using_openai else None,
                module="log_analyser",
            )
            break
        except TokenLimitError:
            if attempt >= _MAX_RETRIES:
                logger.error("Token limit exceeded after %d retries", _MAX_RETRIES)
                raise HTTPException(
                    500,
                    "Log volume exceeds AI model token limits even after reduction. "
                    "Try selecting a shorter time range or fewer lines.",
                )
            # Halve the log lines and retry
            current_lines = current_lines[: max(1, len(current_lines) // 2)]
            partial = True
            user_content = assemble_user_content(current_lines)
            est_tokens = _estimate_tokens(system + user_content) + max_tok
            logger.warning(
                "Token limit hit (attempt %d/%d), retrying with %d log lines (~%d tokens)",
                attempt + 1, _MAX_RETRIES, len(current_lines), est_tokens,
            )
        except Exception as exc:
            logger.error("LLM analysis failed: %s", exc, exc_info=True)
            raise HTTPException(500, f"LLM analysis failed: {exc}")

    # ── Prepend partial-analysis notice if logs were reduced ────────────────
    if partial and summary:
        summary = _merge_chunk_summaries(
            [summary], len(current_lines), len(log_lines)
        )

    actual = getattr(_llm_service, "last_usage", {})
    return AnalyseResponse(
        model_used=model_display,
        has_images=has_images,
        slack_messages=slack_msg_count,
        log_count=len(req.logs),
        summary=summary or "Analysis could not be completed.",
        partial_analysis=partial,
        chunks_analysed=1,
        estimated_tokens=est_tokens,
        actual_prompt_tokens     = actual.get("prompt_tokens", 0),
        actual_completion_tokens = actual.get("completion_tokens", 0),
        actual_total_tokens      = actual.get("total_tokens", 0),
        cost_usd                 = actual.get("cost_usd", 0.0),
    )
