"""Tests for the configurable pricing module and session usage tracking."""
import time
from unittest.mock import MagicMock, patch

import pytest

# ── Pricing module tests ─────────────────────────────────────────────────────

from services.ai.pricing import calculate_cost, get_pricing, get_all_pricing


class TestGetPricing:
    def test_exact_match(self):
        p = get_pricing("gpt-4.1")
        assert p == {"input": 2.00, "output": 8.00}

    def test_prefix_match(self):
        p = get_pricing("gpt-4.1-2025-04-14")
        assert p == {"input": 2.00, "output": 8.00}

    def test_unknown_model_returns_default(self):
        p = get_pricing("some-unknown-model-xyz")
        assert p == {"input": 2.00, "output": 8.00}

    def test_gpt4o_mini(self):
        p = get_pricing("gpt-4o-mini")
        assert p == {"input": 0.15, "output": 0.60}

    def test_gpt4o(self):
        p = get_pricing("gpt-4o")
        assert p == {"input": 2.50, "output": 10.00}

    def test_o4_mini(self):
        p = get_pricing("o4-mini")
        assert p == {"input": 1.10, "output": 4.40}


class TestCalculateCost:
    def test_basic(self):
        cost = calculate_cost("gpt-4.1", prompt_tokens=1000, completion_tokens=500)
        expected = 1000 * 2.00 / 1_000_000 + 500 * 8.00 / 1_000_000
        assert abs(cost - expected) < 1e-9

    def test_zero_tokens(self):
        assert calculate_cost("gpt-4.1", 0, 0) == 0.0

    def test_unknown_model_uses_default(self):
        cost = calculate_cost("mystery-model", 1000, 500)
        expected = 1000 * 2.00 / 1_000_000 + 500 * 8.00 / 1_000_000
        assert abs(cost - expected) < 1e-9


class TestGetAllPricing:
    def test_returns_dict(self):
        p = get_all_pricing()
        assert isinstance(p, dict)
        assert "gpt-4.1" in p
        assert "input" in p["gpt-4.1"]


# ── Session tracking tests ───────────────────────────────────────────────────

@pytest.fixture
def llm_service():
    """Create a real LLMService with mocked clients."""
    with patch("services.ai.llm_service.settings") as mock_settings:
        mock_settings.ollama_base_url = "http://localhost:11434/v1"
        mock_settings.ollama_host = "http://localhost:11434"
        mock_settings.ollama_model = "qwen2.5:7b"
        mock_settings.ollama_num_ctx = 8192
        mock_settings.openai_api_key = "test-key"
        mock_settings.openai_model = "gpt-4.1"

        with patch("services.ai.llm_service.OpenAI"):
            from services.ai.llm_service import LLMService
            svc = LLMService()
            return svc


class TestSessionTracking:
    def test_initial_state(self, llm_service):
        usage = llm_service.get_session_usage()
        assert usage["modules"] == {}
        assert usage["totals"]["cost_usd"] == 0.0
        assert usage["totals"]["request_count"] == 0
        assert usage["active_model"] == "gpt-4.1"

    def test_accumulate_session(self, llm_service):
        llm_service._accumulate_session("log_analyser", {
            "prompt_tokens": 1000,
            "completion_tokens": 200,
            "total_tokens": 1200,
            "cost_usd": 0.0036,
        })
        usage = llm_service.get_session_usage()
        assert usage["modules"]["log_analyser"]["request_count"] == 1
        assert usage["modules"]["log_analyser"]["prompt_tokens"] == 1000
        assert usage["totals"]["cost_usd"] == 0.0036

    def test_multiple_calls_accumulate(self, llm_service):
        for _ in range(3):
            llm_service._accumulate_session("bag_analyser", {
                "prompt_tokens": 500,
                "completion_tokens": 100,
                "total_tokens": 600,
                "cost_usd": 0.001,
            })
        usage = llm_service.get_session_usage()
        assert usage["modules"]["bag_analyser"]["request_count"] == 3
        assert usage["modules"]["bag_analyser"]["prompt_tokens"] == 1500
        assert abs(usage["totals"]["cost_usd"] - 0.003) < 1e-9

    def test_module_isolation(self, llm_service):
        llm_service._accumulate_session("log_analyser", {
            "prompt_tokens": 1000, "completion_tokens": 200,
            "total_tokens": 1200, "cost_usd": 0.003,
        })
        llm_service._accumulate_session("slack_investigation", {
            "prompt_tokens": 2000, "completion_tokens": 400,
            "total_tokens": 2400, "cost_usd": 0.007,
        })
        usage = llm_service.get_session_usage()
        assert len(usage["modules"]) == 2
        assert usage["modules"]["log_analyser"]["prompt_tokens"] == 1000
        assert usage["modules"]["slack_investigation"]["prompt_tokens"] == 2000
        assert abs(usage["totals"]["cost_usd"] - 0.01) < 1e-9
        assert usage["totals"]["request_count"] == 2

    def test_reset_session(self, llm_service):
        llm_service._accumulate_session("log_analyser", {
            "prompt_tokens": 1000, "completion_tokens": 200,
            "total_tokens": 1200, "cost_usd": 0.003,
        })
        llm_service.reset_session_usage()
        usage = llm_service.get_session_usage()
        assert usage["modules"] == {}
        assert usage["totals"]["cost_usd"] == 0.0

    def test_uptime_seconds(self, llm_service):
        usage = llm_service.get_session_usage()
        assert usage["uptime_seconds"] >= 0
        assert usage["session_start"] > 0


# ── Usage endpoint tests ─────────────────────────────────────────────────────

class TestUsageEndpoint:
    def test_get_usage_returns_200(self, llm_service):
        from app.routes.ai_config import router, register_singletons
        from fastapi.testclient import TestClient
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        register_singletons(llm_service)

        client = TestClient(app)
        resp = client.get("/api/v1/ai/usage")
        assert resp.status_code == 200
        body = resp.json()
        assert "totals" in body
        assert "modules" in body
        assert "pricing" in body
        assert "gpt-4.1" in body["pricing"]

    def test_reset_usage(self, llm_service):
        from app.routes.ai_config import router, register_singletons
        from fastapi.testclient import TestClient
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        register_singletons(llm_service)

        # Accumulate some usage first
        llm_service._accumulate_session("log_analyser", {
            "prompt_tokens": 500, "completion_tokens": 100,
            "total_tokens": 600, "cost_usd": 0.001,
        })

        client = TestClient(app)

        # Verify usage exists
        resp = client.get("/api/v1/ai/usage")
        assert resp.json()["totals"]["request_count"] == 1

        # Reset
        resp = client.post("/api/v1/ai/usage/reset")
        assert resp.status_code == 200

        # Verify cleared
        resp = client.get("/api/v1/ai/usage")
        assert resp.json()["totals"]["request_count"] == 0
