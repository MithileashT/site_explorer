"""Slack thread reader + local Ollama summarization service."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import re
import threading
import time
from typing import Dict, Generator, List, Tuple

import requests
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from core.config import resolve_slack_bot_token, settings
from core.logging import get_logger
from services.ai.prompts import load_prompt
from schemas.slack_investigation import (
    SlackLLMStatusResponse,
    SlackThreadAttachment,
    SlackThreadInvestigationRequest,
    SlackThreadInvestigationResponse,
    SlackThreadMessage,
)

logger = get_logger(__name__)

_URL_RE = re.compile(r"https?://\S+")
_MAX_FETCH_MESSAGES = 200  # hard cap Slack thread messages fetched for summary
_WARM_JOIN_TIMEOUT_SECONDS = 3
_SUMMARY_CACHE_MAX = 64  # max cached summaries (LRU eviction)
_SUMMARY_CACHE_SCHEMA_VERSION = "v3"  # bump when response parsing/format assumptions change


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
    """Parse Slack permalink: .../archives/<CHANNEL>/p<TIMESTAMP>."""
    match = re.search(r"https://([^.]+)\.slack\.com/archives/([A-Z0-9]+)/p(\d+)", url)
    if not match:
        raise ValueError("Slack thread URL is invalid. Expected .../archives/<CHANNEL>/p<TIMESTAMP>.")
    workspace, channel_id, p_ts = match.groups()
    return ParsedSlackThreadRef(
        workspace=workspace,
        channel_id=channel_id,
        thread_ts=_p_timestamp_to_ts(p_ts),
    )


def _extract_log_blocks(text: str) -> Tuple[str, List[str]]:
    blocks: List[str] = []
    triple = re.findall(r"```(.*?)```", text or "", re.DOTALL)
    blocks.extend(b.strip() for b in triple if b.strip())
    clean = re.sub(r"```.*?```", "[log block]", text or "", flags=re.DOTALL)

    single = re.findall(r"`([^`]{40,})`", clean)
    blocks.extend(b.strip() for b in single if b.strip())
    clean = re.sub(r"`[^`]{40,}`", "[log snippet]", clean)
    return clean.strip(), blocks


def _as_bullets(text: str) -> List[str]:
    out: List[str] = []
    for line in text.splitlines():
        cleaned = re.sub(r"^[-*\d.\s]+", "", line).strip()
        if cleaned:
            out.append(cleaned)
    return out


def _split_markdown_sections(markdown_text: str) -> Dict[str, str]:
    sections: Dict[str, List[str]] = {}
    current = ""
    for line in markdown_text.splitlines():
        stripped = line.strip()
        # Match heading levels # through ####
        heading_match = re.match(r"^#{1,4}\s+(.+?)\s*$", stripped)
        if not heading_match:
            # Also match bold-only lines as headings (e.g. **The Issue**)
            heading_match = re.match(r"^\*\*(.+?)\*\*\s*$", stripped)
        if heading_match:
            # Normalize: lowercase, strip trailing colons/punctuation
            current = re.sub(r"[:\-]+$", "", heading_match.group(1).strip()).strip().lower()
            sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def _find_section(sections: Dict[str, str], *candidates: str) -> str:
    """Fuzzy section lookup: try exact match, then substring containment."""
    for key in candidates:
        if key in sections:
            return sections[key].strip()
    # Fallback: check if any section key contains a candidate word
    for key in candidates:
        for sk, sv in sections.items():
            if key in sk or sk in key:
                return sv.strip()
    return ""


class SlackInvestigationService:
    def __init__(self, _llm_service=None) -> None:
        self._llm_service = _llm_service
        self.client: WebClient | None = None
        self._client_token = ""
        self._user_cache: Dict[str, str] = {}
        self._models_cache: List[str] | None = None
        self.ollama_host = settings.ollama_host.rstrip("/")
        self.text_model = settings.ollama_text_model
        # LRU summary cache — keyed by (thread_url, model, description) hash
        self._summary_cache: OrderedDict[str, Tuple[str, str]] = OrderedDict()

    def _slack_token(self) -> str:
        token = resolve_slack_bot_token()
        if token:
            return token
        raise RuntimeError(
            "SLACK_BOT_TOKEN is not configured on the backend. "
            "Set SLACK_BOT_TOKEN (or SLACK_TOKEN) in backend/.env. "
            "If using Docker, recreate backend: docker compose up -d --force-recreate backend"
        )

    def _require_client(self) -> WebClient:
        token = self._slack_token()
        if self.client is None or self._client_token != token:
            self.client = WebClient(token=token)
            self._client_token = token
        return self.client

    def _ollama_ping(self) -> bool:
        try:
            resp = requests.get(f"{self.ollama_host}/api/tags", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def _ollama_models(self) -> List[str]:
        if self._models_cache is not None:
            return self._models_cache
        try:
            resp = requests.get(f"{self.ollama_host}/api/tags", timeout=5)
            resp.raise_for_status()
            self._models_cache = [m.get("name", "") for m in resp.json().get("models", [])]
            return self._models_cache
        except Exception:
            return []

    def llm_status(self) -> SlackLLMStatusResponse:
        self._models_cache = None  # always fetch fresh for status check

        # Gather providers from LLMService if available
        providers: List[Dict] = []
        active_provider: Dict | None = None
        if self._llm_service and hasattr(self._llm_service, "available_providers"):
            providers = self._llm_service.available_providers()
            active_provider = self._llm_service.active_provider

        if not self._ollama_ping():
            # Ollama offline — still show OpenAI providers if available
            openai_providers = [p for p in providers if p.get("type") == "openai"]
            status = "offline" if not openai_providers else "online"
            fix_msg = (
                f"Ollama is not running at {self.ollama_host}. Run: ollama serve"
                if not openai_providers else None
            )
            return SlackLLMStatusResponse(
                status=status,
                text_model=self.text_model,
                text_ready=bool(openai_providers),
                installed=[],
                fix=fix_msg,
                providers=providers,
                active_provider=active_provider,
            )

        installed = self._ollama_models()
        text_prefix = self.text_model.split(":", 1)[0]
        return SlackLLMStatusResponse(
            status="online",
            text_model=self.text_model,
            text_ready=any(text_prefix in name for name in installed),
            installed=installed,
            providers=providers,
            active_provider=active_provider,
        )

    def _resolve_user(self, user_id: str | None) -> str:
        if not user_id:
            return "unknown"
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        if user_id.startswith("B"):
            self._user_cache[user_id] = f"bot:{user_id}"
            return self._user_cache[user_id]

        client = self._require_client()
        try:
            data = client.users_info(user=user_id)
            user = data.get("user", {})
            profile = user.get("profile", {})
            display = profile.get("display_name") or profile.get("real_name") or user.get("name") or user_id
        except SlackApiError:
            display = user_id
        self._user_cache[user_id] = display
        return display

    def _ensure_in_channel(self, client: WebClient, channel_id: str) -> None:
        """Join a public channel if the bot is not already a member."""
        try:
            channel_info = client.conversations_info(channel=channel_id)
            is_member = (channel_info.get("channel") or {}).get("is_member", False)
            if is_member:
                return
        except SlackApiError:
            pass  # proceed to join attempt

        try:
            client.conversations_join(channel=channel_id)
            logger.info("Auto-joined channel %s to fetch thread.", channel_id)
        except SlackApiError as exc:
            join_err = exc.response.get("error", "unknown")
            if join_err == "method_not_supported_for_channel_type":
                raise ValueError(
                    f"The bot is not in channel '{channel_id}' (private channel). "
                    "Invite the bot manually: /invite @<bot_name>"
                ) from exc
            if join_err == "is_archived":
                raise ValueError(
                    f"Channel '{channel_id}' is archived and cannot be joined."
                ) from exc
            raise ValueError(
                f"Could not join channel '{channel_id}' ({join_err}). "
                "Invite the bot to the channel first."
            ) from exc

    def _fetch_thread_messages(
        self,
        ref: ParsedSlackThreadRef,
        include_bots: bool,
        max_messages: int,
    ) -> Tuple[List[SlackThreadMessage], List[SlackThreadAttachment]]:
        client = self._require_client()
        cursor = None
        _auto_joined = False
        t_phase_start = time.perf_counter()

        # ── Phase 1: Fetch raw Slack messages (no attachment download yet) ────
        raw_items: List[Dict] = []  # list of raw Slack message dicts
        while len(raw_items) < max_messages:
            limit = min(200, max_messages - len(raw_items))
            try:
                resp = client.conversations_replies(
                    channel=ref.channel_id,
                    ts=ref.thread_ts,
                    limit=limit,
                    cursor=cursor,
                    inclusive=True,
                )
            except SlackApiError as exc:
                err = exc.response.get("error", "unknown_error")
                if err == "not_in_channel" and not _auto_joined:
                    self._ensure_in_channel(client, ref.channel_id)
                    _auto_joined = True
                    continue  # retry with the joined channel
                if err == "not_in_channel":
                    raise ValueError(
                        f"Bot is not in channel '{ref.channel_id}'. "
                        "Invite the bot to the channel first."
                    ) from exc
                if err == "channel_not_found":
                    raise ValueError("Channel not found. Check the Slack thread URL.") from exc
                if err == "thread_not_found":
                    raise ValueError("Thread not found. Check the Slack thread URL.") from exc
                if err == "missing_scope":
                    raise RuntimeError(
                        "Missing Slack API scopes. Ensure the bot token has "
                        "'channels:history', 'groups:history', and 'channels:join' scopes."
                    ) from exc
                if err == "invalid_auth":
                    raise RuntimeError(
                        "Invalid Slack token. Check SLACK_BOT_TOKEN in backend/.env and recreate the backend container."
                    ) from exc
                raise RuntimeError(f"Slack API error: {err}") from exc

            for raw in resp.get("messages", []):
                if not include_bots and (raw.get("subtype") == "bot_message" or raw.get("bot_id")):
                    continue
                raw_items.append(raw)
                if len(raw_items) >= max_messages:
                    break

            cursor = (resp.get("response_metadata") or {}).get("next_cursor") or None
            if not cursor:
                break

        t_messages = time.perf_counter()
        logger.info("Fetch phase 1 (messages): %.1fs (%d messages)",
                     t_messages - t_phase_start, len(raw_items))

        # ── Phase 2: Batch-resolve unique user IDs (parallel) ─────────────────
        unique_users = {
            raw.get("user") or raw.get("bot_id")
            for raw in raw_items
            if raw.get("user") or raw.get("bot_id")
        }
        users_to_resolve = [
            uid for uid in unique_users
            if uid and uid not in self._user_cache
        ]
        if users_to_resolve:
            with ThreadPoolExecutor(max_workers=min(8, len(users_to_resolve))) as pool:
                futures = {pool.submit(self._resolve_user, uid): uid for uid in users_to_resolve}
                for fut in as_completed(futures):
                    try:
                        fut.result()
                    except Exception:
                        pass  # _resolve_user already caches fallback

        t_users = time.perf_counter()
        logger.info("Fetch phase 2 (user resolve): %.1fs (%d users)",
                     t_users - t_messages, len(users_to_resolve))

        # ── Phase 3: Assemble messages + file mentions (no downloads) ─────────
        messages: List[SlackThreadMessage] = []
        file_mentions: List[SlackThreadAttachment] = []
        for msg_idx, raw in enumerate(raw_items):
            raw_text = raw.get("text") or ""
            clean_text, log_blocks = _extract_log_blocks(raw_text)

            message_attachments: List[SlackThreadAttachment] = []
            for slack_file in raw.get("files", []) or []:
                filename = slack_file.get("name", "unknown")
                filetype = slack_file.get("filetype") or slack_file.get("mimetype") or "unknown"
                mention = SlackThreadAttachment(
                    filename=filename,
                    filetype=str(filetype),
                    extracted=f"[File shared: {filename}]",
                )
                message_attachments.append(mention)
                file_mentions.append(mention)

            if not clean_text and not log_blocks and not message_attachments:
                continue

            ts = str(raw.get("ts", ""))
            try:
                dt = datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            except Exception:
                dt = ts

            user_id = raw.get("user") or raw.get("bot_id")
            messages.append(
                SlackThreadMessage(
                    ts=ts,
                    datetime=dt,
                    user=self._resolve_user(user_id),
                    text=clean_text,
                    log_blocks=log_blocks,
                    attachments=message_attachments,
                )
            )
        logger.info("Fetch phase 3 (assembly): %.1fs (%d messages, %d file mentions)",
                    time.perf_counter() - t_users, len(messages), len(file_mentions))
        return messages, file_mentions

    def _ollama_chat(self, chat_messages: List[Dict], model: str, max_tokens: int = 3500) -> str:
        # If LLMService is available, delegate to it for provider-aware routing
        if self._llm_service and hasattr(self._llm_service, "chat"):
            return self._llm_service.chat(
                messages=chat_messages,
                max_tokens=max_tokens,
                temperature=0.2,
                model_override=model if model != self._llm_service.model else None,
                module="slack_investigation",
            )

        # Fallback: direct Ollama API call (backward compatibility)
        payload = {
            "model": model,
            "messages": chat_messages,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_ctx": settings.ollama_num_ctx,
            },
        }
        try:
            resp = requests.post(f"{self.ollama_host}/api/chat", json=payload, timeout=600)
            resp.raise_for_status()
            return (resp.json().get("message") or {}).get("content", "").strip()
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError(f"Ollama is not running at {self.ollama_host}. Start it with: ollama serve") from exc
        except Exception as exc:
            logger.error("Ollama chat error (model=%s): %s", model, exc)
            raise RuntimeError(f"Local LLM error: {exc}") from exc

    def _generate_summary(
        self,
        req: SlackThreadInvestigationRequest,
        messages: List[SlackThreadMessage],
        attachments: List[SlackThreadAttachment],
    ) -> Tuple[str, str]:
        # Determine model: use request override, active provider, or default
        model = req.model_override or ""

        # If LLMService is available and no override specified, use active provider
        if self._llm_service and hasattr(self._llm_service, "active_provider") and not model:
            active = self._llm_service.active_provider
            model = f"{active['type']}:{active['model']}"

        # If still no model, use the default text model
        if not model:
            model = self.text_model

        # ── Cache lookup ──────────────────────────────────────────────────
        cache_key = self._build_cache_key(req, messages, model)
        if cache_key in self._summary_cache:
            self._summary_cache.move_to_end(cache_key)
            logger.info("Summary cache HIT for thread=%s model=%s", req.slack_thread_url[:60], model)
            return self._summary_cache[cache_key]

        # For Ollama models (without provider prefix), validate installation
        is_remote = model.startswith("openai:") or model.startswith("gemini:")
        if not is_remote:
            plain_model = model.removeprefix("ollama:")
            installed = self._ollama_models()
            model_prefix = plain_model.split(":", 1)[0]
            if not any(model_prefix in name for name in installed):
                if any(self.text_model.split(":", 1)[0] in name for name in installed):
                    logger.warning(
                        "Model %s not installed, falling back to text model %s",
                        plain_model, self.text_model,
                    )
                    plain_model = self.text_model
                else:
                    raise RuntimeError(
                        f"Model '{plain_model}' is not installed in Ollama. "
                        f"Pull it with: ollama pull {plain_model}"
                    )
            model = plain_model

        _system, chat, strategy = self._build_prompt_messages(req, messages, model)
        max_tok = strategy["max_tokens"]
        summary = self._ollama_chat(chat, model, max_tokens=max_tok)

        # ── Store in cache ────────────────────────────────────────────────
        self._summary_cache[cache_key] = (summary, model)
        if len(self._summary_cache) > _SUMMARY_CACHE_MAX:
            self._summary_cache.popitem(last=False)  # evict oldest

        return summary, model

    def _build_cache_key(
        self,
        req: SlackThreadInvestigationRequest,
        messages: List[SlackThreadMessage],
        model: str,
    ) -> str:
        """Deterministic cache key including prompt/parser signatures.

        Including prompt/schema signatures ensures summary changes are reflected
        immediately after prompt or parser updates.
        """
        try:
            prompt_signature = hashlib.sha256(load_prompt("issue_summary").encode("utf-8")).hexdigest()[:16]
        except Exception:
            # Keep cache functional even if prompt lookup fails unexpectedly.
            prompt_signature = "no-prompt"

        msg_fingerprint = "|".join(m.ts for m in messages[-10:])
        raw = (
            f"{_SUMMARY_CACHE_SCHEMA_VERSION}:{prompt_signature}:"
            f"{req.slack_thread_url}:{req.description}:{req.site_id or ''}:"
            f"{req.custom_prompt or ''}:{model}:{len(messages)}:{msg_fingerprint}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    def _build_prompt_messages(
        self,
        req: SlackThreadInvestigationRequest,
        messages: List[SlackThreadMessage],
        model: str,
    ) -> Tuple[str, List[Dict], dict]:
        """Build system prompt + chat messages for summary generation.

        Returns (system_prompt, chat_messages, strategy).
        """
        system = load_prompt("issue_summary")
        strategy = self._model_summary_strategy(model)

        selected_messages = messages[-strategy["prompt_message_limit"]:]

        thread_lines: List[str] = []
        for msg in selected_messages:
            clean_msg = _URL_RE.sub("", msg.text).strip()
            line = f"{msg.user}: {clean_msg}"
            for idx, block in enumerate(msg.log_blocks, 1):
                clean_block = _URL_RE.sub("", block[:2000]).strip()
                line += f"\n  [Log block {idx}]\n{clean_block}"
            for attachment in msg.attachments:
                line += f"\n  [File shared: {attachment.filename}]"
            thread_lines.append(line)

        prompt = (
            f"ISSUE NAME / DESCRIPTION:\n{req.description}\n\n"
            f"SITE: {req.site_id or 'N/A'}\n\n"
            f"SLACK THREAD ({len(selected_messages)} messages)\n"
            "--- MESSAGES ---\n\n"
            + "\n\n".join(thread_lines)
        )
        if req.custom_prompt:
            prompt += f"\n\nSPECIAL FOCUS: {req.custom_prompt}"

        max_prompt_chars = min(
            strategy["prompt_char_budget"],
            max(500, (settings.ollama_num_ctx - 800) * 3),
        )
        if len(prompt) > max_prompt_chars:
            prompt = prompt[:max_prompt_chars] + "\n\n[... thread truncated to fit context window ...]"

        chat: List[Dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

        return system, chat, strategy

    @staticmethod
    def _model_summary_strategy(model: str) -> dict:
        """Return token budget and depth hints based on model capability."""
        m = model.lower()
        # Mid-tier cloud models — check BEFORE high-tier to avoid
        # "gpt-4o-mini" matching the "gpt-4o" substring in high-tier.
        if any(tag in m for tag in ("gpt-4o-mini", "gpt-3.5", "gemini-1.5-flash", "gemini-2.0-flash")):
            return {
                "max_tokens": 2800,
                "depth": "medium",
                "prompt_char_budget": 12000,
                "prompt_message_limit": 100,
            }
        # High-capability cloud models
        if any(tag in m for tag in ("gpt-5", "gpt-4o", "gpt-4.1", "gpt-4-turbo", "gemini-2", "gemini-1.5-pro", "claude")):
            return {
                "max_tokens": 3600,
                "depth": "high",
                "prompt_char_budget": 13000,
                "prompt_message_limit": 130,
            }
        # Large local models (70B+)
        if any(tag in m for tag in ("70b", "72b", "llama3.1:70", "qwen2.5:72")):
            return {
                "max_tokens": 2800,
                "depth": "medium",
                "prompt_char_budget": 12000,
                "prompt_message_limit": 100,
            }
        # Small local models (default)
        return {
            "max_tokens": 2000,
            "depth": "concise",
            "prompt_char_budget": 8000,
            "prompt_message_limit": 60,
        }

    def _infer_risk(self, summary: str, assessment: str = "") -> str:
        # Prefer structured assessment verdict over keyword scanning
        if assessment:
            lowered = assessment.lower()
            if "hardware fault" in lowered or "software bug" in lowered:
                return "high"
            if "configuration error" in lowered or "environmental factor" in lowered:
                return "medium"
            if "as designed" in lowered:
                return "low"
            if "tentative" in lowered:
                return "medium"

        # Fallback: keyword scan on full summary
        lowered = summary.lower()
        if any(token in lowered for token in ["sev1", "critical", "safety", "production down", "data loss"]):
            return "high"
        if any(token in lowered for token in ["degraded", "intermittent", "warning", "retry"]):
            return "medium"
        return "low"

    # ── Shared response builder ─────────────────────────────────────────────

    def _build_response(
        self,
        req: SlackThreadInvestigationRequest,
        ref: ParsedSlackThreadRef,
        messages: List[SlackThreadMessage],
        attachments: List[SlackThreadAttachment],
        summary: str,
        model_used: str,
        t0: float,
        t_fetch: float,
        t_llm_done: float = 0.0,
    ) -> SlackThreadInvestigationResponse:
        """Parse LLM summary into structured response fields."""
        t_llm = t_llm_done or time.perf_counter()
        sections = _split_markdown_sections(summary)

        # ── Extract Assessment (inline field, not a full section) ──
        assessment = ""
        assess_match = re.search(r"\*\*Assessment:\*\*\s*(.+?)(?:\n|$)", summary)
        if assess_match:
            assessment = assess_match.group(1).strip()

        # ── Incident templates — strict RCA structure ──
        issue = _find_section(sections, "issue summary", "issue overview", "the issue", "problem", "incident")
        issue_detail = sections.get("issue", "").strip()
        cause_text = _find_section(sections, "cause", "root cause", "tentative root cause", "root cause analysis")
        key_observations_section = _find_section(sections, "key observations", "observations", "important logs & errors")
        key_findings_section = _find_section(sections, "key findings", "findings")
        recovery = _find_section(sections, "recovery action", "recommended actions", "actions taken", "actions taken / suggested fixes", "suggested fixes")
        solution = _find_section(sections, "solution")
        conclusion = _find_section(sections, "conclusion", "conclusion / recovery action")

        # ── General template (D) ──
        thread_summary_section = _find_section(sections, "thread summary")
        key_points = _find_section(sections, "key points")
        decisions = _find_section(sections, "decisions & action items", "decisions", "action items")

        # ── Build thread_summary: narrative overview ONLY ──
        # Cause, Key Findings, Recovery Action, and Solution are rendered
        # as separate UI sections — do NOT embed them here to avoid duplication.
        summary_parts: List[str] = []

        if thread_summary_section:
            summary_parts.append(f"**Thread Summary**\n{thread_summary_section}")
            if key_points:
                summary_parts.append(f"**Key Points**\n{key_points}")
            if decisions:
                summary_parts.append(f"**Decisions & Action Items**\n{decisions}")
        else:
            if issue:
                summary_parts.append(f"**ISSUE SUMMARY**\n{issue}")
            if issue_detail:
                summary_parts.append(f"**Issue**\n{issue_detail}")
            if assessment:
                summary_parts.append(f"**Assessment:** {assessment}")

        thread_summary = "\n\n".join(summary_parts).strip() or summary[:2000]

        # ── Build key_findings list (from Key Observations + Key Findings) ──
        if thread_summary_section:
            findings_list = _as_bullets(key_points) if key_points else []
        else:
            combined_findings = ""
            if key_observations_section:
                combined_findings += key_observations_section
            if key_findings_section and key_findings_section != key_observations_section:
                combined_findings += "\n" + key_findings_section
            findings_list = _as_bullets(combined_findings) if combined_findings else []
        findings_list = findings_list or [
            "Review raw analysis for detailed evidence extracted from messages and files."
        ]

        # ── Build recommended_actions list (from Recovery Action ONLY) ──
        if thread_summary_section:
            actions_list = _as_bullets(decisions) if decisions else []
        else:
            actions_list = _as_bullets(recovery) if recovery else []
        actions_list = actions_list or [
            "No explicit action items detected; assign owners to follow up on unresolved findings."
        ]

        participants = sorted({msg.user for msg in messages if msg.user})

        usage = getattr(self._llm_service, "last_usage", {}) if self._llm_service else {}
        logger.info(
            "Slack investigate timing: fetch=%.2fs llm=%.2fs total=%.2fs (messages=%d file_mentions=%d)",
            t_fetch - t0,
            t_llm - t_fetch,
            time.perf_counter() - t0,
            len(messages),
            len(attachments),
        )
        return SlackThreadInvestigationResponse(
            workspace=ref.workspace,
            channel_id=ref.channel_id,
            thread_ts=ref.thread_ts,
            message_count=len(messages),
            file_mention_count=len(attachments),
            attachment_count=len(attachments),
            model_used=model_used,
            participants=participants,
            thread_summary=thread_summary,
            key_findings=findings_list,
            recommended_actions=actions_list,
            risk_level=self._infer_risk(summary, assessment=assessment),
            assessment=assessment,
            solution=solution or conclusion,
            cause=cause_text,
            timeline=messages,
            attachments=attachments,
            raw_analysis=summary,
            actual_prompt_tokens     = usage.get("prompt_tokens", 0),
            actual_completion_tokens = usage.get("completion_tokens", 0),
            actual_total_tokens      = usage.get("total_tokens", 0),
            cost_usd                 = usage.get("cost_usd", 0.0),
        )

    # ── Pre-investigation setup (shared between investigate & streaming) ──────

    def _pre_investigate(self, req: SlackThreadInvestigationRequest):
        """Validate env, parse URL, pre-warm Ollama, fetch messages.

        Returns (ref, messages, attachments, t0, t_fetch).
        """

        t0 = time.perf_counter()
        using_remote = False
        if self._llm_service and hasattr(self._llm_service, "active_provider"):
            using_remote = self._llm_service.active_provider.get("type") in ("openai", "gemini")
        if req.model_override and (req.model_override.startswith("openai:") or req.model_override.startswith("gemini:")):
            using_remote = True

        if not using_remote and not self._ollama_ping():
            raise RuntimeError(
                f"Ollama is not running at {self.ollama_host}. Run: ollama serve"
            )

        ref = parse_slack_thread_url(req.slack_thread_url)

        _warm_thread = None
        if not using_remote:
            warm_model = req.model_override or self.text_model
            if warm_model.startswith("ollama:"):
                warm_model = warm_model.removeprefix("ollama:")
            def _warm():
                try:
                    requests.post(
                        f"{self.ollama_host}/api/generate",
                        json={"model": warm_model, "prompt": "", "keep_alive": "10m"},
                        timeout=60,
                    )
                except Exception:
                    pass
            _warm_thread = threading.Thread(target=_warm, daemon=True)
            _warm_thread.start()

        fetch_limit = min(req.max_messages, _MAX_FETCH_MESSAGES)
        messages, attachments = self._fetch_thread_messages(ref, req.include_bots, fetch_limit)
        if not messages:
            raise RuntimeError("Thread is empty or inaccessible with current token/scopes.")
        t_fetch = time.perf_counter()
        logger.info("Slack fetch completed: %.2fs (%d messages, %d file mentions)",
                     t_fetch - t0, len(messages), len(attachments))

        if _warm_thread is not None:
            _warm_thread.join(timeout=_WARM_JOIN_TIMEOUT_SECONDS)

        return ref, messages, attachments, t0, t_fetch

    def investigate(self, req: SlackThreadInvestigationRequest) -> SlackThreadInvestigationResponse:
        ref, messages, attachments, t0, t_fetch = self._pre_investigate(req)
        summary, model_used = self._generate_summary(req, messages, attachments)
        t_llm_done = time.perf_counter()
        return self._build_response(req, ref, messages, attachments, summary, model_used, t0, t_fetch, t_llm_done)

    def investigate_streaming(self, req: SlackThreadInvestigationRequest):
        """Full investigation with streaming LLM output.

        Yields tuples of (event_type, data):
          - ("chunk", text_chunk)     — streaming LLM token
          - ("result", response)      — final SlackThreadInvestigationResponse
        """
        ref, messages, attachments, t0, t_fetch = self._pre_investigate(req)

        # Resolve model (same logic as _generate_summary)
        model = req.model_override or ""
        if self._llm_service and hasattr(self._llm_service, "active_provider") and not model:
            active = self._llm_service.active_provider
            model = f"{active['type']}:{active['model']}"
        if not model:
            model = self.text_model

        # Check cache — on hit, yield full text as single chunk
        cache_key = self._build_cache_key(req, messages, model)
        if cache_key in self._summary_cache:
            self._summary_cache.move_to_end(cache_key)
            summary, model_used = self._summary_cache[cache_key]
            logger.info("Summary cache HIT (streaming) thread=%s model=%s", req.slack_thread_url[:60], model)
            yield ("chunk", summary)
            yield ("result", self._build_response(req, ref, messages, attachments, summary, model_used, t0, t_fetch))
            return

        # Validate Ollama model installation for local models
        is_remote = model.startswith("openai:") or model.startswith("gemini:")
        if not is_remote:
            plain_model = model.removeprefix("ollama:")
            installed = self._ollama_models()
            model_prefix = plain_model.split(":", 1)[0]
            if not any(model_prefix in name for name in installed):
                if any(self.text_model.split(":", 1)[0] in name for name in installed):
                    plain_model = self.text_model
                else:
                    raise RuntimeError(f"Model '{plain_model}' is not installed in Ollama.")
            model = plain_model

        _system, chat, strategy = self._build_prompt_messages(req, messages, model)

        # Stream LLM output, collecting full text
        full_chunks: List[str] = []
        if self._llm_service and hasattr(self._llm_service, "chat_stream"):
            for chunk in self._llm_service.chat_stream(
                messages=chat,
                max_tokens=strategy["max_tokens"],
                temperature=0.2,
                model_override=model if model != getattr(self._llm_service, "model", None) else None,
                module="slack_investigation",
            ):
                full_chunks.append(chunk)
                yield ("chunk", chunk)
        else:
            # Fallback: non-streaming — yield full response at once
            summary = self._ollama_chat(chat, model, max_tokens=strategy["max_tokens"])
            full_chunks.append(summary)
            yield ("chunk", summary)

        summary = "".join(full_chunks)
        t_llm_done = time.perf_counter()

        # Cache the result
        self._summary_cache[cache_key] = (summary, model)
        if len(self._summary_cache) > _SUMMARY_CACHE_MAX:
            self._summary_cache.popitem(last=False)

        yield ("result", self._build_response(req, ref, messages, attachments, summary, model, t0, t_fetch, t_llm_done))
