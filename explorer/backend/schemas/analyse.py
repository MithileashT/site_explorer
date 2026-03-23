"""Pydantic schemas for the combined log + Slack AI analysis endpoint."""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class LogEntry(BaseModel):
    timestamp_ms: int
    level: str = ""
    hostname: str = ""
    deployment: str = ""
    message: str = ""
    labels: Dict[str, str] = {}


class AnalyseRequest(BaseModel):
    """Payload for POST /api/v1/investigate/analyse."""
    logs: List[LogEntry] = Field(default_factory=list)
    time_from: Optional[str] = None
    time_to: Optional[str] = None
    # Analysis-specific time range (epoch ms) — filters logs before LLM processing
    analysis_from_ms: Optional[int] = None
    analysis_to_ms: Optional[int] = None
    site_id: Optional[str] = None
    env: Optional[str] = None
    hostname: Optional[str] = None
    deployment: Optional[str] = None
    slack_thread_url: Optional[str] = None
    issue_description: str = Field(..., min_length=5)


class AnalyseResponse(BaseModel):
    model_used: str
    has_images: bool = False
    slack_messages: int = 0
    log_count: int = 0
    summary: str
    partial_analysis: bool = False
    chunks_analysed: int = 1
    estimated_tokens: int = 0  # estimated prompt tokens sent to LLM
    # Actual tokens reported back by the LLM API (0 when using Ollama)
    actual_prompt_tokens:     int = 0
    actual_completion_tokens: int = 0
    actual_total_tokens:      int = 0
    cost_usd:                 float = 0.0
