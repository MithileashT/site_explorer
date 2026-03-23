"""
services/ai/llm_service.py
───────────────────────────
Single LLM call returning all 5 analysis sections in one response.
Works with Ollama (local) or any OpenAI-compatible endpoint.
Supports centralized provider management for global AI consistency.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, List, Optional

import requests as http_requests
from openai import OpenAI

from core.config import settings
from core.logging import get_logger
from services.ai.pricing import MODEL_PRICING
from services.ai.pricing import calculate_cost, get_pricing

logger = get_logger(__name__)


class TokenLimitError(RuntimeError):
    """Raised when the prompt exceeds the model's context window."""
    pass


class RateLimitError(RuntimeError):
    """Raised when the provider returns a rate-limit or quota-exceeded error (HTTP 429)."""
    pass


_SECTIONS = [
    "log_timeline", "node_analysis", "error_analysis",
    "pattern_analysis", "technical_conclusion",
]
_EMPTY_RESULT: Dict[str, Any] = {k: "" for k in _SECTIONS}

_DELIMITERS = {
    "log_timeline":         "###LOG_TIMELINE###",
    "node_analysis":        "###NODE_ANALYSIS###",
    "error_analysis":       "###ERROR_ANALYSIS###",
    "pattern_analysis":     "###PATTERN_ANALYSIS###",
    "technical_conclusion": "###CONCLUSION###",
}

_MAX_LOG_LINES = 120

_STOPWORDS = {
    "the","a","an","is","it","in","on","at","of","to","and","or","was","were",
    "be","been","being","have","has","had","do","does","did","will","would",
    "could","should","not","no","with","for","from","by","are","that","this",
    "but","if","as","so","up","its","my","we","i","robot","system","issue",
    "error","problem","occurred","happened","during","after","before","when",
}


def _extract_keywords(description: str) -> List[str]:
    tokens = re.findall(r"[a-zA-Z0-9_/]+", description.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 2]


def _find_relevant_logs(logs: List[Dict], keywords: List[str]) -> List[Dict]:
    if not keywords:
        return [e for e in logs if e["log_level"] in ("ERROR", "FATAL")]
    relevant = []
    for e in logs:
        text = (e["message"] + " " + e["node_name"]).lower()
        if e["log_level"] in ("ERROR", "FATAL") or any(kw in text for kw in keywords):
            relevant.append(e)
    return relevant


def _parse_sections(raw: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    delim_order = list(_DELIMITERS.items())
    for i, (key, token) in enumerate(delim_order):
        start = raw.find(token)
        if start == -1:
            result[key] = ""
            continue
        content_start = start + len(token)
        if i + 1 < len(delim_order):
            next_token = delim_order[i + 1][1]
            end        = raw.find(next_token, content_start)
            content    = raw[content_start:end] if end != -1 else raw[content_start:]
        else:
            content = raw[content_start:]
        result[key] = content.strip()
    return result


class LLMService:
    def __init__(self) -> None:
        self._lock = threading.Lock()

        # ── Ollama client (always available) ─────────────────────────────────
        self._ollama_client = OpenAI(
            base_url=settings.ollama_base_url, api_key="ollama"
        )
        self._ollama_host = settings.ollama_host.rstrip("/")

        # ── OpenAI client (available when API key is configured) ─────────────
        self._openai_client: Optional[OpenAI] = None
        if settings.openai_api_key:
            self._openai_client = OpenAI(api_key=settings.openai_api_key)

        # ── Gemini client (OpenAI-compatible endpoint) ───────────────────────
        self._gemini_client: Optional[OpenAI] = None
        if settings.gemini_api_key:
            self._gemini_client = OpenAI(
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=settings.gemini_api_key,
            )

        # ── Actual token usage from last LLM call ────────────────────────────
        # Populated after every call to .chat(); zeroed on new call.
        self.last_usage: Dict[str, Any] = {}

        # ── Cumulative session usage (since service start) ───────────────────
        # Keyed by module name: "log_analyser", "bag_analyser", "slack_investigation", "other"
        self._session_usage: Dict[str, Dict[str, Any]] = {}
        self._session_start = time.time()

        # ── Active provider state ────────────────────────────────────────────
        # Default: use OpenAI if key present, else Ollama
        if settings.openai_api_key:
            self._active_type = "openai"
            self._active_model = settings.openai_model
        else:
            self._active_type = "ollama"
            self._active_model = settings.ollama_model

        # Legacy attributes for backward compatibility
        self.client = (
            self._openai_client if self._active_type == "openai"
            else self._ollama_client
        )
        self.model = self._active_model

        logger.info("LLMService: provider=%s model=%s", self._active_type, self._active_model)

    # ── Provider management ──────────────────────────────────────────────────

    def _ollama_installed_models(self) -> List[str]:
        try:
            resp = http_requests.get(f"{self._ollama_host}/api/tags", timeout=5)
            resp.raise_for_status()
            return [m.get("name", "") for m in resp.json().get("models", [])]
        except Exception:
            return []

    def available_providers(self) -> List[Dict[str, str]]:
        """Return all available AI providers/models the user can select."""
        providers: List[Dict[str, str]] = []

        # Ollama models
        for model_name in self._ollama_installed_models():
            providers.append({
                "id": f"ollama:{model_name}",
                "name": model_name,
                "type": "ollama",
            })
        # Always include the configured default even if Ollama is offline
        default_id = f"ollama:{settings.ollama_model}"
        if not any(p["id"] == default_id for p in providers):
            providers.append({
                "id": default_id,
                "name": settings.ollama_model,
                "type": "ollama",
            })

        # OpenAI (when API key is configured)
        # List the configured default plus well-known models from the pricing registry.
        if settings.openai_api_key:
            _openai_models_seen: set = set()
            # Always include the configured model first
            providers.append({
                "id": f"openai:{settings.openai_model}",
                "name": f"OpenAI {settings.openai_model}",
                "type": "openai",
            })
            _openai_models_seen.add(settings.openai_model)
            # Add well-known OpenAI models from pricing registry
            for model_name in MODEL_PRICING:
                if model_name.startswith("gpt-") and model_name not in _openai_models_seen:
                    providers.append({
                        "id": f"openai:{model_name}",
                        "name": f"OpenAI {model_name}",
                        "type": "openai",
                    })
                    _openai_models_seen.add(model_name)

        # Gemini (when API key is configured)
        if settings.gemini_api_key:
            providers.append({
                "id": f"gemini:{settings.gemini_model}",
                "name": f"Gemini {settings.gemini_model}",
                "type": "gemini",
            })

        return providers

    @property
    def active_provider(self) -> Dict[str, str]:
        return {
            "id": f"{self._active_type}:{self._active_model}",
            "name": self._active_model,
            "model": self._active_model,
            "type": self._active_type,
        }

    def set_active_provider(self, provider_id: str) -> Dict[str, str]:
        """Switch the globally active AI provider. provider_id format: 'type:model'."""
        if ":" not in provider_id:
            raise ValueError(f"Invalid provider ID format: '{provider_id}'. Expected 'type:model'.")

        ptype, model = provider_id.split(":", 1)

        if ptype == "openai":
            if not self._openai_client:
                raise ValueError("OpenAI API key is not configured. Set OPENAI_API_KEY in .env.")
        elif ptype == "gemini":
            if not self._gemini_client:
                raise ValueError("Gemini API key is not configured. Set GEMINI_API_KEY in .env.")
        elif ptype == "ollama":
            pass  # Ollama is always available as a target
        else:
            raise ValueError(f"Unknown provider type: '{ptype}'. Supported: ollama, openai, gemini.")

        with self._lock:
            self._active_type = ptype
            self._active_model = model

            # Update legacy attributes
            if ptype == "openai":
                self.client = self._openai_client
            elif ptype == "gemini":
                self.client = self._gemini_client
            else:
                self.client = self._ollama_client
            self.model = model

        logger.info("AI provider switched: %s → %s", ptype, model)
        return self.active_provider

    # ── Generic chat method (used by all AI features) ────────────────────────

    def chat(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int = 3500,
        temperature: float = 0.1,
        model_override: Optional[str] = None,
        module: str = "other",
    ) -> str:
        """Unified chat completion using the active provider.

        If model_override is given (format 'type:model' or plain model name),
        it overrides the active provider for this single call.
        ``module`` tags the call for per-module session tracking
        (e.g. "log_analyser", "bag_analyser", "slack_investigation").
        """
        ptype = self._active_type
        model = self._active_model
        client = self.client

        if model_override:
            if ":" in model_override and model_override.split(":", 1)[0] in ("openai", "ollama", "gemini"):
                ptype, model = model_override.split(":", 1)
            else:
                # Plain model name — assume it's an Ollama model
                model = model_override
                ptype = "ollama"

            if ptype == "openai":
                client = self._openai_client
            elif ptype == "gemini":
                client = self._gemini_client
            else:
                client = self._ollama_client

        if client is None:
            raise RuntimeError(f"No client available for provider '{ptype}'. Check configuration.")

        try:
            # Ollama on CPU can be very slow (5-10 tok/s); give it 10 minutes.
            # OpenAI API is fast; 3 minutes is plenty.
            llm_timeout = 600 if ptype == "ollama" else 180
            kwargs: Dict[str, Any] = {
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "messages": messages,
                "timeout": llm_timeout,
            }
            # Pass Ollama-specific context window setting
            if ptype == "ollama":
                kwargs["extra_body"] = {"options": {"num_ctx": settings.ollama_num_ctx}}

            resp = client.chat.completions.create(**kwargs)
            # Capture real token usage from API response
            try:
                if resp.usage:
                    cost = calculate_cost(
                        model,
                        int(resp.usage.prompt_tokens),
                        int(resp.usage.completion_tokens),
                    )
                    self.last_usage = {
                        "prompt_tokens":     int(resp.usage.prompt_tokens),
                        "completion_tokens": int(resp.usage.completion_tokens),
                        "total_tokens":      int(resp.usage.total_tokens),
                        "cost_usd":          cost,
                        "model":             model,
                        "provider":          ptype,
                    }
                    # Accumulate into session tracker
                    self._accumulate_session(module, self.last_usage)

                    if ptype == "openai":
                        logger.info(
                            "[TOKEN_USAGE] provider=%s model=%s module=%s | prompt=%d completion=%d total=%d | cost=$%.6f",
                            ptype, model, module,
                            self.last_usage["prompt_tokens"],
                            self.last_usage["completion_tokens"],
                            self.last_usage["total_tokens"],
                            cost,
                        )
                    else:
                        logger.info(
                            "[TOKEN_USAGE] provider=%s model=%s module=%s | prompt=%d completion=%d total=%d",
                            ptype, model, module,
                            self.last_usage["prompt_tokens"],
                            self.last_usage["completion_tokens"],
                            self.last_usage["total_tokens"],
                        )
            except (TypeError, ValueError, AttributeError):
                pass  # non-standard mock or provider; usage tracking not critical
            return (resp.choices[0].message.content or "").strip()
        except Exception as exc:
            error_str = str(exc).lower()
            logger.error("LLM chat failed (provider=%s, model=%s): %s", ptype, model, exc)
            # Distinguish rate/quota limit (429) from context-too-large errors.
            # Rate limits should NOT be retried by reducing input size.
            is_rate_limit = (
                "429" in str(exc)
                or "rate_limit" in error_str
                or "rate limit" in error_str
                or "quota" in error_str
            )
            is_token_limit = (
                "too large" in error_str
                or "context_length" in error_str
                or "context length" in error_str
                or "maximum context" in error_str
                or "max tokens" in error_str
            )
            if is_rate_limit and not is_token_limit:
                raise RateLimitError(f"Rate/quota limit ({ptype}/{model}): {exc}") from exc
            if is_rate_limit or is_token_limit:
                raise TokenLimitError(f"Token limit exceeded ({ptype}/{model}): {exc}") from exc
            raise RuntimeError(f"LLM call failed ({ptype}/{model}): {exc}") from exc

    # ── Session usage tracking ─────────────────────────────────────────────

    def _resolve_client(self, model_override: Optional[str] = None):
        """Resolve provider type, model name, and client for a given override.

        Returns (ptype, model, client).
        """
        ptype = self._active_type
        model = self._active_model
        client = self.client

        if model_override:
            if ":" in model_override and model_override.split(":", 1)[0] in ("openai", "ollama", "gemini"):
                ptype, model = model_override.split(":", 1)
            else:
                model = model_override
                ptype = "ollama"

            if ptype == "openai":
                client = self._openai_client
            elif ptype == "gemini":
                client = self._gemini_client
            else:
                client = self._ollama_client

        if client is None:
            raise RuntimeError(f"No client available for provider '{ptype}'. Check configuration.")
        return ptype, model, client

    def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int = 3500,
        temperature: float = 0.1,
        model_override: Optional[str] = None,
        module: str = "other",
    ):
        """Streaming chat completion — yields text chunks as they arrive.

        Same provider-routing logic as ``chat()`` but uses ``stream=True``.
        Token usage is NOT tracked for streaming calls (API doesn't return usage
        in streaming mode for most providers).
        """
        ptype, model, client = self._resolve_client(model_override)

        llm_timeout = 600 if ptype == "ollama" else 180
        kwargs: Dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": messages,
            "timeout": llm_timeout,
            "stream": True,
        }
        if ptype == "ollama":
            kwargs["extra_body"] = {"options": {"num_ctx": settings.ollama_num_ctx}}

        try:
            stream = client.chat.completions.create(**kwargs)
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as exc:
            logger.error("LLM chat_stream failed (provider=%s, model=%s): %s", ptype, model, exc)
            raise RuntimeError(f"LLM streaming failed ({ptype}/{model}): {exc}") from exc

    def _accumulate_session(self, module: str, usage: Dict[str, Any]) -> None:
        """Add a single call's usage to the cumulative session tracker."""
        if module not in self._session_usage:
            self._session_usage[module] = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
                "request_count": 0,
            }
        bucket = self._session_usage[module]
        bucket["prompt_tokens"]     += usage.get("prompt_tokens", 0)
        bucket["completion_tokens"] += usage.get("completion_tokens", 0)
        bucket["total_tokens"]      += usage.get("total_tokens", 0)
        bucket["cost_usd"]          += usage.get("cost_usd", 0.0)
        bucket["request_count"]     += 1

    def get_session_usage(self) -> Dict[str, Any]:
        """Return cumulative session usage stats (per-module + totals)."""
        totals = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "request_count": 0,
        }
        for stats in self._session_usage.values():
            for k in totals:
                totals[k] += stats[k]
        totals["cost_usd"] = round(totals["cost_usd"], 6)
        per_module = {
            mod: {**stats, "cost_usd": round(stats["cost_usd"], 6)}
            for mod, stats in self._session_usage.items()
        }
        return {
            "session_start": self._session_start,
            "uptime_seconds": round(time.time() - self._session_start, 1),
            "active_model": self._active_model,
            "active_provider": self._active_type,
            "modules": per_module,
            "totals": totals,
        }

    def reset_session_usage(self) -> None:
        """Reset cumulative session counters."""
        self._session_usage.clear()
        self._session_start = time.time()

    # ── Legacy methods (preserved for backward compatibility) ────────────────

    def _call(self, system: str, user: str, max_tokens: int = 3500, module: str = "other") -> str:
        return self.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            module=module,
        )

    def generate_log_incident_summary(
        self,
        robot_name: str,
        incident_time: str,
        filtered_logs: List[Dict[str, Any]],
        priority_logs: List[Dict[str, Any]],
        issue_description: str = "",
        engine_hypothesis: str = "",
    ) -> Dict[str, Any]:
        """Single LLM call producing 5 structured analysis sections."""
        if not filtered_logs:
            r = dict(_EMPTY_RESULT)
            r["log_timeline"] = "No logs found in the specified time window."
            return r

        desc_clean    = issue_description.strip()
        keywords      = _extract_keywords(desc_clean) if desc_clean else []
        relevant_logs = _find_relevant_logs(filtered_logs, keywords)

        def fmt(entries: List[Dict]) -> str:
            return "\n".join(
                f"[{e['log_level']:5s}] {e['datetime']}  {e['node_name'][:40]:40s}  {e['message']}"
                for e in entries
            )

        err_entries   = [e for e in filtered_logs if e["log_level"] in ("ERROR", "FATAL", "WARN")]
        other_entries = [e for e in filtered_logs if e not in err_entries]
        cap_others    = max(0, _MAX_LOG_LINES - len(err_entries))
        trimmed       = sorted(err_entries + other_entries[:cap_others], key=lambda e: e["timestamp"])

        log_block = fmt(trimmed)
        err_block = fmt([e for e in trimmed if e["log_level"] in ("ERROR", "FATAL", "WARN")]) or "(none)"

        rel_seen, rel_dedup = set(), []
        for e in sorted(relevant_logs, key=lambda x: x["timestamp"]):
            key = (e["timestamp"], e["node_name"], e["message"])
            if key not in rel_seen:
                rel_seen.add(key)
                rel_dedup.append(e)
        rel_block = fmt(rel_dedup) or "(No log entries matched the reported issue keywords)"

        total  = len(filtered_logs)
        n_err  = sum(1 for e in filtered_logs if e["log_level"] in ("ERROR", "FATAL"))
        n_warn = sum(1 for e in filtered_logs if e["log_level"] == "WARN")
        span   = f"{filtered_logs[0]['datetime']}  →  {filtered_logs[-1]['datetime']}"
        nodes  = ", ".join(sorted({e["node_name"] for e in filtered_logs}))

        hypothesis_block = (
            f"\nRULE-BASED HYPOTHESIS FROM SIGNAL ANALYSIS:\n{engine_hypothesis}\n"
            if engine_hypothesis else ""
        )

        description_block = ""
        if desc_clean:
            description_block = (
                f"\n══ ENGINEER'S REPORTED ISSUE ══\n"
                f'  "{desc_clean}"\n'
                f"  Keywords: {', '.join(keywords) or '(none)'}\n"
                f"  Matching log entries ({len(rel_dedup)}):\n{rel_block}\n"
                f"══════════════════════════════\n"
            )

        system_prompt = (
            "You are a senior ROS/AMR field engineer performing root-cause analysis. "
            "Read the reported issue and find log evidence that explains or contradicts it. "
            "Cite exact node names, timestamps, and verbatim messages as evidence. "
            "Do NOT fabricate log entries. Do NOT repeat the full log in your output.\n\n"
            f"Output EXACTLY these five sections in order, each starting with its delimiter:\n"
            + "\n".join(f"  {d}" for d in _DELIMITERS.values())
        )

        user_prompt = (
            f"Robot: {robot_name} | Incident: {incident_time} | Span: {span}\n"
            f"Counts: {total} total | {n_err} ERROR/FATAL | {n_warn} WARN\n"
            f"Active nodes: {nodes}\n"
            f"{description_block}"
            f"{hypothesis_block}\n"
            f"FULL /rosout LOG ({len(trimmed)} entries):\n{log_block}\n\n"
            f"ERROR/WARN entries:\n{err_block}"
        )

        raw    = self._call(system_prompt, user_prompt, module="bag_analyser")
        result = _parse_sections(raw)
        for k in _SECTIONS:
            if k not in result:
                result[k] = ""
        result["_raw"] = raw
        return result

    def generate_investigation_summary(self, prompt: str) -> str:
        """Feed a pre-built investigation prompt (from LogAnalyzerEngine) to the LLM."""
        system = (
            "You are an expert ROS/AMR diagnostics engineer. "
            "Analyse the incident and give a structured response with: "
            "Root Cause, Confidence Level, Evidence, and Recommended Next Steps."
        )
        return self._call(system, prompt, max_tokens=1500)
