"""Unit tests for robust Slack token resolution."""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import config as config_module


def test_resolve_slack_bot_token_prefers_primary_env(monkeypatch) -> None:
    monkeypatch.setenv("SLACK_BOT_TOKEN", '  "xoxb-primary-token"  ')
    monkeypatch.setenv("SLACK_TOKEN", "xoxb-alias-token")
    monkeypatch.setenv("SLACK_API_TOKEN", "xoxb-legacy-token")

    assert config_module.resolve_slack_bot_token() == "xoxb-primary-token"


def test_resolve_slack_bot_token_uses_alias_when_primary_missing(monkeypatch) -> None:
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.setenv("SLACK_TOKEN", "'xoxb-alias-token'")
    monkeypatch.delenv("SLACK_API_TOKEN", raising=False)

    assert config_module.resolve_slack_bot_token() == "xoxb-alias-token"


def test_resolve_slack_bot_token_falls_back_to_env_file(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / "backend.env"
    env_file.write_text('SLACK_BOT_TOKEN="xoxb-from-dotenv"\n', encoding="utf-8")

    monkeypatch.setattr(config_module, "_ENV_PATH", str(env_file))
    monkeypatch.setenv("SLACK_BOT_TOKEN", "")
    monkeypatch.delenv("SLACK_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_API_TOKEN", raising=False)

    assert config_module.resolve_slack_bot_token() == "xoxb-from-dotenv"
