"""Tests for POST /api/v1/investigate/analyse."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch

from schemas.analyse import AnalyseRequest, LogEntry


def test_analyse_request_validates_description() -> None:
    with pytest.raises(Exception):
        AnalyseRequest(issue_description="abc")  # < 5 chars


def test_analyse_request_accepts_valid_payload() -> None:
    req = AnalyseRequest(
        logs=[
            LogEntry(timestamp_ms=1000000, level="ERROR", message="segfault"),
        ],
        issue_description="Robot stopped unexpectedly during mission",
        site_id="actsgm001",
    )
    assert len(req.logs) == 1
    assert req.logs[0].level == "ERROR"


def test_analyse_response_schema() -> None:
    from schemas.analyse import AnalyseResponse

    resp = AnalyseResponse(
        model_used="qwen2.5:7b",
        has_images=False,
        slack_messages=0,
        log_count=42,
        summary="## What Happened\nRobot stopped.",
    )
    assert resp.model_used == "qwen2.5:7b"
    assert resp.log_count == 42
    assert "What Happened" in resp.summary


# ── Config coverage ────────────────────────────────────────────────────────


def test_config_has_ollama_vision_model() -> None:
    """settings.ollama_vision_model must exist so analyse route doesn't crash."""
    from core.config import settings

    assert hasattr(settings, "ollama_vision_model"), (
        "ollama_vision_model missing from _Settings — "
        "analyse route will crash with AttributeError"
    )
    assert isinstance(settings.ollama_vision_model, str)


def test_cors_allows_localhost_port_80() -> None:
    """CORS must allow http://localhost (nginx on port 80) to avoid Network Error."""
    from core.config import settings

    assert "http://localhost" in settings.allowed_origins, (
        "http://localhost not in allowed_origins — browser requests from "
        "nginx (port 80) will be blocked by CORS and show Network Error"
    )


# ── Route integration ─────────────────────────────────────────────────────


@pytest.fixture()
def analyse_client():
    """TestClient with mocked LLM + Slack singletons."""
    from app.main import app
    from app.routes import analyse as analyse_route

    mock_llm = MagicMock()
    mock_llm.active_provider = {"id": "openai:gpt-4.1", "model": "gpt-4.1", "type": "openai"}
    mock_llm.chat.return_value = "## What Happened\nTest summary."
    mock_slack = MagicMock()
    analyse_route._llm_service = mock_llm
    analyse_route._slack_service = mock_slack
    from fastapi.testclient import TestClient

    yield TestClient(app), mock_llm, mock_slack
    analyse_route._llm_service = None
    analyse_route._slack_service = None


def test_analyse_endpoint_does_not_crash_on_missing_vision_model(analyse_client):
    """Endpoint must not raise AttributeError for missing config attr."""
    tc, mock_llm, _ = analyse_client

    # Mock Ollama HTTP calls so we don't need a running instance
    mock_tags_resp = MagicMock()
    mock_tags_resp.status_code = 200
    mock_tags_resp.json.return_value = {
        "models": [{"name": "qwen2.5:7b"}]
    }
    mock_tags_resp.raise_for_status = MagicMock()

    mock_chat_resp = MagicMock()
    mock_chat_resp.status_code = 200
    mock_chat_resp.json.return_value = {
        "message": {"content": "## What Happened\nTest summary."}
    }
    mock_chat_resp.raise_for_status = MagicMock()

    import requests as _real_requests
    with patch("requests.get", return_value=mock_tags_resp), \
         patch("requests.post", return_value=mock_chat_resp):

        resp = tc.post(
            "/api/v1/investigate/analyse",
            json={
                "logs": [
                    {
                        "timestamp_ms": 1710381676806,
                        "level": "ERROR",
                        "hostname": "edge01",
                        "deployment": "gbc",
                        "message": "[ERROR] segfault in route_manager",
                        "labels": {},
                    }
                ],
                "issue_description": "Robot stopped moving during mission",
            },
        )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "summary" in body
    assert body["log_count"] == 1


# ── Log deduplication and formatting tests ──────────────────────────────


def test_deduplicate_logs_groups_identical_messages() -> None:
    """Duplicate log messages should be grouped with a count."""
    from app.routes.analyse import _deduplicate_logs

    entries = [
        {"ts_ms": 1000, "level": "ERROR", "host": "edge01", "dep": "gbc", "msg": "segfault in route_manager"},
        {"ts_ms": 2000, "level": "ERROR", "host": "edge01", "dep": "gbc", "msg": "segfault in route_manager"},
        {"ts_ms": 3000, "level": "ERROR", "host": "edge01", "dep": "gbc", "msg": "segfault in route_manager"},
        {"ts_ms": 4000, "level": "WARN", "host": "edge01", "dep": "gbc", "msg": "connection timeout"},
    ]
    result = _deduplicate_logs(entries)
    # The 3 identical errors should be grouped into 1 entry with count
    assert len(result) < len(entries), "Dedup should reduce the number of entries"
    # The grouped entry should mention the count
    grouped = [r for r in result if "segfault" in r]
    assert len(grouped) == 1
    assert "3x" in grouped[0] or "×3" in grouped[0] or "(3)" in grouped[0]


def test_deduplicate_logs_preserves_unique_messages() -> None:
    """Unique messages should not be lost by deduplication."""
    from app.routes.analyse import _deduplicate_logs

    entries = [
        {"ts_ms": 1000, "level": "ERROR", "host": "edge01", "dep": "gbc", "msg": "error A"},
        {"ts_ms": 2000, "level": "WARN", "host": "edge01", "dep": "gbc", "msg": "warning B"},
        {"ts_ms": 3000, "level": "INFO", "host": "edge01", "dep": "gbc", "msg": "info C"},
    ]
    result = _deduplicate_logs(entries)
    assert len(result) == 3, "Unique messages should all be preserved"


def test_format_timestamp_human_readable() -> None:
    """Timestamps should be formatted as ISO-like strings, not raw epoch ms."""
    from app.routes.analyse import _format_ts_ms

    # 2024-03-14T10:30:00.000Z in epoch ms
    ts_ms = 1710412200000
    formatted = _format_ts_ms(ts_ms)
    assert "2024" in formatted, f"Expected ISO date in output, got: {formatted}"
    assert "10:30" in formatted, f"Expected time in output, got: {formatted}"


def test_build_log_statistics_summary() -> None:
    """A statistics summary should be generated from log entries."""
    from app.routes.analyse import _build_log_stats

    entries = [
        {"ts_ms": 1000, "level": "ERROR", "host": "edge01", "dep": "gbc", "msg": "segfault"},
        {"ts_ms": 2000, "level": "ERROR", "host": "edge01", "dep": "gbc", "msg": "segfault"},
        {"ts_ms": 3000, "level": "WARN", "host": "edge02", "dep": "nav", "msg": "timeout"},
        {"ts_ms": 4000, "level": "INFO", "host": "edge01", "dep": "gbc", "msg": "started"},
    ]
    stats = _build_log_stats(entries)
    assert "ERROR" in stats, "Stats should mention error count"
    assert "segfault" in stats, "Stats should mention top error pattern"


def test_analyse_endpoint_with_duplicate_logs(analyse_client):
    """Endpoint should handle duplicate logs efficiently."""
    tc, mock_llm, _ = analyse_client

    mock_tags_resp = MagicMock()
    mock_tags_resp.status_code = 200
    mock_tags_resp.json.return_value = {"models": [{"name": "qwen2.5:7b"}]}
    mock_tags_resp.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock_tags_resp):
        # Send 100 identical error logs
        logs = [
            {
                "timestamp_ms": 1710381676806 + i * 1000,
                "level": "ERROR",
                "hostname": "edge01",
                "deployment": "gbc",
                "message": "[ERROR] segfault in route_manager node_id=42",
                "labels": {},
            }
            for i in range(100)
        ]
        resp = tc.post(
            "/api/v1/investigate/analyse",
            json={
                "logs": logs,
                "issue_description": "Robot stopped moving during mission",
            },
        )

    assert resp.status_code == 200
    # Verify the LLM was called with deduplicated content
    call_args = mock_llm.chat.call_args
    prompt_content = call_args[1]["messages"][1]["content"] if "messages" in call_args[1] else call_args[0][0][1]["content"]
    # The prompt should NOT contain 100 separate identical lines
    assert prompt_content.count("segfault in route_manager") < 10, (
        "Duplicate logs should be deduplicated in the LLM prompt"
    )


# ── Time-range filtering tests ──────────────────────────────────────────


def test_time_range_filtering_filters_logs() -> None:
    """Logs outside the time range should be excluded before processing."""
    from app.routes.analyse import _filter_logs_by_time_range

    entries = [
        {"ts_ms": 1000, "level": "ERROR", "host": "h1", "dep": "d1", "msg": "early error"},
        {"ts_ms": 5000, "level": "ERROR", "host": "h1", "dep": "d1", "msg": "mid error"},
        {"ts_ms": 9000, "level": "WARN", "host": "h1", "dep": "d1", "msg": "late warning"},
    ]
    # Filter: only keep 4000-6000
    result = _filter_logs_by_time_range(entries, from_ms=4000, to_ms=6000)
    assert len(result) == 1
    assert result[0]["msg"] == "mid error"


def test_time_range_filtering_keeps_all_when_no_range() -> None:
    """When no time range is given, all logs should be preserved."""
    from app.routes.analyse import _filter_logs_by_time_range

    entries = [
        {"ts_ms": 1000, "level": "INFO", "host": "h1", "dep": "d1", "msg": "a"},
        {"ts_ms": 5000, "level": "INFO", "host": "h1", "dep": "d1", "msg": "b"},
    ]
    result = _filter_logs_by_time_range(entries, from_ms=None, to_ms=None)
    assert len(result) == 2


def test_time_range_filtering_handles_partial_range() -> None:
    """When only from or to is given, filter with the one provided."""
    from app.routes.analyse import _filter_logs_by_time_range

    entries = [
        {"ts_ms": 1000, "level": "INFO", "host": "h1", "dep": "d1", "msg": "a"},
        {"ts_ms": 5000, "level": "INFO", "host": "h1", "dep": "d1", "msg": "b"},
        {"ts_ms": 9000, "level": "INFO", "host": "h1", "dep": "d1", "msg": "c"},
    ]
    # Only from_ms
    result = _filter_logs_by_time_range(entries, from_ms=4000, to_ms=None)
    assert len(result) == 2
    assert result[0]["msg"] == "b"

    # Only to_ms
    result = _filter_logs_by_time_range(entries, from_ms=None, to_ms=6000)
    assert len(result) == 2
    assert result[-1]["msg"] == "b"


# ── Token budget cap tests ───────────────────────────────────────────────


def test_cap_log_lines_for_token_budget() -> None:
    """Log lines should be capped to stay within token budget."""
    from app.routes.analyse import _cap_lines_for_token_budget

    # Create 200 lines of ~200 chars each = ~40K chars
    lines = [f"[2024-01-01 00:00:00.000] [ERROR] [h1/d1] {'x' * 180}" for _ in range(200)]
    capped = _cap_lines_for_token_budget(lines, max_chars=10000)
    total_chars = sum(len(l) for l in capped)
    assert total_chars <= 10000, f"Capped lines should be within budget, got {total_chars}"
    assert len(capped) < 200, "Some lines should be dropped to stay within budget"


def test_cap_log_lines_preserves_all_when_under_budget() -> None:
    """When lines fit within budget, all should be preserved."""
    from app.routes.analyse import _cap_lines_for_token_budget

    lines = ["short line 1", "short line 2", "short line 3"]
    capped = _cap_lines_for_token_budget(lines, max_chars=10000)
    assert len(capped) == 3


def test_analyse_endpoint_time_range_filters_logs(analyse_client):
    """Endpoint should filter logs by analysis_from/analysis_to timestamps."""
    tc, mock_llm, _ = analyse_client

    mock_tags_resp = MagicMock()
    mock_tags_resp.status_code = 200
    mock_tags_resp.json.return_value = {"models": [{"name": "qwen2.5:7b"}]}
    mock_tags_resp.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock_tags_resp):
        logs = [
            {"timestamp_ms": 1000, "level": "ERROR", "hostname": "h1",
             "deployment": "d1", "message": "early error", "labels": {}},
            {"timestamp_ms": 5000, "level": "ERROR", "hostname": "h1",
             "deployment": "d1", "message": "target error", "labels": {}},
            {"timestamp_ms": 9000, "level": "WARN", "hostname": "h1",
             "deployment": "d1", "message": "late warning", "labels": {}},
        ]
        resp = tc.post(
            "/api/v1/investigate/analyse",
            json={
                "logs": logs,
                "issue_description": "Robot stopped during mission",
                "analysis_from_ms": 4000,
                "analysis_to_ms": 6000,
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    # The endpoint should report filtering was applied
    assert body["log_count"] == 3  # original count
    call_args = mock_llm.chat.call_args
    prompt_content = call_args[1]["messages"][1]["content"]
    assert "target error" in prompt_content
    assert "early error" not in prompt_content
    assert "late warning" not in prompt_content


# ── Token estimation tests ───────────────────────────────────────────────


def test_estimate_tokens_basic() -> None:
    """Token estimation should approximate 1 token per ~4 chars."""
    from app.routes.analyse import _estimate_tokens

    assert _estimate_tokens("") == 1  # minimum of 1
    assert _estimate_tokens("a" * 100) == 25
    assert _estimate_tokens("a" * 4000) == 1000


def test_estimate_tokens_returns_at_least_one() -> None:
    """Even empty strings should return at least 1."""
    from app.routes.analyse import _estimate_tokens

    assert _estimate_tokens("") >= 1
    assert _estimate_tokens("hi") >= 1


# ── Chunk log lines tests ───────────────────────────────────────────────


def test_chunk_log_lines_splits_correctly() -> None:
    """Log lines should be split into chunks within the character budget."""
    from app.routes.analyse import _chunk_log_lines

    # 10 lines of 100 chars each = 1000 chars total
    lines = [f"line {i}: {'x' * 90}" for i in range(10)]
    # Chunk at 300 chars → should produce ~4 chunks
    chunks = _chunk_log_lines(lines, max_chars_per_chunk=300)
    assert len(chunks) > 1, "Should produce multiple chunks"
    for chunk in chunks:
        chunk_size = sum(len(l) + 1 for l in chunk)
        # Each chunk should respect the budget
        assert chunk_size <= 300 + 200, f"Chunk too big: {chunk_size}"  # some tolerance for last line


def test_chunk_log_lines_single_chunk_when_fits() -> None:
    """When all lines fit in one chunk, returns a single list."""
    from app.routes.analyse import _chunk_log_lines

    lines = ["short a", "short b", "short c"]
    chunks = _chunk_log_lines(lines, max_chars_per_chunk=10000)
    assert len(chunks) == 1
    assert chunks[0] == lines


def test_chunk_log_lines_empty_input() -> None:
    """Empty input should return a list with one empty list."""
    from app.routes.analyse import _chunk_log_lines

    chunks = _chunk_log_lines([], max_chars_per_chunk=1000)
    assert len(chunks) == 1
    assert chunks[0] == []


# ── Merge chunk summaries tests ──────────────────────────────────────────


def test_merge_chunk_summaries_single() -> None:
    """Single-chunk merge should include partial analysis note."""
    from app.routes.analyse import _merge_chunk_summaries

    result = _merge_chunk_summaries(["## Findings\n- Error found"], 50, 200)
    assert "Partial analysis" in result or "partial" in result.lower()
    assert "Error found" in result


def test_merge_chunk_summaries_multiple() -> None:
    """Multi-chunk merge should label each segment."""
    from app.routes.analyse import _merge_chunk_summaries

    summaries = ["Chunk 1 findings", "Chunk 2 findings"]
    result = _merge_chunk_summaries(summaries, 100, 200)
    assert "Segment 1" in result
    assert "Segment 2" in result
    assert "Chunk 1 findings" in result
    assert "Chunk 2 findings" in result


def test_merge_chunk_summaries_empty() -> None:
    """Empty summaries should return informative fallback."""
    from app.routes.analyse import _merge_chunk_summaries

    result = _merge_chunk_summaries([], 0, 100)
    assert "could not be performed" in result.lower() or "no analysis" in result.lower()


# ── 429 retry / graceful degradation tests ───────────────────────────────


def test_token_limit_error_class_exists() -> None:
    """TokenLimitError should be importable from llm_service."""
    from services.ai.llm_service import TokenLimitError

    exc = TokenLimitError("test")
    assert isinstance(exc, RuntimeError)
    assert "test" in str(exc)


def test_analyse_endpoint_retries_on_429(analyse_client):
    """When the LLM returns a 429 error, the endpoint should retry with fewer logs."""
    tc, mock_llm, _ = analyse_client

    mock_tags_resp = MagicMock()
    mock_tags_resp.status_code = 200
    mock_tags_resp.json.return_value = {"models": [{"name": "qwen2.5:7b"}]}
    mock_tags_resp.raise_for_status = MagicMock()

    from services.ai.llm_service import TokenLimitError

    # First call raises 429, second succeeds
    mock_llm.chat.side_effect = [
        TokenLimitError("429: rate limit exceeded"),
        "## What Happened\nPartial analysis result.",
    ]

    with patch("requests.get", return_value=mock_tags_resp):
        logs = [
            {"timestamp_ms": 1000 + i, "level": "ERROR", "hostname": "h1",
             "deployment": "d1", "message": f"error msg {i}", "labels": {}}
            for i in range(100)
        ]
        resp = tc.post(
            "/api/v1/investigate/analyse",
            json={"logs": logs, "issue_description": "Robot stopped during mission"},
        )

    assert resp.status_code == 200, f"Expected 200 after retry, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["partial_analysis"] is True
    assert "Partial analysis" in body["summary"] or "partial" in body["summary"].lower()
    assert mock_llm.chat.call_count == 2


def test_analyse_endpoint_partial_analysis_schema(analyse_client):
    """Response should include partial_analysis and chunks_analysed fields."""
    tc, mock_llm, _ = analyse_client

    mock_tags_resp = MagicMock()
    mock_tags_resp.status_code = 200
    mock_tags_resp.json.return_value = {"models": [{"name": "qwen2.5:7b"}]}
    mock_tags_resp.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock_tags_resp):
        resp = tc.post(
            "/api/v1/investigate/analyse",
            json={
                "logs": [{"timestamp_ms": 1000, "level": "ERROR", "hostname": "h1",
                          "deployment": "d1", "message": "error", "labels": {}}],
                "issue_description": "Robot stopped during mission",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "partial_analysis" in body
    assert "chunks_analysed" in body
    assert body["partial_analysis"] is False
    assert body["chunks_analysed"] == 1


def test_analyse_endpoint_gives_error_after_exhausted_retries(analyse_client):
    """After max retries, endpoint should return 500 with helpful message."""
    tc, mock_llm, _ = analyse_client

    mock_tags_resp = MagicMock()
    mock_tags_resp.status_code = 200
    mock_tags_resp.json.return_value = {"models": [{"name": "qwen2.5:7b"}]}
    mock_tags_resp.raise_for_status = MagicMock()

    from services.ai.llm_service import TokenLimitError

    # All calls raise 429
    mock_llm.chat.side_effect = TokenLimitError("429: rate limit exceeded")

    with patch("requests.get", return_value=mock_tags_resp):
        logs = [
            {"timestamp_ms": 1000 + i, "level": "ERROR", "hostname": "h1",
             "deployment": "d1", "message": f"error msg {i}", "labels": {}}
            for i in range(50)
        ]
        resp = tc.post(
            "/api/v1/investigate/analyse",
            json={"logs": logs, "issue_description": "Robot stopped during mission"},
        )

    assert resp.status_code == 500
    assert "token limit" in resp.json()["detail"].lower() or "time range" in resp.json()["detail"].lower()


def test_analyse_response_schema_with_partial_fields() -> None:
    """AnalyseResponse should support partial_analysis and chunks_analysed."""
    from schemas.analyse import AnalyseResponse

    resp = AnalyseResponse(
        model_used="gpt-4.1",
        log_count=500,
        summary="Partial result",
        partial_analysis=True,
        chunks_analysed=2,
    )
    assert resp.partial_analysis is True
    assert resp.chunks_analysed == 2
