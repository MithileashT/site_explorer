"""Tests for prompt file loader."""

from services.ai.prompts import load_prompt


def test_load_issue_summary_prompt() -> None:
    """load_prompt('issue_summary') returns non-empty string with strict sections."""
    text = load_prompt("issue_summary")
    assert isinstance(text, str)
    assert len(text) > 500
    assert "INCIDENT FORMAT" in text
    assert "GENERAL FORMAT" in text
    assert "**ISSUE SUMMARY**" in text
    assert "**Cause" in text


def test_load_prompt_caches() -> None:
    """Subsequent calls return the same object (cached)."""
    a = load_prompt("issue_summary")
    b = load_prompt("issue_summary")
    assert a is b


def test_load_prompt_missing_raises() -> None:
    """Requesting a non-existent prompt raises FileNotFoundError."""
    import pytest

    with pytest.raises(FileNotFoundError):
        load_prompt("nonexistent_prompt_xyz")
