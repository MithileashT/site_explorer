"""Pydantic schemas for Slack thread investigation APIs."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class SlackThreadInvestigationRequest(BaseModel):
    """User-provided input to fetch and summarize a Slack thread."""

    slack_thread_url: str = Field(..., min_length=10)
    description: str = Field(..., min_length=5)
    custom_prompt: Optional[str] = None
    site_id: Optional[str] = None
    include_bots: bool = False
    max_messages: int = Field(400, ge=1, le=800)
    model_override: Optional[str] = None  # e.g. "llama3.1:8b" — overrides server default


class SlackThreadAttachment(BaseModel):
    filename: str
    filetype: str  # image | pdf | pptx | text | log | unknown
    extracted: str
    b64_image: Optional[str] = None


class SlackThreadMessage(BaseModel):
    ts: str
    datetime: str
    user: str
    text: str
    log_blocks: List[str] = []
    attachments: List[SlackThreadAttachment] = []


class SlackLLMStatusResponse(BaseModel):
    status: str  # online | offline
    text_model: str
    text_ready: bool
    installed: List[str]
    fix: Optional[str] = None


class SlackThreadInvestigationResponse(BaseModel):
    status: str = "completed"
    workspace: Optional[str] = None
    channel_id: str
    thread_ts: str
    message_count: int
    attachment_count: int = 0
    model_used: str = ""
    participants: List[str] = []
    thread_summary: str
    key_findings: List[str] = []
    recommended_actions: List[str] = []
    risk_level: str = "medium"
    timeline: List[SlackThreadMessage] = []
    attachments: List[SlackThreadAttachment] = []
    raw_analysis: str = ""
