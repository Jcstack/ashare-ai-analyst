"""Multi-channel notification dispatcher.

Sends notifications to external channels (WeChat Work, DingTalk,
Telegram, generic Webhook) based on sentinel.yaml configuration.

Per PRD v3.2 FR-SS003: Multi-channel notification configuration.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("web.notification_dispatcher")


class NotificationDispatcher:
    """Dispatches notifications to configured external channels.

    Each channel sends independently — one failure does not block others.
    """

    def __init__(self) -> None:
        self._config = self._load_config()
        self._client = httpx.Client(timeout=10.0)
        logger.info("NotificationDispatcher initialized")

    def _load_config(self) -> dict[str, Any]:
        try:
            config = load_config("sentinel")
            return config.get("notifications", {})
        except FileNotFoundError:
            logger.warning("config/sentinel.yaml not found; no notification channels")
            return {}

    def _resolve_env(self, value: str) -> str:
        """Resolve ${ENV_VAR} patterns in config values."""
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            env_key = value[2:-1]
            return os.environ.get(env_key, "")
        return value

    def get_channels(self) -> list[dict[str, Any]]:
        """Return all configured channels (with secrets masked)."""
        channels = self._config.get("channels", [])
        result = []
        for ch in channels:
            masked = dict(ch)
            for key in ("webhook_url", "bot_token", "secret", "url"):
                if key in masked and masked[key]:
                    val = str(masked[key])
                    if val.startswith("${"):
                        masked[key] = val  # Show env var name
                    elif len(val) > 8:
                        masked[key] = val[:4] + "****" + val[-4:]
                    else:
                        masked[key] = "****"
            result.append(masked)
        return result

    def get_event_types(self) -> list[str]:
        """Return all supported event types."""
        return self._config.get("event_types", [])

    def dispatch(
        self,
        event_type: str,
        title: str,
        message: str,
        *,
        severity: str = "info",
    ) -> dict[str, Any]:
        """Send notification to all channels subscribed to this event type.

        Args:
            event_type: Event type (e.g. "risk_alert", "sentiment_update").
            title: Notification title.
            message: Notification body text.
            severity: Severity level (info, warning, critical).

        Returns:
            Dict with results per channel.
        """
        channels = self._config.get("channels", [])
        results: dict[str, str] = {}

        for ch in channels:
            if not ch.get("enabled", False):
                continue

            events = ch.get("events", [])
            if "all" not in events and event_type not in events:
                continue

            ch_type = ch.get("type", "unknown")
            try:
                if ch_type == "wecom":
                    self._send_wecom(ch, title, message)
                elif ch_type == "dingtalk":
                    self._send_dingtalk(ch, title, message)
                elif ch_type == "telegram":
                    self._send_telegram(ch, title, message)
                elif ch_type == "webhook":
                    self._send_webhook(ch, event_type, title, message, severity)
                else:
                    results[ch_type] = "unsupported"
                    continue
                results[ch_type] = "ok"
            except Exception as exc:
                logger.warning("Failed to send to %s: %s", ch_type, exc)
                results[ch_type] = f"error: {exc}"

        return {
            "event_type": event_type,
            "channels": results,
            "dispatched": sum(1 for v in results.values() if v == "ok"),
        }

    def _send_wecom(self, ch: dict, title: str, message: str) -> None:
        """Send via WeChat Work (企业微信) webhook."""
        url = self._resolve_env(ch.get("webhook_url", ""))
        if not url:
            raise ValueError("WeChat Work webhook_url not configured")

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": f"### {title}\n{message}",
            },
        }
        resp = self._client.post(url, json=payload)
        resp.raise_for_status()

    def _send_dingtalk(self, ch: dict, title: str, message: str) -> None:
        """Send via DingTalk (钉钉) webhook."""
        url = self._resolve_env(ch.get("webhook_url", ""))
        if not url:
            raise ValueError("DingTalk webhook_url not configured")

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": f"### {title}\n{message}",
            },
        }
        resp = self._client.post(url, json=payload)
        resp.raise_for_status()

    def _send_telegram(self, ch: dict, title: str, message: str) -> None:
        """Send via Telegram Bot API."""
        token = self._resolve_env(ch.get("bot_token", ""))
        chat_id = self._resolve_env(ch.get("chat_id", ""))
        if not token or not chat_id:
            raise ValueError("Telegram bot_token or chat_id not configured")

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": f"*{title}*\n{message}",
            "parse_mode": "Markdown",
        }
        resp = self._client.post(url, json=payload)
        resp.raise_for_status()

    def _send_webhook(
        self,
        ch: dict,
        event_type: str,
        title: str,
        message: str,
        severity: str,
    ) -> None:
        """Send via generic HTTP webhook."""
        url = self._resolve_env(ch.get("url", ""))
        if not url:
            raise ValueError("Webhook url not configured")

        method = ch.get("method", "POST").upper()
        headers = ch.get("headers", {})
        payload = {
            "event_type": event_type,
            "title": title,
            "message": message,
            "severity": severity,
        }

        if method == "POST":
            resp = self._client.post(url, json=payload, headers=headers)
        else:
            resp = self._client.request(method, url, json=payload, headers=headers)
        resp.raise_for_status()

    def update_channels(self, channels: list[dict]) -> None:
        """Update notification channels in memory."""
        self._config["channels"] = channels

    def reload_config(self) -> None:
        """Reload configuration from disk."""
        self._config = self._load_config()
