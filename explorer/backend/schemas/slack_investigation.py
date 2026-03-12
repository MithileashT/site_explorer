"""Pydantic schemas for Slack thread investigation APIs."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class SlackThreadInvestigationRequest(BaseModel):
    """User-provided input to fetch and summarize a Slack thread."""

    slack_thread_url: str = Field(..., min_length=10)
    description: str = Field(..., min_length=5)
    site_id: Optional[str] = None
    hostname: Optional[str] = None
    include_bots: bool = False
    max_messages: int = Field(200, ge=1, le=500)


class SlackThreadMessage(BaseModel):
    ts: str
    datetime: str
    user: str
    text: str


class SlackThreadInvestigationResponse(BaseModel):
    status: str = "completed"
    workspace: Optional[str] = None
    channel_id: str
    thread_ts: str
    message_count: int
    participants: List[str] = []
    thread_summary: str
    key_findings: List[str] = []
    recommended_actions: List[str] = []
    risk_level: str = "medium"
    timeline: List[SlackThreadMessage] = []
    raw_analysis: str = ""
