"""Pydantic schemas for AI provider configuration APIs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AIProviderInfo(BaseModel):
    """Description of a single available AI provider/model."""

    id: str = Field(..., description="Unique identifier, e.g. 'ollama:qwen2.5:7b' or 'openai:gpt-4.1'")
    name: str = Field(..., description="Human-readable display name")
    type: str = Field(..., description="Provider type: 'ollama' or 'openai'")


class AIProvidersResponse(BaseModel):
    """Response listing all available AI providers and the currently active one."""

    providers: List[AIProviderInfo]
    active: AIProviderInfo


class SetProviderRequest(BaseModel):
    """Request to switch the globally active AI provider."""

    provider_id: str = Field(..., min_length=3, description="Provider ID to activate, e.g. 'openai:gpt-4.1'")


class ModuleUsage(BaseModel):
    prompt_tokens:     int = 0
    completion_tokens: int = 0
    total_tokens:      int = 0
    cost_usd:          float = 0.0
    request_count:     int = 0


class AIUsageResponse(BaseModel):
    """Cumulative session-level token usage + pricing info."""

    session_start:    float
    uptime_seconds:   float
    active_model:     str
    active_provider:  str
    modules:          Dict[str, ModuleUsage] = {}
    totals:           ModuleUsage = ModuleUsage()
    pricing:          Dict[str, Dict[str, float]] = {}  # model → {input, output}
