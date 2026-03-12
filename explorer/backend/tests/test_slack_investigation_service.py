"""Unit tests for Slack investigation URL parsing helpers."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services.ai.slack_investigation_service import parse_slack_thread_url


def test_parse_slack_thread_url_success() -> None:
    ref = parse_slack_thread_url("https://example.slack.com/archives/C123ABC45/p1772691175223000")
    assert ref.workspace == "example"
    assert ref.channel_id == "C123ABC45"
    assert ref.thread_ts == "1772691175.223000"


def test_parse_slack_thread_url_rejects_invalid_url() -> None:
    with pytest.raises(ValueError):
        parse_slack_thread_url("https://example.slack.com/archives/C123ABC45")
