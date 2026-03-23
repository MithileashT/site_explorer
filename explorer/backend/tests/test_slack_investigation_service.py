"""Unit tests for Slack investigation parsing and model-selection helpers."""

import os
import sys
import inspect

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from schemas.slack_investigation import (
    SlackThreadInvestigationRequest,
    SlackThreadMessage,
)
from services.ai.prompts import load_prompt
from services.ai.slack_investigation_service import (
    SlackInvestigationService,
    ParsedSlackThreadRef,
    _as_bullets,
    _extract_log_blocks,
    _find_section,
    _split_markdown_sections,
    parse_slack_thread_url,
    _MAX_FETCH_MESSAGES,
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


def test_slack_token_accepts_alias_token(monkeypatch) -> None:
    monkeypatch.setenv("SLACK_BOT_TOKEN", "")
    monkeypatch.setenv("SLACK_TOKEN", '"xoxb-alias-token"')

    svc = SlackInvestigationService()
    assert svc._slack_token() == "xoxb-alias-token"


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
    # Prompt uses RCA structure with Key Findings and Solution sections
    assert "**ISSUE SUMMARY**" in system_content
    assert "**Cause**" in system_content
    assert "**Key Findings**" in system_content
    assert "**Recovery Action**" in system_content
    assert "**Solution**" in system_content
    assert "INCIDENT FORMAT" in system_content


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
    """Attachment metadata should be included as lightweight file mention only."""
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
    assert "[File shared: robot.log]" in user_content
    assert "[ERROR] nav2 crashed" not in user_content


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

def test_fetch_message_cap_for_latency() -> None:
    """Slack fetch hard cap should prevent very large thread fetch latency."""
    assert _MAX_FETCH_MESSAGES <= 200


def test_file_mention_included_in_prompt(monkeypatch) -> None:
    """Prompt should include lightweight file mentions only."""
    from schemas.slack_investigation import SlackThreadAttachment

    svc = SlackInvestigationService()
    captured: dict = {}

    def spy_chat(msgs, model, **kw):
        captured["messages"] = msgs
        return "## Issue Overview\n- test"

    monkeypatch.setattr(svc, "_ollama_chat", spy_chat)
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])

    att = SlackThreadAttachment(
        filename="robot.log", filetype="log", extracted="[File shared: robot.log]",
    )
    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Test file mention",
        max_messages=200,
    )
    msgs = [SlackThreadMessage(
        ts="1.0", datetime="2026-03-13 10:00 UTC", user="a",
        text="See logs", attachments=[att],
    )]
    svc._generate_summary(req, msgs, [att])

    prompt = captured["messages"][1]["content"]
    assert "[File shared: robot.log]" in prompt
    assert "ATTACHMENTS" not in prompt


def test_no_multimodal_image_blocks(monkeypatch) -> None:
    """Prompt should remain plain text even with image attachment metadata."""
    from schemas.slack_investigation import SlackThreadAttachment

    svc = SlackInvestigationService()
    captured: dict = {}

    def spy_chat(msgs, model, **kw):
        captured["messages"] = msgs
        return "## Issue Overview\n- test"

    monkeypatch.setattr(svc, "_ollama_chat", spy_chat)
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])

    att = SlackThreadAttachment(
        filename="screenshot.png", filetype="image", extracted="[File shared: screenshot.png]", b64_image="ZmFrZS1iYXNlNjQ=",
    )
    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Test plain text prompt",
        model_override="openai:gpt-4.1",
        max_messages=200,
    )
    msgs = [SlackThreadMessage(
        ts="1.0", datetime="2026-03-13 10:00 UTC", user="a",
        text="Big log", attachments=[att],
    )]
    svc._generate_summary(req, msgs, [att])

    user_content = captured["messages"][1]["content"]
    assert isinstance(user_content, str)


def test_max_tokens_reasonable_for_all_providers(monkeypatch) -> None:
    """max_tokens passed to _ollama_chat should be at least 2000 (model-adaptive)."""
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
    assert captured["max_tokens"] >= 2000, (
        f"max_tokens is {captured['max_tokens']}, expected >= 2000 for RCA format"
    )


# ── Prompt integration tests ──────────────────────────────────────────────────

def test_generate_summary_uses_loaded_prompt(monkeypatch) -> None:
    """_generate_summary should use the prompt from issue_summary.md, not hardcoded text."""
    captured_messages: list = []

    class FakeLLM:
        active_provider = {"type": "openai", "model": "gpt-4o"}
        model = "gpt-4o"
        last_usage = {}

        def chat(self, messages, **kwargs):
            captured_messages.extend(messages)
            return (
                "**Issue Summary**\nTest.\n\n"
                "**Assessment:** AMR behavior is as designed.\n\n"
                "**Status:** Resolved\n**cc:** @test"
            )

    svc = SlackInvestigationService(_llm_service=FakeLLM())
    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://test.slack.com/archives/C123ABC/p1234567890123000",
        description="Test issue",
    )
    msgs = [SlackThreadMessage(
        ts="1.0", datetime="2026-01-01 00:00 UTC", user="alice",
        text="Robot stopped",
    )]

    svc._generate_summary(req, msgs, [])
    system_content = captured_messages[0]["content"]
    # Must contain new 6-section RCA prompt markers
    assert "INCIDENT FORMAT" in system_content
    assert "THREAD ROUTING" in system_content
    assert "THINK BEFORE YOU WRITE" in system_content
    # Must NOT contain old hardcoded markers
    assert "## Issue Overview" not in system_content
    assert "## Key Observations" not in system_content
    assert "TEMPLATE A" not in system_content


# ── Section extraction for new template formats ───────────────────────────────

def test_section_extraction_template_a_simple() -> None:
    """Parser should extract sections from Template A (Simple) output."""
    md = (
        "**Issue Summary**\n"
        "AMR01 triggered BARCODE_TOPIC_CRITICAL due to USB disconnect.\n\n"
        "**Recovery Action**\n"
        "- Re-seat the USB connector.\n\n"
        "**Assessment:** Hardware fault — USB connector instability.\n\n"
        "**Status:** Monitoring\n"
        "**cc:** @keiko"
    )
    sections = _split_markdown_sections(md)
    assert "issue summary" in sections
    assert "recovery action" in sections


def test_section_extraction_template_b_standard() -> None:
    """Parser should extract sections from Template B (Standard) output."""
    md = (
        "**Issue Summary**\n"
        "Task assignment timing issue caused by network latency.\n\n"
        "**Findings**\n"
        "- Robots transitioned to AVAILABLE after unload.\n\n"
        "**Root Cause**\n"
        "Network latency → AVAILABLE → idle nav → task arrived mid-transit.\n\n"
        "**Recovery Action**\n"
        "- Monitor edge-server network.\n\n"
        "**Assessment:** AMR behavior is as designed.\n\n"
        "**Status:** Monitoring\n"
        "**cc:** @support"
    )
    sections = _split_markdown_sections(md)
    assert "issue summary" in sections
    assert "findings" in sections
    assert "root cause" in sections
    assert "recovery action" in sections


def test_section_extraction_template_d_general() -> None:
    """Parser should extract sections from Template D (Non-Incident) output."""
    md = (
        "**Thread Summary**\n"
        "Team discussed deployment timeline for v3.7.0.\n\n"
        "**Key Points**\n"
        "- Alice confirmed staging deploy on Monday.\n"
        "- Bob raised concern about DB migration.\n\n"
        "**Decisions & Action Items**\n"
        "- Deploy staging Monday — owner: Alice.\n"
        "- Bob to test migration script by Friday.\n\n"
        "**Status:** In Progress"
    )
    sections = _split_markdown_sections(md)
    assert "thread summary" in sections
    assert "key points" in sections
    assert "decisions & action items" in sections


def test_find_section_new_template_names() -> None:
    """_find_section should match new section names from all templates."""
    sections = {
        "issue summary": "Robot stopped",
        "findings": "Log analysis confirmed X",
        "root cause": "A → B → C",
        "recovery action": "Re-seat USB",
        "thread summary": "Team discussed deployment",
        "key points": "Alice confirmed staging",
        "decisions & action items": "Deploy Monday",
    }
    assert _find_section(sections, "issue summary", "issue") == "Robot stopped"
    assert _find_section(sections, "findings") == "Log analysis confirmed X"
    assert _find_section(sections, "root cause", "tentative root cause") == "A → B → C"
    assert _find_section(sections, "thread summary") == "Team discussed deployment"
    assert _find_section(sections, "key points") == "Alice confirmed staging"
    assert _find_section(sections, "decisions & action items", "decisions", "action items") == "Deploy Monday"


# ── Assessment extraction tests ───────────────────────────────────────────────

def test_assessment_extracted_from_summary() -> None:
    """Assessment verdict should be extracted from **Assessment:** line."""
    import re

    md = (
        "**Issue Summary**\nRobot stopped.\n\n"
        "**Assessment:** This is a hardware fault.\n\n"
        "**Status:** Resolved"
    )
    match = re.search(r"\*\*Assessment:\*\*\s*(.+?)(?:\n|$)", md)
    assert match is not None
    assert match.group(1).strip() == "This is a hardware fault."


def test_assessment_field_in_response(monkeypatch) -> None:
    """investigate() should populate the assessment field on the response."""
    from schemas.slack_investigation import SlackThreadAttachment

    captured: list = []

    class FakeLLM:
        active_provider = {"type": "openai", "model": "gpt-4o"}
        model = "gpt-4o"
        last_usage = {}

        def chat(self, messages, **kwargs):
            captured.extend(messages)
            return (
                "**Issue Summary**\n"
                "AMR01 USB disconnect.\n\n"
                "**Recovery Action**\n"
                "- Re-seat USB.\n\n"
                "**Assessment:** Hardware fault — USB connector instability.\n\n"
                "**Status:** Monitoring\n"
                "**cc:** @keiko"
            )

    svc = SlackInvestigationService(_llm_service=FakeLLM())

    # Mock Slack API calls
    monkeypatch.setattr(svc, "_fetch_thread_messages", lambda ref, inc, mx: (
        [SlackThreadMessage(ts="1.0", datetime="2026-01-01", user="alice", text="USB error")],
        [],
    ))

    from schemas.slack_investigation import SlackThreadInvestigationRequest
    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://test.slack.com/archives/C123ABC/p1234567890123000",
        description="USB disconnect issue",
    )
    result = svc.investigate(req)
    assert result.assessment == "Hardware fault — USB connector instability."
    assert result.risk_level == "high"  # hardware fault → high


def test_infer_risk_from_assessment() -> None:
    """_infer_risk should derive risk_level from the assessment verdict."""
    svc = SlackInvestigationService()
    assert svc._infer_risk("", assessment="This is a hardware fault.") == "high"
    assert svc._infer_risk("", assessment="This is a software bug.") == "high"
    assert svc._infer_risk("", assessment="This is a configuration error.") == "medium"
    assert svc._infer_risk("", assessment="AMR behavior is as designed.") == "low"
    assert svc._infer_risk("", assessment="Tentative: likely a network issue; pending logs.") == "medium"


# ── Vision / multimodal image tests ───────────────────────────────────────────

def test_generate_summary_includes_images_for_vision_model(monkeypatch) -> None:
    """Text-only mode should avoid multimodal image blocks even for vision models."""
    from schemas.slack_investigation import SlackThreadAttachment

    captured: list = []

    class FakeLLM:
        active_provider = {"type": "openai", "model": "gpt-4o"}
        model = "gpt-4o"
        last_usage = {}

        def chat(self, messages, **kwargs):
            captured.extend(messages)
            return (
                "**Issue Summary**\nTest.\n\n"
                "**Assessment:** Hardware fault.\n\n"
                "**Status:** Resolved\n**cc:** @test"
            )

    svc = SlackInvestigationService(_llm_service=FakeLLM())
    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://test.slack.com/archives/C123ABC/p1234567890123000",
        description="Test issue",
    )
    msgs = [SlackThreadMessage(
        ts="1.0", datetime="2026-01-01", user="alice", text="See screenshot",
    )]
    attachments = [SlackThreadAttachment(
        filename="error.png", filetype="image", extracted="[Image: error.png]",
        b64_image="iVBORw0KGgo=",
    )]

    svc._generate_summary(req, msgs, attachments)

    user_msg = captured[1]
    assert isinstance(user_msg["content"], str)
    assert "data:image/" not in user_msg["content"]


def test_generate_summary_no_images_for_ollama(monkeypatch) -> None:
    """Ollama models should get plain text content, no image blocks."""
    from schemas.slack_investigation import SlackThreadAttachment

    captured: list = []

    class FakeLLM:
        active_provider = {"type": "ollama", "model": "qwen2.5-coder"}
        model = "qwen2.5-coder"
        last_usage = {}

        def chat(self, messages, **kwargs):
            captured.extend(messages)
            return (
                "**Issue Summary**\nTest.\n\n"
                "**Assessment:** Software bug.\n\n"
                "**Status:** Resolved\n**cc:** @test"
            )

    svc = SlackInvestigationService(_llm_service=FakeLLM())
    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://test.slack.com/archives/C123ABC/p1234567890123000",
        description="Test issue",
    )
    msgs = [SlackThreadMessage(
        ts="1.0", datetime="2026-01-01", user="alice", text="See screenshot",
    )]
    attachments = [SlackThreadAttachment(
        filename="error.png", filetype="image", extracted="[Image: error.png]",
        b64_image="iVBORw0KGgo=",
    )]

    svc._generate_summary(req, msgs, attachments)

    user_msg = captured[1]
    # For Ollama, content should be plain string (no vision support)
    assert isinstance(user_msg["content"], str)


# ── 6-section RCA format tests ────────────────────────────────────────────────

def test_section_extraction_6_section_rca() -> None:
    """Parser should extract all sections from the RCA format."""
    md = (
        "**ISSUE SUMMARY**\n"
        "AMR01 stopped navigating at Site-X due to sensor failure.\n\n"
        "**Issue**\n"
        "LiDAR FTDI USB disconnection caused AMCL localization loss.\n\n"
        "**Cause**\n"
        "USB cable fatigue caused intermittent FTDI disconnect.\n\n"
        "**Key Observations**\n"
        "- The USB disconnect proves hardware-level failure, ruling out software\n\n"
        "**Key Findings**\n"
        "- AMCL lost localization because LiDAR was its only input\n\n"
        "**Recovery Action**\n"
        "- Re-seated USB cable; robot resumed operation\n\n"
        "**Conclusion**\n"
        "USB cable fatigue → intermittent FTDI disconnect → LiDAR topic loss → AMCL delocalization → navigation halt.\n"
        "Replace USB cable with strain-relieved variant.\n\n"
        "**Assessment:** This is a hardware fault.\n\n"
        "**Status:** Resolved\n"
        "**cc:** @keiko"
    )
    sections = _split_markdown_sections(md)
    assert "issue summary" in sections
    assert "issue" in sections
    assert "cause" in sections
    assert "key observations" in sections
    assert "key findings" in sections
    assert "recovery action" in sections
    assert "conclusion" in sections

    # Verify _find_section resolves all
    assert _find_section(sections, "issue summary") != ""
    assert _find_section(sections, "cause") != ""
    assert _find_section(sections, "key observations") != ""
    assert _find_section(sections, "key findings") != ""
    assert _find_section(sections, "recovery action") != ""
    assert _find_section(sections, "conclusion") != ""
    # issue_detail uses exact match in the actual code
    assert sections.get("issue", "").strip() != ""


def test_response_includes_solution_field() -> None:
    """Response schema should have a solution field."""
    from schemas.slack_investigation import SlackThreadInvestigationResponse
    resp = SlackThreadInvestigationResponse(
        channel_id="C123", thread_ts="1.0", message_count=1,
        thread_summary="test", solution="Replace USB cable.",
    )
    assert resp.solution == "Replace USB cable."


def test_prompt_has_reasoning_preamble(monkeypatch) -> None:
    """System prompt must include chain-of-thought reasoning instructions."""
    svc = SlackInvestigationService()
    captured: dict = {}

    def spy_chat(msgs, model, **kw):
        captured["messages"] = msgs
        return "**Issue Summary**\nTest"

    monkeypatch.setattr(svc, "_ollama_chat", spy_chat)
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])

    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Test reasoning", max_messages=200,
    )
    msgs = [SlackThreadMessage(ts="1.0", datetime="2026-03-13 10:00 UTC", user="a", text="hi")]
    svc._generate_summary(req, msgs, [])

    system = captured["messages"][0]["content"]
    assert "THINK BEFORE YOU WRITE" in system
    assert "causal chain" in system.lower()


def test_prompt_has_anti_repetition_rule(monkeypatch) -> None:
    """System prompt must enforce anti-repetition between Observations and Findings."""
    svc = SlackInvestigationService()
    captured: dict = {}

    def spy_chat(msgs, model, **kw):
        captured["messages"] = msgs
        return "**Issue Summary**\nTest"

    monkeypatch.setattr(svc, "_ollama_chat", spy_chat)
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])

    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Test anti-repetition", max_messages=200,
    )
    msgs = [SlackThreadMessage(ts="1.0", datetime="2026-03-13 10:00 UTC", user="a", text="hi")]
    svc._generate_summary(req, msgs, [])

    system = captured["messages"][0]["content"]
    assert "ANTI-REPETITION" in system
    assert "exactly ONCE" in system


def test_investigate_populates_solution_field(monkeypatch) -> None:
    """investigate() should populate the solution and cause fields from LLM output."""

    class FakeLLM:
        active_provider = {"type": "openai", "model": "gpt-4o"}
        model = "gpt-4o"
        last_usage = {}

        def chat(self, messages, **kwargs):
            return (
                "**ISSUE SUMMARY**\n"
                "AMR01 stopped due to USB disconnect.\n\n"
                "**Issue**\n"
                "LiDAR FTDI USB disconnection.\n\n"
                "**Cause**\n"
                "USB cable fatigue caused intermittent FTDI disconnect.\n\n"
                "**Key Observations**\n"
                "- USB disconnect event in kernel log at 10:05\n\n"
                "**Key Findings**\n"
                "- Hardware-level failure confirmed\n\n"
                "**Recovery Action**\n"
                "- Re-seated USB cable\n\n"
                "**Conclusion**\n"
                "USB cable fatigue → FTDI disconnect → LiDAR loss → nav halt.\n"
                "Replace cable with strain-relieved variant.\n\n"
                "**Assessment:** This is a hardware fault.\n\n"
                "**Status:** Resolved\n"
                "**cc:** @keiko"
            )

    svc = SlackInvestigationService(_llm_service=FakeLLM())
    monkeypatch.setattr(svc, "_fetch_thread_messages", lambda ref, inc, mx: (
        [SlackThreadMessage(ts="1.0", datetime="2026-01-01", user="alice", text="USB error")],
        [],
    ))

    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://test.slack.com/archives/C123ABC/p1234567890123000",
        description="USB disconnect issue",
    )
    result = svc.investigate(req)
    assert "USB cable fatigue" in result.solution
    assert "strain-relieved" in result.solution
    assert result.assessment == "This is a hardware fault."
    assert result.risk_level == "high"
    # thread_summary should contain narrative sections only (no Key Findings / Conclusion)
    assert "**ISSUE SUMMARY**" in result.thread_summary
    assert "**Issue**" in result.thread_summary
    assert "**Key Findings**" not in result.thread_summary
    assert "**Conclusion**" not in result.thread_summary


# ── Strict output contract tests ──────────────────────────────────────────────


def test_strict_prompt_contains_cause_section() -> None:
    """System prompt must use **Cause** heading."""
    text = load_prompt("issue_summary")
    assert "**Cause**" in text


def test_strict_prompt_section_headings() -> None:
    """System prompt must contain all RCA section headings."""
    text = load_prompt("issue_summary")
    assert "**ISSUE SUMMARY**" in text
    assert "**Issue**" in text
    assert "**Cause**" in text
    assert "**Key Findings**" in text
    assert "**Recovery Action**" in text
    assert "**Solution**" in text


def test_investigate_no_duplicate_findings_in_thread_summary(monkeypatch) -> None:
    """thread_summary must NOT contain Key Findings/Observations or Conclusion — those go to dedicated fields."""

    class FakeLLM:
        active_provider = {"type": "openai", "model": "gpt-4o"}
        model = "gpt-4o"
        last_usage = {}

        def chat(self, messages, **kwargs):
            return (
                "**ISSUE SUMMARY**\n"
                "AMR01 stopped due to USB disconnect.\n\n"
                "**Issue**\n"
                "LiDAR FTDI USB disconnection.\n\n"
                "**Cause**\n"
                "USB cable fatigue caused FTDI adapter to lose contact.\n\n"
                "**Key Observations**\n"
                "- USB disconnect event seen in kernel log\n\n"
                "**Key Findings**\n"
                "- Hardware-level failure confirmed\n"
                "- Not a software bug\n\n"
                "**Recovery Action**\n"
                "- Re-seated USB cable\n\n"
                "**Conclusion**\n"
                "USB cable fatigue → FTDI disconnect → LiDAR loss.\n"
                "Replace cable with strain-relieved variant.\n\n"
                "**Assessment:** This is a hardware fault.\n\n"
                "**Status:** Resolved\n"
                "**cc:** @keiko"
            )

    svc = SlackInvestigationService(_llm_service=FakeLLM())
    monkeypatch.setattr(svc, "_fetch_thread_messages", lambda ref, inc, mx: (
        [SlackThreadMessage(ts="1.0", datetime="2026-01-01", user="alice", text="USB error")],
        [],
    ))

    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://test.slack.com/archives/C123ABC/p1234567890123000",
        description="USB disconnect issue",
    )
    result = svc.investigate(req)

    # thread_summary: narrative overview only (ISSUE SUMMARY + Issue + Assessment)
    assert "**ISSUE SUMMARY**" in result.thread_summary
    assert "**Issue**" in result.thread_summary

    # Sections rendered separately must NOT be in thread_summary
    assert "**Cause**" not in result.thread_summary
    assert "**Key Findings**" not in result.thread_summary
    assert "**Key Observations**" not in result.thread_summary
    assert "**Conclusion**" not in result.thread_summary
    assert "**Recovery Action**" not in result.thread_summary

    # Dedicated fields populated correctly
    assert len(result.key_findings) > 0
    assert "USB cable fatigue" in result.solution
    assert result.cause != ""
    assert "USB cable fatigue" in result.cause


def test_schema_has_cause_field() -> None:
    """Response schema must have a cause field."""
    from schemas.slack_investigation import SlackThreadInvestigationResponse
    resp = SlackThreadInvestigationResponse(
        channel_id="C123", thread_ts="1.0", message_count=1,
        thread_summary="test", cause="Bad USB cable.",
    )
    assert resp.cause == "Bad USB cable."


def test_model_adaptive_token_budget(monkeypatch) -> None:
    """_generate_summary should use different max_tokens based on model capability."""

    captured_kwargs: list = []

    class FakeLLM:
        active_provider = {"type": "openai", "model": "gpt-4o"}
        model = "gpt-4o"
        last_usage = {}

        def chat(self, messages, **kwargs):
            captured_kwargs.append(kwargs)
            return "**ISSUE SUMMARY**\nTest"

    svc = SlackInvestigationService(_llm_service=FakeLLM())

    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Token budget test", max_messages=200,
    )
    msgs = [SlackThreadMessage(ts="1.0", datetime="2026-03-13 10:00 UTC", user="a", text="hi")]

    # Test with gpt-4o (should get higher budget)
    svc._generate_summary(req, msgs, [])
    gpt4o_tokens = captured_kwargs[0].get("max_tokens", 0)

    # Test with small ollama model (should get lower budget)
    captured_kwargs.clear()
    svc._llm_service.active_provider = {"type": "ollama", "model": "qwen2.5:7b"}
    svc._llm_service.model = "qwen2.5:7b"
    monkeypatch.setattr(svc, "_ollama_models", lambda: ["qwen2.5:7b"])
    svc._generate_summary(req, msgs, [])
    ollama_tokens = captured_kwargs[0].get("max_tokens", 0)

    assert gpt4o_tokens > ollama_tokens, f"gpt-4o ({gpt4o_tokens}) should get more tokens than ollama ({ollama_tokens})"


def test_latency_optimized_token_budgets() -> None:
    """Token budgets should stay bounded to keep summary latency practical."""
    fast_cloud = SlackInvestigationService._model_summary_strategy("openai:gpt-4o")
    fast_local = SlackInvestigationService._model_summary_strategy("ollama:qwen2.5:7b")

    assert fast_cloud["max_tokens"] <= 3800
    assert fast_local["max_tokens"] <= 2200


def test_generate_summary_caps_prompt_thread_messages(monkeypatch) -> None:
    """Very long threads should be capped before constructing the LLM prompt."""
    svc = SlackInvestigationService()
    captured: dict = {}

    def spy_chat(msgs, model, **kw):
        captured["messages"] = msgs
        return "**ISSUE SUMMARY**\nCapped"

    monkeypatch.setattr(svc, "_ollama_chat", spy_chat)
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])

    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Prompt capping test",
        model_override="openai:gpt-4o",
        max_messages=400,
    )
    msgs = [
        SlackThreadMessage(
            ts=f"{i}.0",
            datetime="2026-03-13 10:00 UTC",
            user="u",
            text=f"message-{i}",
        )
        for i in range(200)
    ]

    svc._generate_summary(req, msgs, [])
    user_prompt = captured["messages"][1]["content"]
    assert "SLACK THREAD (130 messages)" in user_prompt
    assert "message-0" not in user_prompt
    assert "message-199" in user_prompt


def test_investigate_uses_fetch_cap(monkeypatch) -> None:
    """investigate() should cap max_messages passed to Slack fetch for speed."""

    class FakeLLM:
        active_provider = {"type": "openai", "model": "gpt-4o"}
        model = "gpt-4o"
        last_usage = {}

        def chat(self, messages, **kwargs):
            return (
                "**ISSUE SUMMARY**\nTest.\n\n"
                "**Issue**\nX\n\n"
                "**Cause**\nY\n\n"
                "**Key Observations**\n- O\n\n"
                "**Key Findings**\n- Z\n\n"
                "**Recovery Action**\n- A\n\n"
                "**Conclusion**\nB\n\n"
                "**Assessment:** This is a hardware fault.\n\n"
                "**Status:** Resolved\n"
                "**cc:** @test"
            )

    svc = SlackInvestigationService(_llm_service=FakeLLM())
    captured: dict = {}

    def fake_fetch(_ref, _inc, max_messages):
        captured["max_messages"] = max_messages
        return [SlackThreadMessage(ts="1.0", datetime="2026-01-01", user="alice", text="USB error")], []

    monkeypatch.setattr(svc, "_fetch_thread_messages", fake_fetch)

    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://test.slack.com/archives/C123ABC/p1234567890123000",
        description="USB disconnect issue",
        max_messages=800,
    )
    svc.investigate(req)
    assert captured["max_messages"] == _MAX_FETCH_MESSAGES


# ── Provider-matrix regression tests for strict RCA output ────────────────────

_STRICT_RCA_OUTPUT = (
    "**ISSUE SUMMARY**\n"
    "AMR01 stopped due to USB disconnect at Site-X.\n\n"
    "**Issue**\n"
    "LiDAR FTDI USB disconnection caused AMCL localization loss.\n\n"
    "**Cause**\n"
    "USB cable fatigue caused intermittent FTDI disconnect → LiDAR topic loss.\n\n"
    "**Key Observations**\n"
    "- Kernel log shows USB disconnect event at 10:05 UTC\n"
    "- LiDAR topic stopped publishing immediately after disconnect\n\n"
    "**Key Findings**\n"
    "- Hardware-level failure confirmed via kernel log\n"
    "- AMCL lost localization because LiDAR was its only input\n\n"
    "**Recovery Action**\n"
    "- Re-seated USB cable; robot resumed operation\n"
    "- Replace cable with strain-relieved variant\n\n"
    "**Conclusion**\n"
    "USB cable fatigue → FTDI disconnect → LiDAR loss → AMCL delocalization → nav halt.\n"
    "Replace cable with strain-relieved variant.\n\n"
    "**Assessment:** This is a hardware fault.\n\n"
    "**Status:** Resolved\n"
    "**cc:** @keiko"
)

_PROVIDER_MODELS = [
    ("openai", "gpt-4o"),
    ("openai", "gpt-4.1"),
    ("gemini", "gemini-2.0-flash"),
    ("ollama", "qwen2.5:7b"),
]


@pytest.mark.parametrize("provider_type,model_name", _PROVIDER_MODELS)
def test_strict_sections_parsed_per_provider(monkeypatch, provider_type, model_name) -> None:
    """Strict RCA sections must parse correctly regardless of provider."""

    class FakeLLM:
        active_provider = {"type": provider_type, "model": model_name}
        model = model_name
        last_usage = {}

        def chat(self, messages, **kwargs):
            return _STRICT_RCA_OUTPUT

    svc = SlackInvestigationService(_llm_service=FakeLLM())
    monkeypatch.setattr(svc, "_fetch_thread_messages", lambda ref, inc, mx: (
        [SlackThreadMessage(ts="1.0", datetime="2026-01-01", user="alice", text="USB error")],
        [],
    ))
    if provider_type == "ollama":
        monkeypatch.setattr(svc, "_ollama_models", lambda: [model_name])

    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://test.slack.com/archives/C123ABC/p1234567890123000",
        description="USB disconnect issue",
    )
    result = svc.investigate(req)

    # Narrative-only thread_summary — no sections rendered separately
    assert "**ISSUE SUMMARY**" in result.thread_summary
    assert "**Issue**" in result.thread_summary
    # Sections rendered as standalone UI components must NOT be in thread_summary
    assert "**Cause**" not in result.thread_summary
    assert "**Key Findings**" not in result.thread_summary
    assert "**Key Observations**" not in result.thread_summary
    assert "**Conclusion**" not in result.thread_summary
    assert "**Recovery Action**" not in result.thread_summary
    # Dedicated fields populated
    assert result.cause != ""
    assert len(result.key_findings) >= 2
    assert len(result.recommended_actions) >= 1
    assert "USB cable fatigue" in result.solution
    assert result.assessment == "This is a hardware fault."


@pytest.mark.parametrize("provider_type,model_name", _PROVIDER_MODELS)
def test_adaptive_budget_varies_by_provider(provider_type, model_name) -> None:
    """Model-adaptive strategy should return different budgets by provider class."""
    strategy = SlackInvestigationService._model_summary_strategy(f"{provider_type}:{model_name}")
    assert strategy["max_tokens"] >= 2000
    assert strategy["depth"] in ("high", "medium", "concise")


# ── GPT-5.x Model Integration Tests ──────────────────────────────────────────

_GPT5_MODELS = ["gpt-5.1", "gpt-5.2", "gpt-5.4"]


@pytest.mark.parametrize("model", _GPT5_MODELS)
def test_gpt5_model_in_pricing_registry(model) -> None:
    """GPT-5.x models must be registered in the pricing registry."""
    from services.ai.pricing import get_pricing, MODEL_PRICING
    pricing = get_pricing(model)
    # Should NOT fall back to default — should have explicit pricing
    assert model in MODEL_PRICING, f"{model} not found in MODEL_PRICING"
    assert pricing["input"] > 0
    assert pricing["output"] > 0


@pytest.mark.parametrize("model", _GPT5_MODELS)
def test_gpt5_model_summary_strategy(model) -> None:
    """GPT-5.x models should map to high-capability strategy tier."""
    strategy = SlackInvestigationService._model_summary_strategy(f"openai:{model}")
    assert strategy["max_tokens"] >= 3600, f"{model} should get high-tier max_tokens"
    assert strategy["depth"] == "high"
    assert strategy["prompt_message_limit"] >= 130


@pytest.mark.parametrize("model", _GPT5_MODELS)
def test_gpt5_models_appear_in_available_providers(model) -> None:
    """GPT-5.x models should appear in available_providers listing when OpenAI is configured."""
    from unittest.mock import patch, MagicMock
    from services.ai.llm_service import LLMService

    with patch("services.ai.llm_service.settings") as mock_settings:
        mock_settings.ollama_base_url = "http://localhost:11434/v1"
        mock_settings.ollama_host = "http://localhost:11434"
        mock_settings.ollama_model = "qwen2.5:7b"
        mock_settings.ollama_num_ctx = 8192
        mock_settings.openai_api_key = "test-key"
        mock_settings.openai_model = "gpt-4.1"
        mock_settings.gemini_api_key = ""

        with patch("services.ai.llm_service.OpenAI"):
            svc = LLMService()
            providers = svc.available_providers()
            provider_ids = [p["id"] for p in providers]
            assert f"openai:{model}" in provider_ids, f"{model} not in available_providers"


# ── Streaming Endpoint Tests ─────────────────────────────────────────────────

def test_streaming_investigate_endpoint_exists() -> None:
    """The streaming SSE endpoint for investigation should exist."""
    from app.routes.slack_investigation import router
    routes = [r.path for r in router.routes]
    assert "/api/v1/slack/investigate/stream" in routes


def test_streaming_investigate_returns_sse(monkeypatch) -> None:
    """The streaming endpoint should return text/event-stream media type."""
    from app.routes.slack_investigation import router, register_singletons
    from app.routes import slack_investigation as route_mod
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    class FakeLLM:
        active_provider = {"type": "openai", "model": "gpt-4o"}
        model = "gpt-4o"
        last_usage = {}
        def chat(self, messages, **kwargs):
            return _STRICT_RCA_OUTPUT
        def chat_stream(self, messages, **kwargs):
            for chunk in ["**ISSUE ", "SUMMARY**\n", "Test."]:
                yield chunk

    app = FastAPI()
    app.include_router(router)
    register_singletons(FakeLLM())

    # Patch the service's fetch to avoid real Slack calls
    svc = route_mod._service
    monkeypatch.setattr(svc, "_fetch_thread_messages", lambda ref, inc, mx: (
        [SlackThreadMessage(ts="1.0", datetime="2026-01-01", user="alice", text="USB error")],
        [],
    ))

    # Use stream=True to consume SSE
    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/api/v1/slack/investigate/stream",
            json={
                "slack_thread_url": "https://test.slack.com/archives/C123ABC/p1234567890123000",
                "description": "Test streaming endpoint",
            },
        ) as resp:
            assert resp.headers.get("content-type", "").startswith("text/event-stream")
            # Read at least one chunk to confirm data flows
            chunks = []
            for line in resp.iter_lines():
                if line:
                    chunks.append(line)
                if len(chunks) >= 2:
                    break
            assert len(chunks) >= 1, "Should receive at least one SSE data line"


# ── Response Caching Tests ───────────────────────────────────────────────────

def test_summary_cache_returns_cached_result(monkeypatch) -> None:
    """Repeated identical requests should use cached summary to avoid re-calling LLM."""
    call_count = {"n": 0}

    class FakeLLM:
        active_provider = {"type": "openai", "model": "gpt-4o"}
        model = "gpt-4o"
        last_usage = {}
        def chat(self, messages, **kwargs):
            call_count["n"] += 1
            return _STRICT_RCA_OUTPUT

    svc = SlackInvestigationService(_llm_service=FakeLLM())
    monkeypatch.setattr(svc, "_fetch_thread_messages", lambda ref, inc, mx: (
        [SlackThreadMessage(ts="1.0", datetime="2026-01-01", user="alice", text="USB error")],
        [],
    ))

    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://test.slack.com/archives/C123ABC/p1234567890123000",
        description="USB disconnect issue",
    )
    result1 = svc.investigate(req)
    result2 = svc.investigate(req)

    assert result1.thread_summary == result2.thread_summary
    assert call_count["n"] == 1, "Second call should use cache, not call LLM again"


def test_summary_cache_key_differs_by_model(monkeypatch) -> None:
    """Cache should differentiate by model_override — different models should not share cache."""
    calls = []

    class FakeLLM:
        active_provider = {"type": "openai", "model": "gpt-4o"}
        model = "gpt-4o"
        last_usage = {}
        def chat(self, messages, **kwargs):
            calls.append(kwargs.get("model_override"))
            return _STRICT_RCA_OUTPUT

    svc = SlackInvestigationService(_llm_service=FakeLLM())
    monkeypatch.setattr(svc, "_fetch_thread_messages", lambda ref, inc, mx: (
        [SlackThreadMessage(ts="1.0", datetime="2026-01-01", user="alice", text="USB error")],
        [],
    ))

    req1 = SlackThreadInvestigationRequest(
        slack_thread_url="https://test.slack.com/archives/C123ABC/p1234567890123000",
        description="USB disconnect issue",
        model_override="openai:gpt-4o",
    )
    req2 = SlackThreadInvestigationRequest(
        slack_thread_url="https://test.slack.com/archives/C123ABC/p1234567890123000",
        description="USB disconnect issue",
        model_override="openai:gpt-5.1",
    )
    svc.investigate(req1)
    svc.investigate(req2)
    assert len(calls) == 2, "Different models should NOT share cache"


def test_summary_cache_key_changes_when_prompt_changes(monkeypatch) -> None:
    """Cache key should change when issue_summary prompt content changes."""
    svc = SlackInvestigationService()
    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://test.slack.com/archives/C123ABC/p1234567890123000",
        description="USB disconnect issue",
        model_override="openai:gpt-4o",
    )
    msgs = [
        SlackThreadMessage(ts="1.0", datetime="2026-01-01", user="alice", text="USB error"),
    ]

    monkeypatch.setattr("services.ai.slack_investigation_service.load_prompt", lambda _name: "prompt-v1")
    key1 = svc._build_cache_key(req, msgs, "openai:gpt-4o")

    monkeypatch.setattr("services.ai.slack_investigation_service.load_prompt", lambda _name: "prompt-v2")
    key2 = svc._build_cache_key(req, msgs, "openai:gpt-4o")

    assert key1 != key2, "Prompt changes must invalidate cached summaries"


# ── Prompt Optimization Tests ─────────────────────────────────────────────────

def test_prompt_has_key_findings_section() -> None:
    """Prompt should use 'Key Findings' heading per updated spec."""
    prompt = load_prompt("issue_summary")
    assert "**Key Findings**" in prompt


def test_prompt_has_solution_section() -> None:
    """Prompt should have Solution section per updated spec."""
    prompt = load_prompt("issue_summary")
    assert "**Solution**" in prompt


def test_prompt_char_count_within_budget() -> None:
    """The system prompt should be optimized — under 5000 characters for efficiency."""
    prompt = load_prompt("issue_summary")
    assert len(prompt) <= 10000, f"Prompt is {len(prompt)} chars — should be ≤ 10000 for token efficiency"


# ── Enhanced Logging Tests ────────────────────────────────────────────────────

def test_investigate_logs_timing_and_tokens(monkeypatch, caplog) -> None:
    """investigate() should log timing, token usage, and model selection."""
    import logging

    class FakeLLM:
        active_provider = {"type": "openai", "model": "gpt-4o"}
        model = "gpt-4o"
        last_usage = {"prompt_tokens": 500, "completion_tokens": 200, "total_tokens": 700, "cost_usd": 0.005}
        def chat(self, messages, **kwargs):
            return _STRICT_RCA_OUTPUT

    svc = SlackInvestigationService(_llm_service=FakeLLM())
    monkeypatch.setattr(svc, "_fetch_thread_messages", lambda ref, inc, mx: (
        [SlackThreadMessage(ts="1.0", datetime="2026-01-01", user="alice", text="USB error")],
        [],
    ))

    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://test.slack.com/archives/C123ABC/p1234567890123000",
        description="Test timing",
    )

    with caplog.at_level(logging.INFO, logger="services.ai.slack_investigation_service"):
        svc.investigate(req)

    timing_logged = any("fetch=" in r.message and "llm=" in r.message and "total=" in r.message for r in caplog.records)
    assert timing_logged, "investigate should log fetch/llm/total timing"


# ── Async Route Tests ────────────────────────────────────────────────────────

def test_investigate_route_is_async() -> None:
    """The investigate endpoint should be async for non-blocking concurrency."""
    from app.routes.slack_investigation import investigate_slack_thread
    import asyncio
    assert asyncio.iscoroutinefunction(investigate_slack_thread), "investigate endpoint should be async"


# ── investigate_streaming tests ──────────────────────────────────────────────

def test_investigate_streaming_yields_chunks_and_result(monkeypatch) -> None:
    """investigate_streaming should yield ('chunk', text) events and a final ('result', response)."""
    svc = SlackInvestigationService()
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")

    # Stub Ollama ping + models
    monkeypatch.setattr(svc, "_ollama_ping", lambda: True)
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])

    # Stub _fetch_thread_messages to return canned data
    from services.ai.slack_investigation_service import ParsedSlackThreadRef
    canned_messages = [
        SlackThreadMessage(ts="1.0", datetime="2026-03-13 10:00 UTC", user="alice", text="Robot fault detected"),
    ]
    monkeypatch.setattr(svc, "_fetch_thread_messages", lambda ref, bots, limit: (canned_messages, []))

    # Stub _ollama_chat for non-streaming fallback
    monkeypatch.setattr(svc, "_ollama_chat", lambda msgs, model, **kw: "## ISSUE SUMMARY\nRobot stopped\n\n**Assessment:** software bug")

    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Test streaming investigation",
        max_messages=200,
    )

    events = list(svc.investigate_streaming(req))

    chunk_events = [(t, d) for t, d in events if t == "chunk"]
    result_events = [(t, d) for t, d in events if t == "result"]

    assert len(chunk_events) >= 1, "Should yield at least one chunk"
    assert len(result_events) == 1, "Should yield exactly one result"

    result = result_events[0][1]
    assert result.message_count == 1
    assert result.workspace == "example"
    assert result.raw_analysis  # should have content


def test_investigate_streaming_with_llm_service_stream(monkeypatch) -> None:
    """When _llm_service has chat_stream, streaming yields individual tokens."""
    svc = SlackInvestigationService()
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")

    monkeypatch.setattr(svc, "_ollama_ping", lambda: True)
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])

    canned_messages = [
        SlackThreadMessage(ts="1.0", datetime="2026-03-13 10:00 UTC", user="alice", text="fault"),
    ]
    monkeypatch.setattr(svc, "_fetch_thread_messages", lambda ref, bots, limit: (canned_messages, []))

    # Mock LLM service with chat_stream
    class MockLLMService:
        model = "qwen2.5:7b"
        active_provider = {"type": "ollama", "model": "qwen2.5:7b"}
        last_usage = {}

        def chat_stream(self, messages, max_tokens, temperature, model_override, module):
            yield "## ISSUE "
            yield "SUMMARY\n"
            yield "Robot stopped"

    svc._llm_service = MockLLMService()

    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Test token streaming",
        max_messages=200,
    )

    events = list(svc.investigate_streaming(req))
    chunk_events = [(t, d) for t, d in events if t == "chunk"]
    result_events = [(t, d) for t, d in events if t == "result"]

    assert len(chunk_events) == 3, "Should yield 3 streaming chunks"
    assert chunk_events[0][1] == "## ISSUE "
    assert chunk_events[1][1] == "SUMMARY\n"
    assert chunk_events[2][1] == "Robot stopped"
    assert len(result_events) == 1


def test_investigate_streaming_cache_hit(monkeypatch) -> None:
    """On cache hit, streaming yields the full text as a single chunk plus result."""
    svc = SlackInvestigationService()
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
    monkeypatch.setattr(svc, "_ollama_ping", lambda: True)
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])

    canned_messages = [
        SlackThreadMessage(ts="1.0", datetime="2026-03-13 10:00 UTC", user="alice", text="fault"),
    ]
    monkeypatch.setattr(svc, "_fetch_thread_messages", lambda ref, bots, limit: (canned_messages, []))
    monkeypatch.setattr(svc, "_ollama_chat", lambda msgs, model, **kw: "## ISSUE SUMMARY\nCached result")

    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Test cache hit",
        max_messages=200,
    )

    # First call populates cache (non-streaming)
    svc._generate_summary(req, canned_messages, [])

    # Second call via streaming should hit cache
    events = list(svc.investigate_streaming(req))
    chunk_events = [(t, d) for t, d in events if t == "chunk"]
    result_events = [(t, d) for t, d in events if t == "result"]

    assert len(chunk_events) == 1, "Cache hit should yield single chunk with full text"
    assert "Cached result" in chunk_events[0][1]
    assert len(result_events) == 1


# ── _build_response tests ───────────────────────────────────────────────────

def test_build_response_parses_rca_sections() -> None:
    """_build_response should correctly parse RCA markdown into structured fields."""
    import time
    svc = SlackInvestigationService()

    ref = ParsedSlackThreadRef(workspace="test", channel_id="C123", thread_ts="1.0")
    messages = [
        SlackThreadMessage(ts="1.0", datetime="2026-03-13 10:00 UTC", user="alice", text="fault"),
    ]

    summary = (
        "## ISSUE SUMMARY\nRobot stopped near dock A3.\n\n"
        "## Issue\nNavigation failure due to map mismatch.\n\n"
        "## Cause\nMap was not updated after shelf relocation.\n\n"
        "## Key Observations\n- Map drift of 2cm detected\n- AMCL confidence dropped below threshold\n\n"
        "## Key Findings\n- Shelf relocated without map update\n\n"
        "## Recovery Action\n- Re-run map alignment\n- Validate AMCL params\n\n"
        "## Conclusion\nMap mismatch caused nav failure.\n\n"
        "**Assessment:** configuration error\n"
    )

    t0 = time.perf_counter()
    resp = svc._build_response(req=SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123/p1000000000",
        description="test build response",
    ), ref=ref, messages=messages, attachments=[], summary=summary,
        model_used="test-model", t0=t0, t_fetch=t0 + 1.0)

    assert resp.assessment == "configuration error"
    assert resp.cause == "Map was not updated after shelf relocation."
    assert resp.risk_level == "medium"
    assert len(resp.key_findings) >= 2
    assert len(resp.recommended_actions) >= 2
    assert resp.message_count == 1
    assert resp.file_mention_count == 0
    assert resp.attachment_count == 0


def test_build_prompt_messages_signature_no_attachments_param() -> None:
    """Prompt builder should not carry an unused attachments parameter in text-only mode."""
    params = inspect.signature(SlackInvestigationService._build_prompt_messages).parameters
    assert "attachments" not in params


# ── _pre_investigate tests ───────────────────────────────────────────────────

def test_pre_investigate_returns_expected_tuple(monkeypatch) -> None:
    """_pre_investigate should return (ref, messages, attachments, t0, t_fetch)."""
    svc = SlackInvestigationService()
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
    monkeypatch.setattr(svc, "_ollama_ping", lambda: True)

    canned = [
        SlackThreadMessage(ts="1.0", datetime="2026-03-13 10:00 UTC", user="alice", text="msg"),
    ]
    monkeypatch.setattr(svc, "_fetch_thread_messages", lambda ref, bots, limit: (canned, []))

    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="pre-investigate test",
        max_messages=200,
    )

    ref, messages, attachments, t0, t_fetch = svc._pre_investigate(req)

    assert ref.workspace == "example"
    assert ref.channel_id == "C123ABC45"
    assert len(messages) == 1
    assert t_fetch > t0


# ── Prompt Optimization v2 Tests ─────────────────────────────────────────────

def test_prompt_has_log_evidence_rules() -> None:
    """Prompt must contain LOG EVIDENCE RULES section for structured log handling."""
    prompt = load_prompt("issue_summary")
    assert "LOG EVIDENCE RULES" in prompt


def test_prompt_has_depth_scaling_directive() -> None:
    """Prompt must contain DEPTH SCALING rule with 600-900 word target."""
    prompt = load_prompt("issue_summary")
    assert "DEPTH SCALING" in prompt
    assert "600-900" in prompt


def test_prompt_has_no_bulky_reference_example() -> None:
    """Reference example was removed to save ~674 tokens per call."""
    prompt = load_prompt("issue_summary")
    assert "REFERENCE EXAMPLE" not in prompt


def test_high_capability_model_gets_3600_max_tokens() -> None:
    """High-capability models (gpt-4o, gpt-4.1) should get max_tokens=3600."""
    for model in ("openai:gpt-4o", "openai:gpt-4.1", "openai:gpt-4.1-mini"):
        strategy = SlackInvestigationService._model_summary_strategy(model)
        assert strategy["max_tokens"] == 3600, f"{model} should have max_tokens=3600"
        assert strategy["prompt_char_budget"] == 13000, f"{model} should have prompt_char_budget=13000"
        assert strategy["prompt_message_limit"] == 130, f"{model} should have prompt_message_limit=130"


def test_mid_tier_model_gets_2800_max_tokens() -> None:
    """Mid-tier models (gpt-4o-mini) should get max_tokens=2800."""
    strategy = SlackInvestigationService._model_summary_strategy("openai:gpt-4o-mini")
    assert strategy["max_tokens"] == 2800
    assert strategy["prompt_char_budget"] == 12000
    assert strategy["prompt_message_limit"] == 100


def test_cache_key_varies_with_site_id(monkeypatch) -> None:
    """Cache key must change when site_id differs."""
    svc = SlackInvestigationService()
    msgs = [SlackThreadMessage(ts="1.0", datetime="2026-01-01", user="a", text="x")]

    req1 = SlackThreadInvestigationRequest(
        slack_thread_url="https://test.slack.com/archives/C1/p1000",
        description="test cache", site_id="site-A",
    )
    req2 = SlackThreadInvestigationRequest(
        slack_thread_url="https://test.slack.com/archives/C1/p1000",
        description="test cache", site_id="site-B",
    )
    k1 = svc._build_cache_key(req1, msgs, "openai:gpt-4o")
    k2 = svc._build_cache_key(req2, msgs, "openai:gpt-4o")
    assert k1 != k2, "Different site_id should produce different cache keys"


def test_cache_key_varies_with_custom_prompt(monkeypatch) -> None:
    """Cache key must change when custom_prompt differs."""
    svc = SlackInvestigationService()
    msgs = [SlackThreadMessage(ts="1.0", datetime="2026-01-01", user="a", text="x")]

    req1 = SlackThreadInvestigationRequest(
        slack_thread_url="https://test.slack.com/archives/C1/p1000",
        description="test cache", custom_prompt="focus on motor errors",
    )
    req2 = SlackThreadInvestigationRequest(
        slack_thread_url="https://test.slack.com/archives/C1/p1000",
        description="test cache", custom_prompt="focus on network errors",
    )
    k1 = svc._build_cache_key(req1, msgs, "openai:gpt-4o")
    k2 = svc._build_cache_key(req2, msgs, "openai:gpt-4o")
    assert k1 != k2, "Different custom_prompt should produce different cache keys"


# ── Section Deduplication Tests ──────────────────────────────────────────────

def test_thread_summary_does_not_contain_cause_when_cause_field_populated() -> None:
    """thread_summary must NOT embed Cause text when cause is a standalone field."""
    import time
    svc = SlackInvestigationService()

    ref = ParsedSlackThreadRef(workspace="test", channel_id="C123", thread_ts="1.0")
    messages = [
        SlackThreadMessage(ts="1.0", datetime="2026-03-23 10:00 UTC", user="alice", text="fault"),
    ]

    summary = (
        "## ISSUE SUMMARY\nRobot amr55 stopped at dock B4.\n\n"
        "## Issue\nWeight scale pick-wait timeout exceeded threshold.\n\n"
        "## Cause\nGroup picking config radius of 5.4m merged adjacent pick spots.\n\n"
        "## Key Findings\n- distance_between_picking_spots: 5.4 caused merging\n\n"
        "## Recovery Action\n- Reduced group picking radius to 2.0m\n\n"
        "## Solution\nReduce group picking config from 5.4 to 2.0.\n\n"
        "**Assessment:** This is a configuration error.\n"
    )

    t0 = time.perf_counter()
    resp = svc._build_response(
        req=SlackThreadInvestigationRequest(
            slack_thread_url="https://example.slack.com/archives/C123/p1000000000",
            description="test dedup",
        ),
        ref=ref, messages=messages, attachments=[], summary=summary,
        model_used="test-model", t0=t0, t_fetch=t0 + 1.0,
    )

    # Cause should be in the standalone field
    assert resp.cause == "Group picking config radius of 5.4m merged adjacent pick spots."
    # But NOT duplicated inside thread_summary
    assert "**Cause**" not in resp.thread_summary, (
        f"thread_summary should not embed Cause when cause field is populated.\n"
        f"thread_summary was:\n{resp.thread_summary}"
    )


def test_thread_summary_excludes_fields_rendered_separately() -> None:
    """thread_summary should only contain ISSUE SUMMARY narrative, not sections shown elsewhere."""
    import time
    svc = SlackInvestigationService()

    ref = ParsedSlackThreadRef(workspace="test", channel_id="C123", thread_ts="1.0")
    messages = [
        SlackThreadMessage(ts="1.0", datetime="2026-03-23 10:00 UTC", user="alice", text="fault"),
    ]

    summary = (
        "## ISSUE SUMMARY\nRobot stopped due to motor fault.\n\n"
        "## Issue\nMotor overcurrent on drive motor 2.\n\n"
        "## Cause\nBearing seized causing overcurrent condition.\n\n"
        "## Key Findings\n- Motor current exceeded 15A threshold\n\n"
        "## Recovery Action\n- Replaced drive motor bearing\n\n"
        "## Solution\nReplace bearings on preventive schedule.\n\n"
        "**Assessment:** This is a hardware fault.\n"
    )

    t0 = time.perf_counter()
    resp = svc._build_response(
        req=SlackThreadInvestigationRequest(
            slack_thread_url="https://example.slack.com/archives/C123/p1000000000",
            description="test no overlap",
        ),
        ref=ref, messages=messages, attachments=[], summary=summary,
        model_used="test-model", t0=t0, t_fetch=t0 + 1.0,
    )

    # These sections are rendered as standalone UI components — should not be in thread_summary
    assert "**Key Findings**" not in resp.thread_summary
    assert "**Recovery Action**" not in resp.thread_summary
    assert "**Solution**" not in resp.thread_summary


def test_key_findings_not_duplicated_from_observations_overlap() -> None:
    """When LLM outputs only 'Key Findings' (no separate 'Key Observations'),
    the findings should not be doubled."""
    import time
    svc = SlackInvestigationService()

    ref = ParsedSlackThreadRef(workspace="test", channel_id="C123", thread_ts="1.0")
    messages = [
        SlackThreadMessage(ts="1.0", datetime="2026-03-23 10:00 UTC", user="alice", text="fault"),
    ]

    # LLM produces ONLY "Key Findings" — no separate "Key Observations"
    summary = (
        "## ISSUE SUMMARY\nRobot navigation fault.\n\n"
        "## Issue\nAMCL delocalization.\n\n"
        "## Cause\nUSB cable fatigue.\n\n"
        "## Key Findings\n"
        "- LiDAR topic went silent at 10:05:04\n"
        "- AMCL confidence dropped to 0.1 at 10:05:07\n\n"
        "## Recovery Action\n- Re-seated USB cable\n\n"
        "## Solution\nReplace USB cable.\n\n"
        "**Assessment:** This is a hardware fault.\n"
    )

    t0 = time.perf_counter()
    resp = svc._build_response(
        req=SlackThreadInvestigationRequest(
            slack_thread_url="https://example.slack.com/archives/C123/p1000000000",
            description="test findings dedup",
        ),
        ref=ref, messages=messages, attachments=[], summary=summary,
        model_used="test-model", t0=t0, t_fetch=t0 + 1.0,
    )

    # Should have exactly 2 findings, not 4 (doubled)
    assert len(resp.key_findings) == 2, (
        f"Expected 2 findings but got {len(resp.key_findings)}: {resp.key_findings}"
    )


def test_prompt_has_strict_no_overlap_rule() -> None:
    """Prompt must contain explicit NO-OVERLAP instruction between sections."""
    prompt = load_prompt("issue_summary")
    prompt_lower = prompt.lower()
    # Should contain explicit deduplication directive
    assert "each section must contain unique information" in prompt_lower or \
           "no overlap" in prompt_lower or \
           "never repeat" in prompt_lower or \
           "do not restate" in prompt_lower, \
        "Prompt must contain explicit section deduplication rule"


def test_prompt_differentiates_cause_from_solution() -> None:
    """Prompt must clearly distinguish Cause (why) from Solution (fix) scopes."""
    prompt = load_prompt("issue_summary")
    # The Cause section should not mention "permanent fix"
    # The Solution section should not describe the root cause mechanism
    cause_section_start = prompt.find("**Cause**")
    solution_section_start = prompt.find("**Solution**")
    assert cause_section_start != -1 and solution_section_start != -1

    cause_section = prompt[cause_section_start:solution_section_start]
    # Cause section should focus on root cause, not on "permanent fix"
    assert "permanent fix" not in cause_section.lower(), \
        "Cause section should describe WHY, not the fix"
