"""
services/ai/pricing.py
─────────────────────────
Configurable OpenAI model pricing.  All prices in USD per 1 million tokens.
Update these when OpenAI changes their pricing page.
"""
from __future__ import annotations

from typing import Any, Dict

# ── Pricing Registry ──────────────────────────────────────────────────────────
# Key = model name (or prefix match).
# Values = {"input": $/M tokens, "output": $/M tokens}
MODEL_PRICING: Dict[str, Dict[str, float]] = {
    # GPT-5.x family
    "gpt-5.4":       {"input": 3.00,  "output": 12.00},
    "gpt-5.2":       {"input": 2.50,  "output": 10.00},
    "gpt-5.1":       {"input": 2.00,  "output": 8.00},
    # GPT-4.1 family
    "gpt-4.1":       {"input": 2.00,  "output": 8.00},
    "gpt-4.1-mini":  {"input": 0.40,  "output": 1.60},
    "gpt-4.1-nano":  {"input": 0.10,  "output": 0.40},
    # GPT-4o family
    "gpt-4o":        {"input": 2.50,  "output": 10.00},
    "gpt-4o-mini":   {"input": 0.15,  "output": 0.60},
    # GPT-4 Turbo
    "gpt-4-turbo":   {"input": 10.00, "output": 30.00},
    # o-series reasoning
    "o4-mini":       {"input": 1.10,  "output": 4.40},
    "o3":            {"input": 10.00, "output": 40.00},
    "o3-mini":       {"input": 1.10,  "output": 4.40},
    "o1":            {"input": 15.00, "output": 60.00},
    "o1-mini":       {"input": 1.10,  "output": 4.40},
    # GPT-3.5 Turbo (still used by some)
    "gpt-3.5-turbo": {"input": 0.50,  "output": 1.50},
    # Google Gemini family
    "gemini-2.0-flash":  {"input": 0.10,  "output": 0.40},
    "gemini-1.5-flash":  {"input": 0.075, "output": 0.30},
    "gemini-1.5-pro":    {"input": 1.25,  "output": 5.00},
}

# Fallback for unknown models (use gpt-4.1 pricing as safe default)
_DEFAULT_PRICING = {"input": 2.00, "output": 8.00}


def get_pricing(model: str) -> Dict[str, float]:
    """Return {"input": $/M, "output": $/M} for the given model name.

    Does exact match first, then prefix match, then returns the default.
    """
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    # Prefix match: "gpt-4.1-2025-04-14" → "gpt-4.1"
    for prefix, pricing in MODEL_PRICING.items():
        if model.startswith(prefix):
            return pricing
    return dict(_DEFAULT_PRICING)


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Calculate the USD cost for a single API call."""
    p = get_pricing(model)
    return (
        prompt_tokens     * p["input"]  / 1_000_000
        + completion_tokens * p["output"] / 1_000_000
    )


def get_all_pricing() -> Dict[str, Dict[str, float]]:
    """Return the full pricing registry (for UI display)."""
    return dict(MODEL_PRICING)
