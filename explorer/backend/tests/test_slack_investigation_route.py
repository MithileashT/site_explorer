"""API tests for Slack investigation endpoint behavior."""

import json
import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.main import app
from app.routes import slack_investigation
from schemas.slack_investigation import SlackLLMStatusResponse
from schemas.slack_investigation import SlackThreadInvestigationResponse

client = TestClient(app)


class _StubService:
    def investigate(self, _req):
        return SlackThreadInvestigationResponse(
            workspace="example",
            channel_id="C123ABC45",
            thread_ts="1772691175.223000",
            message_count=2,
            participants=["alice", "bob"],
            thread_summary="Thread indicates repeated mission stop due to map mismatch.",
            key_findings=["Mission stop command repeated", "Localization drift discussed"],
            recommended_actions=["Run map alignment checks", "Validate AMCL params"],
            risk_level="high",
            timeline=[],
            raw_analysis="ok",
        )

    def investigate_streaming(self, _req):
        yield ("chunk", "## ISSUE SUMMARY\nRobot stopped")
        yield ("result", SlackThreadInvestigationResponse(
            workspace="example",
            channel_id="C123ABC45",
            thread_ts="1772691175.223000",
            message_count=2,
            participants=["alice", "bob"],
            thread_summary="Thread indicates repeated mission stop due to map mismatch.",
            key_findings=["Mission stop command repeated"],
            recommended_actions=["Run map alignment checks"],
            risk_level="high",
            timeline=[],
            raw_analysis="## ISSUE SUMMARY\nRobot stopped",
        ))


class _FailingService:
    def investigate(self, _req):
        raise RuntimeError("SLACK_BOT_TOKEN is not configured on the backend.")


class _StatusService:
    def llm_status(self):
        return SlackLLMStatusResponse(
            status="online",
            text_model="qwen2.5:7b",
            text_ready=True,
            installed=["llama3.1:8b", "qwen2.5:7b"],
        )


def test_slack_investigation_endpoint_success(monkeypatch) -> None:
    monkeypatch.setattr(slack_investigation, "_service", _StubService())
    response = client.post(
        "/api/v1/slack/investigate",
        json={
            "slack_thread_url": "https://example.slack.com/archives/C123ABC45/p1772691175223000",
            "description": "Robot stopped near dock with repeated fault updates.",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["risk_level"] == "high"
    assert body["message_count"] == 2


def test_slack_investigation_endpoint_handles_runtime_error(monkeypatch) -> None:
    monkeypatch.setattr(slack_investigation, "_service", _FailingService())
    response = client.post(
        "/api/v1/slack/investigate",
        json={
            "slack_thread_url": "https://example.slack.com/archives/C123ABC45/p1772691175223000",
            "description": "Thread check",
        },
    )
    assert response.status_code == 503
    assert "SLACK_BOT_TOKEN" in response.json()["detail"]


def test_slack_status_endpoint_success(monkeypatch) -> None:
    monkeypatch.setattr(slack_investigation, "_service", _StatusService())
    response = client.get("/api/v1/slack/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "online"
    assert body["text_ready"] is True


def test_slack_stream_endpoint_yields_chunk_result_done(monkeypatch) -> None:
    """The streaming endpoint should yield chunk, result, and done SSE events."""
    monkeypatch.setattr(slack_investigation, "_service", _StubService())
    response = client.post(
        "/api/v1/slack/investigate/stream",
        json={
            "slack_thread_url": "https://example.slack.com/archives/C123ABC45/p1772691175223000",
            "description": "Test streaming endpoint.",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = []
    for line in response.text.strip().split("\n"):
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))

    event_types = [e["type"] for e in events]
    assert "chunk" in event_types, "Should have at least one chunk event"
    assert "result" in event_types, "Should have a result event"
    assert event_types[-1] == "done", "Last event should be done"

    # Verify the result event contains structured data
    result_event = next(e for e in events if e["type"] == "result")
    assert result_event["data"]["message_count"] == 2
    assert result_event["data"]["risk_level"] == "high"
