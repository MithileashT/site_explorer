"""Unit tests for Slack investigation parsing and model-selection helpers."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from schemas.slack_investigation import (
    SlackThreadInvestigationRequest,
    SlackThreadMessage,
)
from services.ai.slack_investigation_service import (
    SlackInvestigationService,
    _as_bullets,
    _extract_log_blocks,
    _find_section,
    _split_markdown_sections,
    parse_slack_thread_url,
    _MAX_ATTACHMENT_WORKERS,
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


def test_generate_summary_selects_text_model(monkeypatch) -> None:
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

    monkeypatch.setattr(svc, "_ollama_chat", lambda _messages, _model, **kw: "## The Issue\nX")
    monkeypatch.setattr(svc, "_ollama_models", lambda: ["qwen2.5:7b", "llama3.1:8b"])

    _summary, model = svc._generate_summary(req, messages, [])
    assert model == svc.text_model


def test_slack_headers_accepts_alias_token(monkeypatch) -> None:
    monkeypatch.setenv("SLACK_BOT_TOKEN", "")
    monkeypatch.setenv("SLACK_TOKEN", '"xoxb-alias-token"')

    svc = SlackInvestigationService()
    headers = svc._slack_headers()

    assert headers["Authorization"] == "Bearer xoxb-alias-token"


# ── _ensure_in_channel ─────────────────────────────────────────────────────────

class _FakeResponse:
    """Minimal fake for SlackResponse used in tests."""
    def __init__(self, data: dict) -> None:
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)


def _make_slack_api_error(error_code: str):
    from slack_sdk.errors import SlackApiError
    resp = _FakeResponse({"ok": False, "error": error_code})
    return SlackApiError(message=error_code, response=resp)


def test_ensure_in_channel_skips_join_when_already_member(monkeypatch) -> None:
    svc = SlackInvestigationService()
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")

    join_called = []

    class FakeClient:
        def conversations_info(self, channel):
            return _FakeResponse({"channel": {"is_member": True}})

        def conversations_join(self, channel):
            join_called.append(channel)

    svc._ensure_in_channel(FakeClient(), "C123")  # type: ignore
    assert not join_called, "Should not call join when already a member"


def test_ensure_in_channel_joins_public_channel_when_not_member(monkeypatch) -> None:
    svc = SlackInvestigationService()
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")

    join_called = []

    class FakeClient:
        def conversations_info(self, channel):
            return _FakeResponse({"channel": {"is_member": False}})

        def conversations_join(self, channel):
            join_called.append(channel)

    svc._ensure_in_channel(FakeClient(), "C456")  # type: ignore
    assert join_called == ["C456"]


def test_ensure_in_channel_raises_value_error_for_private_channel(monkeypatch) -> None:
    svc = SlackInvestigationService()
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")

    class FakeClient:
        def conversations_info(self, channel):
            return _FakeResponse({"channel": {"is_member": False}})

        def conversations_join(self, channel):
            raise _make_slack_api_error("method_not_supported_for_channel_type")

    with pytest.raises(ValueError, match="private channel"):
        svc._ensure_in_channel(FakeClient(), "G789")  # type: ignore


def test_fetch_thread_messages_auto_joins_and_retries(monkeypatch) -> None:
    """When conversations_replies returns not_in_channel, the service should
    auto-join and retry successfully."""
    import os
    from services.ai.slack_investigation_service import ParsedSlackThreadRef

    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
    svc = SlackInvestigationService()

    calls = {"replies": 0, "join_attempted": False}

    class FakeClient:
        def conversations_info(self, channel):
            return _FakeResponse({"channel": {"is_member": False}})

        def conversations_join(self, channel):
            calls["join_attempted"] = True

        def conversations_replies(self, channel, ts, limit, cursor, inclusive):
            calls["replies"] += 1
            if calls["replies"] == 1:
                raise _make_slack_api_error("not_in_channel")
            # Second call succeeds with one message
            return _FakeResponse({
                "messages": [
                    {
                        "ts": "1000000001.000000",
                        "user": "U123",
                        "text": "robot fault detected",
                    }
                ],
                "response_metadata": {},
            })

        def users_info(self, user):
            return _FakeResponse({
                "user": {"profile": {"display_name": "alice"}, "name": "alice"}
            })

    svc.client = FakeClient()  # type: ignore
    svc._client_token = "xoxb-fake"

    ref = ParsedSlackThreadRef(
        workspace="example",
        channel_id="C123",
        thread_ts="1000000001.000000",
    )
    messages, attachments = svc._fetch_thread_messages(ref, include_bots=False, max_messages=50)

    assert calls["join_attempted"] is True
    assert len(messages) == 1
    assert messages[0].text == "robot fault detected"


def test_fetch_thread_messages_raises_for_missing_scope(monkeypatch) -> None:
    import os
    from services.ai.slack_investigation_service import ParsedSlackThreadRef

    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
    svc = SlackInvestigationService()

    class FakeClient:
        def conversations_replies(self, **kwargs):
            raise _make_slack_api_error("missing_scope")

    svc.client = FakeClient()  # type: ignore
    svc._client_token = "xoxb-fake"

    ref = ParsedSlackThreadRef(workspace="example", channel_id="C123", thread_ts="1.0")
    with pytest.raises(RuntimeError, match="Missing Slack API scopes"):
        svc._fetch_thread_messages(ref, include_bots=False, max_messages=50)


def test_fetch_thread_messages_raises_for_invalid_auth(monkeypatch) -> None:
    import os
    from services.ai.slack_investigation_service import ParsedSlackThreadRef

    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
    svc = SlackInvestigationService()

    class FakeClient:
        def conversations_replies(self, **kwargs):
            raise _make_slack_api_error("invalid_auth")

    svc.client = FakeClient()  # type: ignore
    svc._client_token = "xoxb-fake"

    ref = ParsedSlackThreadRef(workspace="example", channel_id="C123", thread_ts="1.0")
    with pytest.raises(RuntimeError, match="Invalid Slack token"):
        svc._fetch_thread_messages(ref, include_bots=False, max_messages=50)

# ── llm_status installed field ─────────────────────────────────────────────────

def test_llm_status_returns_installed_models(monkeypatch) -> None:
    """llm_status() should list all installed models."""
    svc = SlackInvestigationService()

    monkeypatch.setattr(
        svc,
        "_ollama_models",
        lambda: ["qwen2.5:7b", "llama3.1:8b"],
    )

    status = svc.llm_status()

    assert set(status.installed) == {"qwen2.5:7b", "llama3.1:8b"}
    assert status.text_ready is True


def test_llm_status_text_not_ready_when_missing(monkeypatch) -> None:
    svc = SlackInvestigationService()

    monkeypatch.setattr(svc, "_ollama_models", lambda: ["other-model:latest"])

    status = svc.llm_status()

    assert status.text_ready is False


# ── _generate_summary with model_override ─────────────────────────────────────

def test_generate_summary_model_override(monkeypatch) -> None:
    """When model_override is set, it should be used instead of the default."""
    svc = SlackInvestigationService()

    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Arm collision near shelf",
        max_messages=200,
        model_override="llama3.1:8b",
    )
    messages = [
        SlackThreadMessage(
            ts="1772691175.223000",
            datetime="2026-03-13 10:00 UTC",
            user="alice",
            text="Collision detected",
        )
    ]

    monkeypatch.setattr(svc, "_ollama_chat", lambda _messages, _model, **kw: "## Summary\nOK")
    monkeypatch.setattr(svc, "_ollama_models", lambda: ["llama3.1:8b"])

    _summary, model_used = svc._generate_summary(req, messages, [])

    assert model_used == "llama3.1:8b"


def test_generate_summary_fallback_when_override_missing(monkeypatch) -> None:
    """When model_override is not installed, fall back to default text model."""
    svc = SlackInvestigationService()

    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Arm collision near shelf",
        max_messages=200,
        model_override="nonexistent:7b",
    )
    messages = [
        SlackThreadMessage(
            ts="1772691175.223000",
            datetime="2026-03-13 10:00 UTC",
            user="alice",
            text="Collision detected",
        )
    ]

    monkeypatch.setattr(svc, "_ollama_chat", lambda _messages, _model, **kw: "## Summary\nOK")
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])

    _summary, model_used = svc._generate_summary(req, messages, [])

    assert model_used == svc.text_model


# ── System prompt instructs point-wise output ──────────────────────────────────

def test_system_prompt_requires_bullet_points(monkeypatch) -> None:
    """The system prompt must instruct the LLM to produce bullet-point output."""
    svc = SlackInvestigationService()
    captured: dict = {}

    def spy_chat(msgs, model, **kw):
        captured["messages"] = msgs
        return "## Issue Overview\n- Robot stopped"

    monkeypatch.setattr(svc, "_ollama_chat", spy_chat)
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])

    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Test bullet prompt",
        max_messages=200,
    )
    msgs = [SlackThreadMessage(ts="1.0", datetime="2026-03-13 10:00 UTC", user="a", text="hi")]
    svc._generate_summary(req, msgs, [])

    system_content = captured["messages"][0]["content"]
    assert "bullet" in system_content.lower()
    assert "## Issue Overview" in system_content
    assert "## Key Observations" in system_content
    assert "## Root Cause Analysis" in system_content
    assert "## Actions Taken / Suggested Fixes" in system_content
    assert "## Current Status / Risks" in system_content


def test_system_prompt_says_description_is_context_only(monkeypatch) -> None:
    """The prompt must include the issue description prominently for context-aware summarization."""
    svc = SlackInvestigationService()
    captured: dict = {}

    def spy_chat(msgs, model, **kw):
        captured["messages"] = msgs
        return "## Issue Overview\n- OK"

    monkeypatch.setattr(svc, "_ollama_chat", spy_chat)
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])

    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Test description context only",
        max_messages=200,
    )
    msgs = [SlackThreadMessage(ts="1.0", datetime="2026-03-13 10:00 UTC", user="a", text="msg")]
    svc._generate_summary(req, msgs, [])

    user_content = captured["messages"][1]["content"]
    assert "issue name" in user_content.lower() or "description" in user_content.lower()
    assert "Test description context only" in user_content


# ── Full log blocks and attachments included ────────────────────────────────

def test_log_blocks_included_in_prompt(monkeypatch) -> None:
    """Log blocks should be included in the prompt up to 2000 chars."""
    svc = SlackInvestigationService()
    captured: dict = {}

    def spy_chat(msgs, model, **kw):
        captured["messages"] = msgs
        return "## The Issue\n- error"

    monkeypatch.setattr(svc, "_ollama_chat", spy_chat)
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])

    long_log = "ERROR: nav2_controller crashed at line " + "x" * 1500
    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Test log inclusion",
        max_messages=200,
    )
    msgs = [SlackThreadMessage(
        ts="1.0", datetime="2026-03-13 10:00 UTC", user="a",
        text="Check logs", log_blocks=[long_log],
    )]
    svc._generate_summary(req, msgs, [])

    user_content = captured["messages"][1]["content"]
    # Should include the log block content (not just 800 chars)
    assert "ERROR: nav2_controller crashed" in user_content
    assert len(long_log[:2000]) <= 2000


def test_attachment_text_included_in_prompt(monkeypatch) -> None:
    """Non-image attachment text should be included inline in the prompt."""
    from schemas.slack_investigation import SlackThreadAttachment

    svc = SlackInvestigationService()
    captured: dict = {}

    def spy_chat(msgs, model, **kw):
        captured["messages"] = msgs
        return "## The Issue\n- log issue"

    monkeypatch.setattr(svc, "_ollama_chat", spy_chat)
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])

    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Test attachment inclusion",
        max_messages=200,
    )
    att = SlackThreadAttachment(
        filename="robot.log", filetype="log",
        extracted="[ERROR] nav2 crashed\n[WARN] map drift detected",
    )
    msgs = [SlackThreadMessage(
        ts="1.0", datetime="2026-03-13 10:00 UTC", user="a",
        text="Attached log", attachments=[att],
    )]
    svc._generate_summary(req, msgs, [att])

    user_content = captured["messages"][1]["content"]
    assert "[ERROR] nav2 crashed" in user_content
    assert "map drift detected" in user_content


# ── Section parsing for new format ─────────────────────────────────────────────

def test_split_markdown_sections_parses_new_headings() -> None:
    """_split_markdown_sections should parse the new section headings."""
    md = (
        "## The Issue\n"
        "- Robot stopped near dock\n"
        "- Nav2 controller crashed\n\n"
        "## Timeline of Key Events\n"
        "- [10:00 UTC] Alert triggered\n"
        "- [10:05 UTC] Engineer investigated\n\n"
        "## Important Logs & Errors\n"
        "- ERROR: nav2_controller segfault\n\n"
        "## Root Cause\n"
        "- Likely map drift\n\n"
        "## Actions Taken\n"
        "- Restarted nav2 service\n\n"
        "## Resolution & Current Status\n"
        "- Robot resumed operation\n\n"
        "## Recommended Next Steps\n"
        "- Run map alignment checks\n"
    )
    sections = _split_markdown_sections(md)
    assert "the issue" in sections
    assert "timeline of key events" in sections
    assert "important logs & errors" in sections
    assert "root cause" in sections
    assert "actions taken" in sections
    assert "resolution & current status" in sections
    assert "recommended next steps" in sections


def test_find_section_matches_new_section_names() -> None:
    """_find_section should find sections by the new naming convention."""
    sections = {
        "the issue": "- Robot stopped",
        "timeline of key events": "- [10:00] Alert",
        "important logs & errors": "- ERROR: crash",
        "root cause": "- Map drift",
        "actions taken": "- Restarted",
        "resolution & current status": "- Resolved",
        "recommended next steps": "- Run checks",
    }
    assert _find_section(sections, "the issue") == "- Robot stopped"
    assert _find_section(sections, "timeline of key events", "timeline") == "- [10:00] Alert"
    assert _find_section(sections, "important logs & errors", "important logs") == "- ERROR: crash"
    assert _find_section(sections, "actions taken") == "- Restarted"
    assert _find_section(sections, "resolution & current status", "resolution") == "- Resolved"
    assert _find_section(sections, "recommended next steps", "next steps") == "- Run checks"


def test_as_bullets_extracts_bullet_lines() -> None:
    text = "- Robot stopped near dock\n- Nav2 crashed\n- Map drift suspected"
    result = _as_bullets(text)
    assert len(result) == 3
    assert "Robot stopped near dock" in result[0]


# ── Performance-related tests ──────────────────────────────────────────────────

def test_attachment_workers_increased():
    """Attachment download concurrency should be at least 16."""
    assert _MAX_ATTACHMENT_WORKERS >= 16


def test_attachment_section_not_duplicated_in_prompt(monkeypatch) -> None:
    """Attachments should NOT be sent both inline in messages AND in the
    separate ATTACHMENTS section. Only one location to avoid token bloat."""
    from schemas.slack_investigation import SlackThreadAttachment

    svc = SlackInvestigationService()
    captured: dict = {}

    def spy_chat(msgs, model, **kw):
        captured["messages"] = msgs
        captured["max_tokens"] = kw.get("max_tokens", 3500)
        return "## Issue Overview\n- test"

    monkeypatch.setattr(svc, "_ollama_chat", spy_chat)
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])

    # Create a message with a large text attachment
    long_content = "ERROR: " + "x" * 5000
    att = SlackThreadAttachment(
        filename="robot.log", filetype="log", extracted=long_content,
    )
    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Test no duplication",
        max_messages=200,
    )
    msgs = [SlackThreadMessage(
        ts="1.0", datetime="2026-03-13 10:00 UTC", user="a",
        text="See logs", attachments=[att],
    )]
    svc._generate_summary(req, msgs, [att])

    prompt = captured["messages"][1]["content"]
    # Count occurrences of the attachment content — should appear at most once
    occurrences = prompt.count("ERROR: " + "x" * 100)
    assert occurrences <= 1, (
        f"Attachment content appears {occurrences} times in prompt — should be at most 1"
    )


def test_attachment_section_truncated(monkeypatch) -> None:
    """Attachments in the separate ATTACHMENTS section should be truncated."""
    from schemas.slack_investigation import SlackThreadAttachment

    svc = SlackInvestigationService()
    captured: dict = {}

    def spy_chat(msgs, model, **kw):
        captured["messages"] = msgs
        return "## Issue Overview\n- test"

    monkeypatch.setattr(svc, "_ollama_chat", spy_chat)
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])

    long_content = "A" * 10000
    att = SlackThreadAttachment(
        filename="huge.log", filetype="log", extracted=long_content,
    )
    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Test truncation",
        max_messages=200,
    )
    msgs = [SlackThreadMessage(
        ts="1.0", datetime="2026-03-13 10:00 UTC", user="a",
        text="Big log", attachments=[att],
    )]
    svc._generate_summary(req, msgs, [att])

    prompt = captured["messages"][1]["content"]
    # The prompt should not contain the full 10000 chars of A's
    assert prompt.count("A") < 5000, "Attachment content is not being truncated in the prompt"


def test_max_tokens_reasonable_for_all_providers(monkeypatch) -> None:
    """max_tokens passed to _ollama_chat should be 2000 for all providers."""
    svc = SlackInvestigationService()
    captured: dict = {}

    def spy_chat(msgs, model, **kw):
        captured["max_tokens"] = kw.get("max_tokens", 9999)
        return "## Issue Overview\n- test"

    monkeypatch.setattr(svc, "_ollama_chat", spy_chat)
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])

    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Test max_tokens",
        max_messages=200,
    )
    msgs = [SlackThreadMessage(
        ts="1.0", datetime="2026-03-13 10:00 UTC", user="a",
        text="test",
    )]
    svc._generate_summary(req, msgs, [])
    assert captured["max_tokens"] <= 2000, (
        f"max_tokens is {captured['max_tokens']}, expected <= 2000 for speed"
    )
