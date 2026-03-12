"""Slack thread fetch + LLM summarization service for investigations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Dict, List

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from core.config import settings
from core.logging import get_logger
from schemas.slack_investigation import (
    SlackThreadInvestigationRequest,
    SlackThreadInvestigationResponse,
    SlackThreadMessage,
)
from services.ai.llm_service import LLMService

logger = get_logger(__name__)

_SUMMARY = "###THREAD_SUMMARY###"
_FINDINGS = "###KEY_FINDINGS###"
_ACTIONS = "###RECOMMENDED_ACTIONS###"
_RISK = "###RISK_LEVEL###"


@dataclass
class ParsedSlackThreadRef:
    workspace: str
    channel_id: str
    thread_ts: str


def _p_timestamp_to_ts(value: str) -> str:
    if not value.isdigit() or len(value) < 7:
        raise ValueError("Invalid Slack message timestamp format.")
    return f"{value[:-6]}.{value[-6:]}"


def parse_slack_thread_url(url: str) -> ParsedSlackThreadRef:
    """Parse a Slack thread URL into workspace/channel/thread identifiers."""
    match = re.search(r"https://([^.]+)\.slack\.com/archives/([A-Z0-9]+)/p(\d+)", url)
    if not match:
        raise ValueError("Slack thread URL is invalid. Expected .../archives/<CHANNEL>/p<TIMESTAMP>.")

    workspace, channel_id, p_ts = match.groups()
    thread_ts = _p_timestamp_to_ts(p_ts)
    return ParsedSlackThreadRef(workspace=workspace, channel_id=channel_id, thread_ts=thread_ts)


def _parse_section(raw: str, token: str, next_token: str | None) -> str:
    start = raw.find(token)
    if start == -1:
        return ""
    content_start = start + len(token)
    if next_token:
        end = raw.find(next_token, content_start)
        if end != -1:
            return raw[content_start:end].strip()
    return raw[content_start:].strip()


def _as_bullets(text: str) -> List[str]:
    out: List[str] = []
    for line in text.splitlines():
        cleaned = re.sub(r"^[-*\d.\s]+", "", line).strip()
        if cleaned:
            out.append(cleaned)
    return out


class SlackInvestigationService:
    def __init__(self, llm: LLMService) -> None:
        self.llm = llm
        self.client = WebClient(token=settings.slack_bot_token) if settings.slack_bot_token else None
        self._user_cache: Dict[str, str] = {}

    def _require_client(self) -> WebClient:
        if not self.client:
            raise RuntimeError("SLACK_BOT_TOKEN is not configured on the backend.")
        return self.client

    def _resolve_user(self, user_id: str | None) -> str:
        if not user_id:
            return "unknown"
        if user_id in self._user_cache:
            return self._user_cache[user_id]

        client = self._require_client()
        try:
            data = client.users_info(user=user_id)
            profile = data.get("user", {})
            display = profile.get("real_name") or profile.get("name") or user_id
        except SlackApiError:
            display = user_id
        self._user_cache[user_id] = display
        return display

    def _fetch_thread_messages(self, ref: ParsedSlackThreadRef, include_bots: bool, max_messages: int) -> List[SlackThreadMessage]:
        client = self._require_client()
        cursor = None
        collected: List[SlackThreadMessage] = []

        while len(collected) < max_messages:
            limit = min(200, max_messages - len(collected))
            try:
                resp = client.conversations_replies(
                    channel=ref.channel_id,
                    ts=ref.thread_ts,
                    limit=limit,
                    cursor=cursor,
                    inclusive=True,
                )
            except SlackApiError as exc:
                raise RuntimeError(f"Slack API error: {exc.response.get('error', 'unknown_error')}") from exc

            for msg in resp.get("messages", []):
                text = (msg.get("text") or "").strip()
                if not text:
                    continue
                if not include_bots and (msg.get("subtype") == "bot_message" or msg.get("bot_id")):
                    continue

                ts = str(msg.get("ts", ""))
                try:
                    dt = datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
                except Exception:
                    dt = ""

                collected.append(
                    SlackThreadMessage(
                        ts=ts,
                        datetime=dt,
                        user=self._resolve_user(msg.get("user")),
                        text=text,
                    )
                )
                if len(collected) >= max_messages:
                    break

            cursor = resp.get("response_metadata", {}).get("next_cursor") or None
            if not cursor:
                break

        return collected

    def _summarize(self, req: SlackThreadInvestigationRequest, messages: List[SlackThreadMessage]) -> tuple[str, List[str], List[str], str, str]:
        if not messages:
            return (
                "No Slack messages were returned for this thread.",
                ["Thread is empty or inaccessible with current token/scopes."],
                ["Verify channel access for the bot and confirm thread URL."],
                "medium",
                "",
            )

        rendered = "\n".join(
            f"[{m.datetime}] {m.user}: {m.text[:700]}" for m in messages[:120]
        )
        context_bits = [
            f"Description: {req.description}",
            f"Site: {req.site_id or 'N/A'}",
            f"Hostname: {req.hostname or 'N/A'}",
            f"Message count: {len(messages)}",
        ]

        prompt = (
            "You are an AMR incident investigator. Read the Slack thread and generate a concise structured output.\n"
            f"Return EXACTLY these sections in order: {_SUMMARY}, {_FINDINGS}, {_ACTIONS}, {_RISK}.\n"
            "In key findings and actions, use bullet lines. Risk level must be one word: low, medium, or high.\n\n"
            + "\n".join(context_bits)
            + "\n\nTHREAD LOGS:\n"
            + rendered
        )

        raw = self.llm.generate_investigation_summary(prompt)
        summary = _parse_section(raw, _SUMMARY, _FINDINGS)
        findings = _as_bullets(_parse_section(raw, _FINDINGS, _ACTIONS))
        actions = _as_bullets(_parse_section(raw, _ACTIONS, _RISK))
        risk = _parse_section(raw, _RISK, None).lower().strip() or "medium"
        if risk not in {"low", "medium", "high"}:
            risk = "medium"

        if not summary:
            summary = "Thread reviewed. See key findings and recommended actions for investigation-ready context."
        if not findings:
            findings = ["Potential issue indicators found in thread discussion."]
        if not actions:
            actions = ["Validate latest operator-reported errors against robot telemetry."]

        return summary, findings, actions, risk, raw

    def investigate(self, req: SlackThreadInvestigationRequest) -> SlackThreadInvestigationResponse:
        ref = parse_slack_thread_url(req.slack_thread_url)
        messages = self._fetch_thread_messages(ref, req.include_bots, req.max_messages)
        summary, findings, actions, risk, raw = self._summarize(req, messages)
        participants = sorted({m.user for m in messages if m.user})

        return SlackThreadInvestigationResponse(
            workspace=ref.workspace,
            channel_id=ref.channel_id,
            thread_ts=ref.thread_ts,
            message_count=len(messages),
            participants=participants,
            thread_summary=summary,
            key_findings=findings,
            recommended_actions=actions,
            risk_level=risk,
            timeline=messages,
            raw_analysis=raw,
        )
