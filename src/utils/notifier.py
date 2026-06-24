"""Discord webhook notification for the A-share analysis system.

Sends formatted Discord embeds for analysis alerts, daily summaries,
and error notifications. All configuration is loaded from
config/notification.yaml per the config-driven design principle.
"""

import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Discord webhook URL pattern: https://discord.com/api/webhooks/{id}/{token}
_WEBHOOK_URL_RE = re.compile(
    r"^https://discord(?:app)?\.com/api/webhooks/\d{17,20}/[A-Za-z0-9_-]+$"
)

# Common placeholder patterns that should not be treated as real values
_PLACEHOLDER_RE = re.compile(
    r"^x{3,}$|^your[_-]|_here$|^placeholder$|^changeme$", re.IGNORECASE
)


def _is_placeholder_url(url: str) -> bool:
    """Return True if the webhook URL contains placeholder segments."""
    if not url:
        return True
    # Check each path segment of the webhook URL for placeholder patterns
    parts = url.rstrip("/").split("/")
    for part in parts[-2:]:  # Check webhook ID and token segments
        if _PLACEHOLDER_RE.search(part):
            return True
    # Also reject if it doesn't match the expected Discord webhook URL format
    if not _WEBHOOK_URL_RE.match(url):
        return True
    return False


class DiscordNotifier:
    """Sends formatted notifications to Discord via webhooks.

    Supports three notification types:
      - Analysis alerts: per-stock AI prediction results
      - Daily summaries: aggregated results for all analyzed stocks
      - Error alerts: system error notifications

    Configuration is loaded from config/notification.yaml. The webhook
    URL is read from the DISCORD_WEBHOOK_URL environment variable.

    Attributes:
        enabled: Whether Discord notifications are active.
        webhook_url: The Discord webhook endpoint URL.
        config: The parsed discord config section from notification.yaml.
    """

    def __init__(self, config_path: str = "notification") -> None:
        """Initialize the DiscordNotifier.

        Args:
            config_path: Config file name (without .yaml extension) to load
                from config/ directory. Defaults to "notification".
        """
        full_config = load_config(config_path)
        self.config: dict[str, Any] = full_config.get("discord", {})
        self.enabled: bool = self.config.get("enabled", False)
        raw_url: str = os.environ.get("DISCORD_WEBHOOK_URL", "")
        self._webhook_invalid: bool = False
        self._timeout: int = self.config.get("timeout_seconds", 10)
        self._max_retries: int = self.config.get("max_retries", 3)
        self._retry_delay: int = self.config.get("retry_delay_seconds", 2)
        self._templates: dict[str, Any] = self.config.get("templates", {})

        if not raw_url:
            logger.warning(
                "DISCORD_WEBHOOK_URL environment variable is not set. "
                "Discord notifications will be disabled."
            )
            self.webhook_url = ""
        elif _is_placeholder_url(raw_url):
            logger.warning(
                "DISCORD_WEBHOOK_URL is a placeholder or invalid value (%s…). "
                "Discord notifications will be disabled. "
                "Set a real webhook URL to enable notifications.",
                raw_url[:40],
            )
            self.webhook_url = ""
            self._webhook_invalid = True
        else:
            self.webhook_url = raw_url

    def send_analysis_alert(self, symbol: str, prediction: dict) -> bool:
        """Send an analysis alert for a single stock prediction.

        Builds a Discord embed with the AI prediction details including
        trend, signal, confidence, risk level, target price range,
        and key reasoning points.

        Args:
            symbol: Stock symbol code (e.g., "000001").
            prediction: Prediction result dictionary containing keys:
                - trend (str): e.g., "bullish", "bearish"
                - signal (str): e.g., "buy", "sell", "hold"
                - confidence (float): 0.0 to 1.0
                - risk_level (str): e.g., "low", "medium", "high"
                - target_price_range (dict): {"low": float, "high": float}
                - reasoning (list[str]): key reasoning points
                - key_factors (list[str]): supporting factors
                - risk_warnings (list[str]): risk warnings

        Returns:
            True if the notification was sent successfully, False otherwise.
        """
        template = self._templates.get("analysis_alert", {})
        color = template.get("color", 3447003)
        title = template.get("title_template", "{symbol} — AI分析预警").format(
            symbol=symbol
        )

        trend = prediction.get("trend", "N/A")
        signal = prediction.get("signal", "N/A")
        confidence = prediction.get("confidence", 0.0)
        risk_level = prediction.get("risk_level", "N/A")
        target_range = prediction.get("target_price_range", {})
        reasoning = prediction.get("reasoning", [])
        key_factors = prediction.get("key_factors", [])
        risk_warnings = prediction.get("risk_warnings", [])

        target_str = (
            f"{target_range.get('low', 'N/A')} — {target_range.get('high', 'N/A')}"
            if target_range
            else "N/A"
        )

        fields = [
            {"name": "趋势", "value": trend, "inline": True},
            {"name": "信号", "value": signal, "inline": True},
            {"name": "置信度", "value": f"{confidence:.0%}", "inline": True},
            {"name": "风险等级", "value": risk_level, "inline": True},
            {"name": "目标价格区间", "value": target_str, "inline": True},
            {
                "name": "关键推理",
                "value": "\n".join(f"• {r}" for r in reasoning) or "N/A",
                "inline": False,
            },
            {
                "name": "关键因素",
                "value": "\n".join(f"• {f}" for f in key_factors) or "N/A",
                "inline": False,
            },
            {
                "name": "风险提示",
                "value": "\n".join(f"• {w}" for w in risk_warnings) or "N/A",
                "inline": False,
            },
        ]

        description = f"股票代码: {symbol}"
        embed = self._build_embed(
            title=title,
            description=description,
            color=color,
            fields=fields,
        )
        payload = {"embeds": [embed]}
        return self._post_webhook(payload)

    def send_daily_summary(self, results: list[dict]) -> bool:
        """Send a daily summary of all analyzed stocks.

        Builds a Discord embed summarizing analysis results for
        multiple stocks in a single notification.

        Args:
            results: List of prediction result dicts, each containing
                at minimum: symbol (str), signal (str), confidence (float).

        Returns:
            True if the notification was sent successfully, False otherwise.
        """
        template = self._templates.get("daily_summary", {})
        color = template.get("color", 5763719)
        today_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        title = template.get("title_template", "每日分析摘要 — {date}").format(
            date=today_str
        )

        fields = []
        for result in results:
            symbol = result.get("symbol", "N/A")
            signal = result.get("signal", "N/A")
            confidence = result.get("confidence", 0.0)
            fields.append(
                {
                    "name": symbol,
                    "value": f"信号: {signal} | 置信度: {confidence:.0%}",
                    "inline": True,
                }
            )

        description = f"共分析 {len(results)} 只股票"
        embed = self._build_embed(
            title=title,
            description=description,
            color=color,
            fields=fields,
        )
        payload = {"embeds": [embed]}
        return self._post_webhook(payload)

    def send_error_alert(self, error_msg: str) -> bool:
        """Send an error alert notification.

        Args:
            error_msg: The error message or description to include.

        Returns:
            True if the notification was sent successfully, False otherwise.
        """
        template = self._templates.get("error_alert", {})
        color = template.get("color", 15548997)
        title = template.get("title_template", "系统错误告警")

        timestamp_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        fields = [
            {"name": "错误信息", "value": error_msg, "inline": False},
            {"name": "发生时间", "value": timestamp_str, "inline": True},
        ]

        embed = self._build_embed(
            title=title,
            description="系统运行过程中发生错误",
            color=color,
            fields=fields,
        )
        payload = {"embeds": [embed]}
        return self._post_webhook(payload)

    def _post_webhook(self, payload: dict) -> bool:
        """Post a payload to the Discord webhook URL with retry logic.

        Retries on 5xx server errors with exponential backoff. Does not
        retry on 4xx client errors. Returns early if notifications are
        disabled or the webhook URL is not configured.

        Args:
            payload: The JSON payload to send to the Discord webhook.

        Returns:
            True if the webhook returned HTTP 204 (success), False otherwise.
        """
        if not self.enabled:
            logger.info("Discord notifications are disabled. Skipping send.")
            return False

        if not self.webhook_url:
            # Only log at debug level if we already warned at startup
            if self._webhook_invalid:
                logger.debug(
                    "Skipping Discord send — webhook URL is placeholder/invalid."
                )
            else:
                logger.warning("No webhook URL configured. Cannot send notification.")
            return False

        last_exception: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                response = requests.post(
                    self.webhook_url,
                    json=payload,
                    timeout=self._timeout,
                )

                if response.status_code == 204:
                    logger.info(
                        "Discord notification sent successfully (attempt %d/%d).",
                        attempt,
                        self._max_retries,
                    )
                    return True

                if 400 <= response.status_code < 500:
                    logger.error(
                        "Discord webhook returned client error %d: %s. Not retrying.",
                        response.status_code,
                        response.text,
                    )
                    return False

                # 5xx server error — retry
                logger.warning(
                    "Discord webhook returned %d (attempt %d/%d). Retrying.",
                    response.status_code,
                    attempt,
                    self._max_retries,
                )

            except requests.exceptions.ConnectionError as exc:
                logger.error(
                    "Connection error sending Discord notification (attempt %d/%d): %s",
                    attempt,
                    self._max_retries,
                    exc,
                )
                last_exception = exc

            except requests.exceptions.Timeout as exc:
                logger.error(
                    "Timeout sending Discord notification (attempt %d/%d): %s",
                    attempt,
                    self._max_retries,
                    exc,
                )
                last_exception = exc

            except requests.exceptions.RequestException as exc:
                logger.error(
                    "Request error sending Discord notification (attempt %d/%d): %s",
                    attempt,
                    self._max_retries,
                    exc,
                )
                last_exception = exc

            # Exponential backoff before next retry
            if attempt < self._max_retries:
                delay = self._retry_delay * (2 ** (attempt - 1))
                logger.debug("Waiting %d seconds before retry.", delay)
                time.sleep(delay)

        logger.error(
            "Failed to send Discord notification after %d attempts.%s",
            self._max_retries,
            f" Last error: {last_exception}" if last_exception else "",
        )
        return False

    def _build_embed(
        self,
        title: str,
        description: str,
        color: int,
        fields: list[dict] | None = None,
    ) -> dict:
        """Build a standard Discord embed dictionary.

        Args:
            title: The embed title text.
            description: The embed description text.
            color: The embed sidebar color as an integer.
            fields: Optional list of field dicts, each with keys:
                - name (str): field name
                - value (str): field value
                - inline (bool): whether to display inline

        Returns:
            A Discord embed dictionary ready for inclusion in a webhook
            payload.
        """
        embed: dict[str, Any] = {
            "title": title,
            "description": description,
            "color": color,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "footer": {
                "text": "A股智能分析系统",
            },
        }
        if fields:
            embed["fields"] = fields
        return embed
