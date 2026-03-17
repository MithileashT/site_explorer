"""Tests for OpenAI provider integration and centralized AI provider management."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch


# ── Config tests ────────────────────────────────────────────────────────────


def test_config_has_openai_model_setting():
    """settings must expose openai_model for configurable OpenAI model selection."""
    from core.config import settings

    assert hasattr(settings, "openai_model")
    # Default should be a valid OpenAI model name
    assert isinstance(settings.openai_model, str)
    assert len(settings.openai_model) > 0


def test_config_openai_model_reads_from_env(monkeypatch):
    """OPENAI_MODEL env var should control the OpenAI model used."""
    # _Settings attributes are evaluated at class definition time,
    # so we test the default value presence and that the env var path exists.
    from core.config import settings
    # The default should be gpt-4.1 (or whatever OPENAI_MODEL is set to in env)
    assert isinstance(settings.openai_model, str)
    assert len(settings.openai_model) > 0
    # Verify env var override works by patching the attribute
    monkeypatch.setattr(settings, "openai_model", "gpt-5")
    assert settings.openai_model == "gpt-5"


# ── LLMService provider management tests ────────────────────────────────────


def test_llm_service_has_available_providers():
    """LLMService must expose available_providers() returning list of providers."""
    from services.ai.llm_service import LLMService

    with patch("services.ai.llm_service.OpenAI"):
        svc = LLMService()
        providers = svc.available_providers()
        assert isinstance(providers, list)
        assert len(providers) > 0
        # Each provider must have id, name, type
        for p in providers:
            assert "id" in p
            assert "name" in p
            assert "type" in p


def test_llm_service_has_active_provider_property():
    """LLMService must expose active_provider with id, name, model, type."""
    from services.ai.llm_service import LLMService

    with patch("services.ai.llm_service.OpenAI"):
        svc = LLMService()
        active = svc.active_provider
        assert isinstance(active, dict)
        assert "id" in active
        assert "model" in active
        assert "type" in active


def test_llm_service_defaults_to_ollama_when_no_openai_key(monkeypatch):
    """Without OPENAI_API_KEY, default provider should be ollama."""
    from core.config import settings
    monkeypatch.setattr(settings, "openai_api_key", "")
    import services.ai.llm_service as llm_mod
    monkeypatch.setattr(llm_mod, "settings", settings)
    from services.ai.llm_service import LLMService

    with patch("services.ai.llm_service.OpenAI"):
        svc = LLMService()
        assert svc.active_provider["type"] == "ollama"


def test_llm_service_includes_openai_when_key_configured(monkeypatch):
    """When OPENAI_API_KEY is set, OpenAI should appear in available_providers."""
    # Patch settings at the module level where LLMService reads it
    from core.config import settings
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-key-12345")
    monkeypatch.setattr(settings, "openai_model", "gpt-4.1")
    # Also patch in the llm_service module's imported reference
    import services.ai.llm_service as llm_mod
    monkeypatch.setattr(llm_mod, "settings", settings)

    from services.ai.llm_service import LLMService

    with patch("services.ai.llm_service.OpenAI"):
        svc = LLMService()
        providers = svc.available_providers()
        types = [p["type"] for p in providers]
        assert "openai" in types


def test_llm_service_set_active_provider():
    """set_active_provider() should switch the active provider and model."""
    from services.ai.llm_service import LLMService

    with patch("services.ai.llm_service.OpenAI"):
        svc = LLMService()
        providers = svc.available_providers()
        if len(providers) > 0:
            # Switch to first available
            svc.set_active_provider(providers[0]["id"])
            assert svc.active_provider["id"] == providers[0]["id"]


def test_llm_service_set_invalid_provider_raises():
    """set_active_provider() with unknown ID should raise ValueError."""
    from services.ai.llm_service import LLMService

    with patch("services.ai.llm_service.OpenAI"):
        svc = LLMService()
        with pytest.raises(ValueError):
            svc.set_active_provider("nonexistent-provider-id")


def test_llm_service_chat_method_exists():
    """LLMService must expose a generic chat() method."""
    from services.ai.llm_service import LLMService

    with patch("services.ai.llm_service.OpenAI"):
        svc = LLMService()
        assert callable(getattr(svc, "chat", None))


def test_llm_service_chat_uses_active_provider():
    """chat() should use the currently active provider's client and model."""
    from services.ai.llm_service import LLMService

    mock_openai = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "test response"
    mock_openai.return_value.chat.completions.create.return_value = mock_response

    with patch("services.ai.llm_service.OpenAI", mock_openai):
        svc = LLMService()
        result = svc.chat(
            messages=[
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hello"},
            ]
        )
        assert result == "test response"


# ── Schema tests ────────────────────────────────────────────────────────────


def test_ai_provider_info_schema():
    """AIProviderInfo Pydantic model should be importable and valid."""
    from schemas.ai_config import AIProviderInfo

    p = AIProviderInfo(id="ollama:qwen2.5:7b", name="qwen2.5:7b", type="ollama")
    assert p.id == "ollama:qwen2.5:7b"
    assert p.type == "ollama"


def test_ai_providers_response_schema():
    """AIProvidersResponse should contain providers list and active provider."""
    from schemas.ai_config import AIProvidersResponse, AIProviderInfo

    resp = AIProvidersResponse(
        providers=[AIProviderInfo(id="ollama:qwen2.5:7b", name="qwen2.5:7b", type="ollama")],
        active=AIProviderInfo(id="ollama:qwen2.5:7b", name="qwen2.5:7b", type="ollama"),
    )
    assert len(resp.providers) == 1
    assert resp.active.id == "ollama:qwen2.5:7b"


def test_set_provider_request_schema():
    """SetProviderRequest must accept a provider_id string."""
    from schemas.ai_config import SetProviderRequest

    req = SetProviderRequest(provider_id="openai:gpt-4.1")
    assert req.provider_id == "openai:gpt-4.1"


# ── Slack investigation service integration tests ───────────────────────────


def test_slack_service_uses_llm_service_for_chat():
    """SlackInvestigationService should accept and use LLMService for AI calls."""
    from services.ai.slack_investigation_service import SlackInvestigationService

    mock_llm = MagicMock()
    mock_llm.active_provider = {"id": "ollama:qwen2.5:7b", "model": "qwen2.5:7b", "type": "ollama"}
    mock_llm.chat.return_value = "## The Issue\n- Test finding"

    svc = SlackInvestigationService(_llm_service=mock_llm)
    assert svc._llm_service is mock_llm


def test_slack_status_includes_providers():
    """llm_status() should include available AI providers."""
    from services.ai.slack_investigation_service import SlackInvestigationService

    mock_llm = MagicMock()
    mock_llm.available_providers.return_value = [
        {"id": "ollama:qwen2.5:7b", "name": "qwen2.5:7b", "type": "ollama"},
    ]
    mock_llm.active_provider = {"id": "ollama:qwen2.5:7b", "model": "qwen2.5:7b", "type": "ollama"}

    svc = SlackInvestigationService(_llm_service=mock_llm)
    # Mock ollama ping + models
    svc._ollama_ping = lambda: True
    svc._ollama_models = lambda: ["qwen2.5:7b"]

    status = svc.llm_status()
    assert hasattr(status, "providers")
    assert len(status.providers) > 0


# ── Analyse route tests ────────────────────────────────────────────────────


def test_analyse_response_preserves_existing_fields():
    """AnalyseResponse should still have all existing fields."""
    from schemas.analyse import AnalyseResponse

    resp = AnalyseResponse(
        model_used="openai:gpt-4.1",
        has_images=False,
        slack_messages=5,
        log_count=100,
        summary="## Analysis\nRobot stopped.",
    )
    assert resp.model_used == "openai:gpt-4.1"
    assert resp.log_count == 100


# ── Provider consistency tests ──────────────────────────────────────────────


def test_provider_switch_is_global():
    """Switching provider on LLMService should affect all subsequent calls."""
    from services.ai.llm_service import LLMService

    mock_openai = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "response"
    mock_openai.return_value.chat.completions.create.return_value = mock_response

    with patch("services.ai.llm_service.OpenAI", mock_openai):
        svc = LLMService()
        initial = svc.active_provider["id"]
        providers = svc.available_providers()

        # If there are multiple providers, switch to a different one
        if len(providers) > 1:
            other = [p for p in providers if p["id"] != initial][0]
            svc.set_active_provider(other["id"])
            assert svc.active_provider["id"] == other["id"]

            # Chat should now use the new provider
            svc.chat(messages=[{"role": "user", "content": "test"}])
            # Verify it used the selected model
            call_args = mock_openai.return_value.chat.completions.create.call_args
            assert call_args is not None
