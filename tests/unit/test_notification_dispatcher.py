"""Tests for notification dispatcher service (FR-SS003)."""

import os
from unittest.mock import MagicMock, patch


class TestNotificationDispatcher:
    def _make_dispatcher(self, channels=None):
        with patch("src.web.services.notification_dispatcher.load_config") as mock_load:
            mock_load.return_value = {
                "notifications": {
                    "channels": channels or [],
                    "event_types": [
                        "risk_alert",
                        "sentiment_update",
                        "advisor_signal",
                    ],
                }
            }
            from src.web.services.notification_dispatcher import (
                NotificationDispatcher,
            )

            return NotificationDispatcher()

    def test_init_no_config(self):
        with patch("src.web.services.notification_dispatcher.load_config") as mock_load:
            mock_load.side_effect = FileNotFoundError
            from src.web.services.notification_dispatcher import (
                NotificationDispatcher,
            )

            dispatcher = NotificationDispatcher()
            assert dispatcher.get_channels() == []

    def test_get_channels_masks_secrets(self):
        dispatcher = self._make_dispatcher(
            channels=[
                {
                    "type": "wecom",
                    "enabled": True,
                    "webhook_url": "https://example.com/12345678abcdef",
                    "events": ["all"],
                }
            ]
        )
        channels = dispatcher.get_channels()
        assert len(channels) == 1
        assert "****" in channels[0]["webhook_url"]

    def test_get_channels_keeps_env_var_reference(self):
        dispatcher = self._make_dispatcher(
            channels=[
                {
                    "type": "telegram",
                    "enabled": False,
                    "bot_token": "${TELEGRAM_BOT_TOKEN}",
                    "chat_id": "${TELEGRAM_CHAT_ID}",
                    "events": [],
                }
            ]
        )
        channels = dispatcher.get_channels()
        assert channels[0]["bot_token"] == "${TELEGRAM_BOT_TOKEN}"

    def test_get_event_types(self):
        dispatcher = self._make_dispatcher()
        types = dispatcher.get_event_types()
        assert "risk_alert" in types

    def test_dispatch_disabled_channels_skipped(self):
        dispatcher = self._make_dispatcher(
            channels=[
                {
                    "type": "wecom",
                    "enabled": False,
                    "webhook_url": "https://example.com",
                    "events": ["all"],
                }
            ]
        )
        result = dispatcher.dispatch("risk_alert", "Test", "Body")
        assert result["dispatched"] == 0
        assert result["channels"] == {}

    def test_dispatch_event_filtering(self):
        dispatcher = self._make_dispatcher(
            channels=[
                {
                    "type": "wecom",
                    "enabled": True,
                    "webhook_url": "https://example.com/hook",
                    "events": ["risk_alert"],
                }
            ]
        )
        # sentiment_update not in events list, should be skipped
        result = dispatcher.dispatch("sentiment_update", "Test", "Body")
        assert result["dispatched"] == 0

    def test_dispatch_all_events_match(self):
        dispatcher = self._make_dispatcher(
            channels=[
                {
                    "type": "webhook",
                    "enabled": True,
                    "url": "https://example.com/hook",
                    "method": "POST",
                    "events": ["all"],
                }
            ]
        )
        # Mock the httpx client
        dispatcher._client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        dispatcher._client.post.return_value = mock_resp

        result = dispatcher.dispatch("anything", "Test", "Body")
        assert result["dispatched"] == 1
        assert result["channels"]["webhook"] == "ok"

    def test_dispatch_failure_isolation(self):
        dispatcher = self._make_dispatcher(
            channels=[
                {
                    "type": "wecom",
                    "enabled": True,
                    "webhook_url": "",  # Will fail
                    "events": ["all"],
                },
                {
                    "type": "webhook",
                    "enabled": True,
                    "url": "https://example.com/hook",
                    "method": "POST",
                    "events": ["all"],
                },
            ]
        )
        dispatcher._client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        dispatcher._client.post.return_value = mock_resp

        result = dispatcher.dispatch("risk_alert", "Test", "Body")
        # wecom should error (empty url), webhook should succeed
        assert "error" in result["channels"].get("wecom", "")
        assert result["channels"]["webhook"] == "ok"

    def test_resolve_env_variable(self):
        dispatcher = self._make_dispatcher()
        os.environ["TEST_SENTINEL_VAR"] = "resolved_value"
        try:
            assert dispatcher._resolve_env("${TEST_SENTINEL_VAR}") == "resolved_value"
            assert dispatcher._resolve_env("plain_string") == "plain_string"
            assert dispatcher._resolve_env("${NONEXISTENT_VAR}") == ""
        finally:
            del os.environ["TEST_SENTINEL_VAR"]

    def test_update_channels(self):
        dispatcher = self._make_dispatcher()
        new_channels = [{"type": "telegram", "enabled": True, "events": ["all"]}]
        dispatcher.update_channels(new_channels)
        assert dispatcher._config["channels"] == new_channels

    def test_unsupported_channel_type(self):
        dispatcher = self._make_dispatcher(
            channels=[
                {
                    "type": "unknown_service",
                    "enabled": True,
                    "events": ["all"],
                }
            ]
        )
        result = dispatcher.dispatch("risk_alert", "Test", "Body")
        assert result["channels"]["unknown_service"] == "unsupported"
