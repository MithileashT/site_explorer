"""Prompt file loader — reads .md prompt files from this directory."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=16)
def load_prompt(name: str) -> str:
    """Load a prompt file by name (without extension).

    Raises FileNotFoundError if the file does not exist.
    """
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()
