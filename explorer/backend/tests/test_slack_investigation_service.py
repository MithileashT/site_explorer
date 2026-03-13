"""Unit tests for Slack investigation parsing and model-selection helpers."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from schemas.slack_investigation import (
    SlackThreadAttachment,
    SlackThreadInvestigationRequest,
    SlackThreadMessage,
)
from services.ai.slack_investigation_service import (
    SlackInvestigationService,
    _extract_log_blocks,
    parse_slack_thread_url,
)


def test_parse_slack_thread_url_success() -> None:
    ref = parse_slack_thread_url("https://example.slack.com/archives/C123ABC45/p1772691175223000")
    assert ref.workspace == "example"
    assert ref.channel_id == "C123ABC45"
    assert ref.thread_ts == "1772691175.223000"


def test_parse_slack_thread_url_rejects_invalid_url() -> None:
    with pytest.raises(ValueError):
        parse_slack_thread_url("https://example.slack.com/archives/C123ABC45")


def test_extract_log_blocks_from_triple_and_inline() -> None:
    clean, blocks = _extract_log_blocks(
        "Issue observed.```ERROR stack trace line 1\nline 2```and `inline long log payload with more than forty chars`"
    )
    assert "[log block]" in clean
    assert "[log snippet]" in clean
    assert len(blocks) == 2
    assert "ERROR stack trace" in blocks[0]


def test_generate_summary_selects_vision_model_when_images_present(monkeypatch) -> None:
    svc = SlackInvestigationService()

    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Robot stopped near dock",
        max_messages=200,
    )
    messages = [
        SlackThreadMessage(
            ts="1772691175.223000",
            datetime="2026-03-13 10:00 UTC",
            user="alice",
            text="Robot fault observed",
        )
    ]
    attachments = [
        SlackThreadAttachment(
            filename="fault.png",
            filetype="image",
            extracted="[Image: fault.png]",
            b64_image="ZmFrZQ==",
        )
    ]

    monkeypatch.setattr(svc, "_ollama_chat", lambda _messages, _model: "## The Issue\nX")
    monkeypatch.setattr(svc, "_ollama_models", lambda: ["qwen2.5:7b", "llama3.2-vision:11b"])

    _summary, model, has_images = svc._generate_summary(req, messages, attachments)
    assert has_images is True
    assert model == svc.vision_model


def test_slack_headers_accepts_alias_token(monkeypatch) -> None:
    monkeypatch.setenv("SLACK_BOT_TOKEN", "")
    monkeypatch.setenv("SLACK_TOKEN", '"xoxb-alias-token"')

    svc = SlackInvestigationService()
    headers = svc._slack_headers()

    assert headers["Authorization"] == "Bearer xoxb-alias-token"
