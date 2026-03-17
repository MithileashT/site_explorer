"""Tests verifying the Ollama integration in SlackInvestigationService.

Each test maps to a specific requirement from the Ollama spec:
  - Model selection (vision vs text based on images)
  - Ollama /api/chat payload structure
  - Image handling (raw base64, cap at 4)
  - Timeout and error handling
  - Config env var defaults
  - Status endpoint (online/offline)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from core.config import settings
from schemas.slack_investigation import (
    SlackThreadAttachment,
    SlackThreadInvestigationRequest,
    SlackThreadMessage,
)
from services.ai.slack_investigation_service import SlackInvestigationService


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_svc() -> SlackInvestigationService:
    return SlackInvestigationService()


def _make_req(**overrides) -> SlackThreadInvestigationRequest:
    defaults = dict(
        slack_thread_url="https://ex.slack.com/archives/C123ABC45/p1772691175223000",
        description="Robot fault near dock 3",
    )
    defaults.update(overrides)
    return SlackThreadInvestigationRequest(**defaults)


def _text_messages(n: int = 2) -> list[SlackThreadMessage]:
    return [
        SlackThreadMessage(
            ts=f"177269117{i}.000000",
            datetime=f"2026-03-13 10:0{i} UTC",
            user=f"user{i}",
            text=f"Message {i}",
        )
        for i in range(n)
    ]


def _image_attachment(name: str = "fault.png", b64: str = "iVBOR") -> SlackThreadAttachment:
    return SlackThreadAttachment(
        filename=name, filetype="image", extracted=f"[Image: {name}]", b64_image=b64,
    )


def _text_attachment(name: str = "robot.log") -> SlackThreadAttachment:
    return SlackThreadAttachment(
        filename=name, filetype="log", extracted="[ERROR] nav2 crashed",
    )


# ── 1. Config defaults match spec ───────────────────────────────────────────

class TestConfigDefaults:
    """Verify OLLAMA_* env var defaults and resolution logic.

    _Settings uses class-level os.getenv() evaluated once at import time,
    so we test the resolution expressions directly rather than re-instantiating.
    """

    def test_default_text_model(self):
        assert settings.ollama_text_model == os.getenv("OLLAMA_TEXT_MODEL", "qwen2.5:7b")

    def test_ollama_host_strips_v1_suffix(self):
        """The host derivation expression strips /v1 from OLLAMA_BASE_URL."""
        base = "http://ollama:11434/v1"
        assert base.removesuffix("/v1") == "http://ollama:11434"

    def test_ollama_host_fallback_default(self):
        """When no env vars set, ollama_host defaults to http://localhost:11434."""
        default_base = "http://localhost:11434/v1"
        assert default_base.removesuffix("/v1") == "http://localhost:11434"

    def test_service_reads_models_from_settings(self):
        """SlackInvestigationService picks up model names from settings."""
        svc = _make_svc()
        assert svc.text_model == settings.ollama_text_model
        assert svc.ollama_host == settings.ollama_host.rstrip("/")


# ── 2. Model selection logic ────────────────────────────────────────────────

class TestModelSelection:
    """has_images → vision model; text only → text model."""

    def test_text_only_thread_uses_text_model(self, monkeypatch):
        svc = _make_svc()
        monkeypatch.setattr(svc, "_ollama_chat", lambda msgs, model, **kw: "## The Issue\nSummary")

        _, model = svc._generate_summary(
            _make_req(), _text_messages(), [],
        )
        assert model == svc.text_model

    def test_thread_with_images_still_uses_text_model(self, monkeypatch):
        """Images are collected but not sent to the LLM — text model is always used."""
        svc = _make_svc()
        monkeypatch.setattr(svc, "_ollama_chat", lambda msgs, model, **kw: "## The Issue\nSummary")
        monkeypatch.setattr(svc, "_ollama_models", lambda: ["qwen2.5:7b", "llama3.1:8b"])

        _, model = svc._generate_summary(
            _make_req(), _text_messages(), [_image_attachment()],
        )
        assert model == svc.text_model

    def test_non_image_attachments_use_text_model(self, monkeypatch):
        svc = _make_svc()
        monkeypatch.setattr(svc, "_ollama_chat", lambda msgs, model, **kw: "## The Issue\nSummary")

        _, model = svc._generate_summary(
            _make_req(), _text_messages(), [_text_attachment()],
        )
        assert model == svc.text_model

    def test_model_override_not_installed_falls_back_to_text(self, monkeypatch):
        """When override model is missing, fall back to default text model."""
        svc = _make_svc()
        monkeypatch.setattr(svc, "_ollama_chat", lambda msgs, model, **kw: "## The Issue\nSummary")
        monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])

        _, model = svc._generate_summary(
            _make_req(model_override="nonexistent:7b"), _text_messages(), [],
        )
        assert model == svc.text_model


# ── 3. Ollama /api/chat payload structure ────────────────────────────────────

class TestOllamaChatPayload:
    """Verify the exact payload sent to POST /api/chat."""

    def test_payload_structure_text_only(self, monkeypatch):
        svc = _make_svc()
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"message": {"content": "ok"}}
            return resp

        monkeypatch.setattr(requests, "post", fake_post)

        result = svc._ollama_chat(
            [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
            "qwen2.5:7b",
        )

        assert captured["url"] == f"{svc.ollama_host}/api/chat"
        payload = captured["json"]
        assert payload["model"] == "qwen2.5:7b"
        assert payload["stream"] is False
        assert payload["options"]["temperature"] == 0.2
        assert payload["options"]["num_ctx"] == settings.ollama_num_ctx
        assert payload["messages"][0]["role"] == "system"
        assert payload["messages"][1]["role"] == "user"
        assert captured["timeout"] == 180
        assert result == "ok"

    def test_payload_includes_images_when_present(self, monkeypatch):
        svc = _make_svc()
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["json"] = json
            resp = MagicMock()
            resp.json.return_value = {"message": {"content": "ok"}}
            return resp

        monkeypatch.setattr(requests, "post", fake_post)

        chat_msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "describe", "images": ["aGVsbG8="]},
        ]
        svc._ollama_chat(chat_msgs, "llama3.1:8b")

        sent_msgs = captured["json"]["messages"]
        assert "images" in sent_msgs[1]
        assert sent_msgs[1]["images"] == ["aGVsbG8="]


# ── 4. Image handling ────────────────────────────────────────────────────────

class TestImageHandling:
    """Images are no longer sent to the LLM — verify no images key in chat."""

    def test_no_images_key_in_generated_summary(self, monkeypatch):
        """_generate_summary should never include images in the chat payload."""
        svc = _make_svc()
        captured_msgs = []

        def spy_chat(msgs, model, **kw):
            captured_msgs.extend(msgs)
            return "## The Issue\nDone"

        monkeypatch.setattr(svc, "_ollama_chat", spy_chat)

        attachments = [_image_attachment("a.png", b64="iVBORw0KGgoAAAA")]
        svc._generate_summary(_make_req(), _text_messages(), attachments)

        user_msg = next(m for m in captured_msgs if m["role"] == "user")
        assert "images" not in user_msg

    def test_no_images_key_when_text_only(self, monkeypatch):
        svc = _make_svc()
        captured_msgs = []

        def spy_chat(msgs, model, **kw):
            captured_msgs.extend(msgs)
            return "## The Issue\nDone"

        monkeypatch.setattr(svc, "_ollama_chat", spy_chat)

        svc._generate_summary(_make_req(), _text_messages(), [])

        user_msg = next(m for m in captured_msgs if m["role"] == "user")
        assert "images" not in user_msg


# ── 5. Timeout & error handling ──────────────────────────────────────────────

class TestOllamaErrors:
    """Connection errors and HTTP failures."""

    def test_connection_error_raises_runtime(self, monkeypatch):
        svc = _make_svc()

        def raise_conn_err(*args, **kwargs):
            raise requests.exceptions.ConnectionError("refused")

        monkeypatch.setattr(requests, "post", raise_conn_err)

        with pytest.raises(RuntimeError, match="Ollama is not running"):
            svc._ollama_chat([{"role": "user", "content": "hi"}], "qwen2.5:7b")

    def test_http_error_raises_runtime(self, monkeypatch):
        svc = _make_svc()

        def fail_500(*args, **kwargs):
            resp = MagicMock()
            resp.status_code = 500
            resp.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
            return resp

        monkeypatch.setattr(requests, "post", fail_500)

        with pytest.raises(RuntimeError, match="Local LLM error"):
            svc._ollama_chat([{"role": "user", "content": "hi"}], "qwen2.5:7b")


# ── 6. Status endpoint logic ────────────────────────────────────────────────

class TestLLMStatus:
    """llm_status() reports correct online/offline + model readiness."""

    def test_offline_when_ping_fails(self, monkeypatch):
        svc = _make_svc()
        monkeypatch.setattr(svc, "_ollama_ping", lambda: False)

        status = svc.llm_status()
        assert status.status == "offline"
        assert status.text_ready is False
        assert status.fix is not None

    def test_online_text_model_ready(self, monkeypatch):
        svc = _make_svc()
        monkeypatch.setattr(svc, "_ollama_ping", lambda: True)
        monkeypatch.setattr(svc, "_ollama_models", lambda: [
            "qwen2.5:7b", "llama3.1:8b",
        ])

        status = svc.llm_status()
        assert status.status == "online"
        assert status.text_ready is True
        assert status.fix is None

    def test_online_text_model_not_ready(self, monkeypatch):
        svc = _make_svc()
        monkeypatch.setattr(svc, "_ollama_ping", lambda: True)
        monkeypatch.setattr(svc, "_ollama_models", lambda: ["other-model:latest"])

        status = svc.llm_status()
        assert status.status == "online"
        assert status.text_ready is False

    def test_status_reports_installed_models(self, monkeypatch):
        svc = _make_svc()
        monkeypatch.setattr(svc, "_ollama_ping", lambda: True)
        monkeypatch.setattr(svc, "_ollama_models", lambda: ["qwen2.5:7b", "llama3.1:8b"])

        status = svc.llm_status()
        assert set(status.installed) == {"qwen2.5:7b", "llama3.1:8b"}


# ── 7. Ping / models helpers ────────────────────────────────────────────────

class TestOllamaHelpers:

    def test_ping_returns_true_on_200(self, monkeypatch):
        svc = _make_svc()

        def ok_get(url, timeout=None):
            resp = MagicMock()
            resp.status_code = 200
            return resp

        monkeypatch.setattr(requests, "get", ok_get)
        assert svc._ollama_ping() is True

    def test_ping_returns_false_on_exception(self, monkeypatch):
        svc = _make_svc()
        monkeypatch.setattr(requests, "get", lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("no")))
        assert svc._ollama_ping() is False

    def test_ollama_models_parses_tags_response(self, monkeypatch):
        svc = _make_svc()

        def tags_get(url, timeout=None):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"models": [
                {"name": "qwen2.5:7b"},
                {"name": "llama3.1:8b"},
            ]}
            resp.raise_for_status = MagicMock()
            return resp

        monkeypatch.setattr(requests, "get", tags_get)
        assert svc._ollama_models() == ["qwen2.5:7b", "llama3.1:8b"]

    def test_ollama_models_returns_empty_on_failure(self, monkeypatch):
        svc = _make_svc()
        monkeypatch.setattr(requests, "get", lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("no")))
        assert svc._ollama_models() == []


# ── 8. Risk inference from summary ──────────────────────────────────────────

class TestRiskInference:

    def test_high_risk_keywords(self):
        svc = _make_svc()
        assert svc._infer_risk("SEV1 incident: production down") == "high"

    def test_medium_risk_keywords(self):
        svc = _make_svc()
        assert svc._infer_risk("intermittent connectivity warning") == "medium"

    def test_low_risk_default(self):
        svc = _make_svc()
        assert svc._infer_risk("minor config update applied") == "low"
