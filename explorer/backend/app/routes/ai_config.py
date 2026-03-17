"""Routes for AI provider configuration management."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.logging import get_logger
from schemas.ai_config import (
    AIProviderInfo,
    AIProvidersResponse,
    AIUsageResponse,
    ModuleUsage,
    SetProviderRequest,
)
from services.ai.pricing import get_all_pricing

logger = get_logger(__name__)
router = APIRouter()

_llm_service = None


def register_singletons(llm_service) -> None:
    global _llm_service
    _llm_service = llm_service


@router.get("/api/v1/ai/providers", tags=["ai-config"], response_model=AIProvidersResponse)
def list_providers() -> AIProvidersResponse:
    """List all available AI providers/models and the currently active one."""
    if _llm_service is None:
        raise HTTPException(503, "LLM service not available.")

    providers = _llm_service.available_providers()
    active = _llm_service.active_provider

    return AIProvidersResponse(
        providers=[AIProviderInfo(**p) for p in providers],
        active=AIProviderInfo(**active),
    )


@router.post("/api/v1/ai/provider", tags=["ai-config"], response_model=AIProvidersResponse)
def set_provider(req: SetProviderRequest) -> AIProvidersResponse:
    """Switch the globally active AI provider/model."""
    if _llm_service is None:
        raise HTTPException(503, "LLM service not available.")

    try:
        _llm_service.set_active_provider(req.provider_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    providers = _llm_service.available_providers()
    active = _llm_service.active_provider

    return AIProvidersResponse(
        providers=[AIProviderInfo(**p) for p in providers],
        active=AIProviderInfo(**active),
    )


@router.get("/api/v1/ai/usage", tags=["ai-config"], response_model=AIUsageResponse)
def get_usage() -> AIUsageResponse:
    """Return cumulative session-level token usage, per-module breakdown, and pricing."""
    if _llm_service is None:
        raise HTTPException(503, "LLM service not available.")

    raw = _llm_service.get_session_usage()
    return AIUsageResponse(
        session_start=raw["session_start"],
        uptime_seconds=raw["uptime_seconds"],
        active_model=raw["active_model"],
        active_provider=raw["active_provider"],
        modules={k: ModuleUsage(**v) for k, v in raw["modules"].items()},
        totals=ModuleUsage(**raw["totals"]),
        pricing=get_all_pricing(),
    )


@router.post("/api/v1/ai/usage/reset", tags=["ai-config"])
def reset_usage():
    """Reset cumulative session counters."""
    if _llm_service is None:
        raise HTTPException(503, "LLM service not available.")
    _llm_service.reset_session_usage()
    return {"status": "ok"}
