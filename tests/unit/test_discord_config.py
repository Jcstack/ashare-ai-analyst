"""Unit tests for Discord bot config reader."""

from __future__ import annotations

from unittest.mock import patch


class TestGetTimeout:
    def test_reads_from_config(self):
        fake_cfg = {
            "rate_limits": {
                "agent_timeout": 600,
                "analysis_timeout": 300,
                "follow_up_timeout": 600,
            }
        }
        with patch("src.discord_bot.config.load_config", return_value=fake_cfg):
            # Clear lru_cache so our mock takes effect
            from src.discord_bot.config import get_discord_config, get_timeout

            get_discord_config.cache_clear()
            assert get_timeout("agent_timeout") == 600
            assert get_timeout("analysis_timeout") == 300
            assert get_timeout("follow_up_timeout") == 600
            get_discord_config.cache_clear()

    def test_defaults_when_key_missing(self):
        fake_cfg = {"rate_limits": {}}
        with patch("src.discord_bot.config.load_config", return_value=fake_cfg):
            from src.discord_bot.config import get_discord_config, get_timeout

            get_discord_config.cache_clear()
            assert get_timeout("nonexistent_key", 999) == 999
            assert get_timeout("agent_timeout", 600) == 600
            get_discord_config.cache_clear()

    def test_defaults_when_section_missing(self):
        fake_cfg = {}
        with patch("src.discord_bot.config.load_config", return_value=fake_cfg):
            from src.discord_bot.config import get_discord_config, get_timeout

            get_discord_config.cache_clear()
            assert get_timeout("agent_timeout", 300) == 300
            get_discord_config.cache_clear()
