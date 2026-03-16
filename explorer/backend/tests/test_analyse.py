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
