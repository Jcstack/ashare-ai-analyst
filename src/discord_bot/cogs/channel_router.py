"""Routes alerts to the correct Discord channel in a 5-channel structure.

Channel mapping:
    #trading-alerts  — Actionable signals (buy/sell/reduce)
    #risk-alerts     — Risk warnings, thesis invalidations, regime changes
    #morning-brief   — 08:00 daily plan
    #close-review    — 15:30 daily review
    #system-health   — Data source status, LLM failures
"""

from __future__ import annotations

import time
from typing import Any

import discord
from discord.ext import commands

from src.discord_bot.embeds.briefing_embed import (
    build_close_review_embed,
    build_morning_brief_embed,
)
from src.discord_bot.embeds.risk_alert_embed import (
    build_generic_risk_embed,
    build_regime_change_embed,
    build_thesis_invalidation_embed,
)
from src.discord_bot.embeds.trading_signal_embed import build_trading_signal_embed
from src.utils.logger import get_logger

logger = get_logger("discord.cogs.channel_router")

# Channel config keys matching config/discord.yaml → channels
CHANNEL_KEYS = (
    "trading_alerts",
    "risk_alerts",
    "morning_brief",
    "close_review",
    "system_health",
)

# Default channel name mapping (overridden by config/discord.yaml)
_DEFAULT_CHANNEL_NAMES: dict[str, str] = {
    "trading_alerts": "trading-alerts",
    "risk_alerts": "risk-alerts",
    "morning_brief": "morning-brief",
    "close_review": "close-review",
    "system_health": "system-health",
}


class ChannelRouter(commands.Cog):
    """Routes alerts to the correct Discord channel."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._channel_cache: dict[str, discord.TextChannel] = {}
        self._channel_names: dict[str, str] = _DEFAULT_CHANNEL_NAMES.copy()

        # Load channel names from config
        from src.discord_bot.config import get_discord_config

        cfg = get_discord_config()
        channels_cfg = cfg.get("channels", {})
        for key in CHANNEL_KEYS:
            if key in channels_cfg:
                self._channel_names[key] = channels_cfg[key]

        # Rate limiting
        alert_cfg = cfg.get("alert_cooldown_seconds", 60)
        self._cooldown_seconds: int = int(alert_cfg)
        self._max_per_hour: int = int(cfg.get("max_alerts_per_hour", 20))
        self._last_alert_time: dict[str, float] = {}
        self._hourly_counts: dict[str, list[float]] = {}

    # ------------------------------------------------------------------
    # Channel resolution
    # ------------------------------------------------------------------

    def _get_guild(self) -> discord.Guild | None:
        """Get the configured guild."""
        from src.discord_bot.bot import AShareAnalystBot

        bot: AShareAnalystBot = self.bot  # type: ignore[assignment]
        return self.bot.get_guild(bot._guild_id)

    def _get_channel(self, key: str) -> discord.TextChannel | None:
        """Resolve a channel key to a Discord TextChannel.

        Looks up by channel name within the configured guild.
        Caches resolved channels for subsequent calls.
        """
        if key in self._channel_cache:
            return self._channel_cache[key]

        guild = self._get_guild()
        if guild is None:
            logger.warning("Guild not found — cannot resolve channel %s", key)
            return None

        channel_name = self._channel_names.get(key)
        if not channel_name:
            logger.warning("No channel name configured for key %s", key)
            return None

        # Search by name
        for ch in guild.text_channels:
            if ch.name == channel_name:
                self._channel_cache[key] = ch
                logger.info("Resolved channel %s → #%s (id=%s)", key, ch.name, ch.id)
                return ch

        logger.warning(
            "Channel #%s not found in guild %s for key %s",
            channel_name,
            guild.name,
            key,
        )
        return None

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _check_rate_limit(self, key: str) -> bool:
        """Return True if the alert should be sent (not rate-limited)."""
        now = time.monotonic()

        # Per-channel cooldown
        last = self._last_alert_time.get(key, 0)
        if now - last < self._cooldown_seconds:
            logger.debug("Rate-limited: %s (cooldown)", key)
            return False

        # Hourly cap
        timestamps = self._hourly_counts.get(key, [])
        # Prune old entries
        cutoff = now - 3600
        timestamps = [t for t in timestamps if t > cutoff]
        if len(timestamps) >= self._max_per_hour:
            logger.debug("Rate-limited: %s (hourly cap)", key)
            return False

        timestamps.append(now)
        self._hourly_counts[key] = timestamps
        self._last_alert_time[key] = now
        return True

    # ------------------------------------------------------------------
    # Public push methods
    # ------------------------------------------------------------------

    async def push_trading_signal(self, action_item: dict[str, Any]) -> bool:
        """Push an actionable trading signal to #trading-alerts.

        Returns True if the message was sent successfully.
        """
        if not self._check_rate_limit("trading_alerts"):
            return False

        channel = self._get_channel("trading_alerts")
        if channel is None:
            # Fall back to default push channel
            channel = await self._fallback_channel()
        if channel is None:
            logger.warning("No channel available for trading signal")
            return False

        embed = build_trading_signal_embed(action_item)
        await channel.send(embed=embed)
        logger.info("Pushed trading signal to #%s", channel.name)
        return True

    async def push_risk_alert(self, alert_type: str, data: dict[str, Any]) -> bool:
        """Push a risk alert to #risk-alerts.

        Args:
            alert_type: One of ``thesis_invalidation``, ``regime_change``,
                        or ``generic``.
            data: Alert payload.

        Returns True if the message was sent successfully.
        """
        if not self._check_rate_limit("risk_alerts"):
            return False

        channel = self._get_channel("risk_alerts")
        if channel is None:
            channel = await self._fallback_channel()
        if channel is None:
            logger.warning("No channel available for risk alert")
            return False

        if alert_type == "thesis_invalidation":
            embed = build_thesis_invalidation_embed(data)
        elif alert_type == "regime_change":
            old_phase = data.get("old_phase", "?")
            new_phase = data.get("new_phase", "?")
            embed = build_regime_change_embed(old_phase, new_phase, data)
        else:
            embed = build_generic_risk_embed(data)

        await channel.send(embed=embed)
        logger.info("Pushed %s risk alert to #%s", alert_type, channel.name)
        return True

    async def push_morning_brief(self, plan: dict[str, Any]) -> bool:
        """Push morning brief to #morning-brief.

        Returns True if the message was sent successfully.
        """
        channel = self._get_channel("morning_brief")
        if channel is None:
            channel = await self._fallback_channel()
        if channel is None:
            logger.warning("No channel available for morning brief")
            return False

        embed = build_morning_brief_embed(plan)
        await channel.send(embed=embed)
        logger.info("Pushed morning brief to #%s", channel.name)
        return True

    async def push_close_review(self, review: dict[str, Any]) -> bool:
        """Push close review to #close-review.

        Returns True if the message was sent successfully.
        """
        channel = self._get_channel("close_review")
        if channel is None:
            channel = await self._fallback_channel()
        if channel is None:
            logger.warning("No channel available for close review")
            return False

        embed = build_close_review_embed(review)
        await channel.send(embed=embed)
        logger.info("Pushed close review to #%s", channel.name)
        return True

    async def push_system_health(self, status: dict[str, Any]) -> bool:
        """Push system health status to #system-health.

        Returns True if the message was sent successfully.
        """
        if not self._check_rate_limit("system_health"):
            return False

        channel = self._get_channel("system_health")
        if channel is None:
            channel = await self._fallback_channel()
        if channel is None:
            logger.warning("No channel available for system health")
            return False

        embed = self._build_system_health_embed(status)
        await channel.send(embed=embed)
        logger.info("Pushed system health to #%s", channel.name)
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _fallback_channel(self) -> discord.TextChannel | None:
        """Fall back to the legacy single push channel."""
        from src.discord_bot.bot import AShareAnalystBot

        bot: AShareAnalystBot = self.bot  # type: ignore[assignment]
        return await bot.get_push_channel()

    @staticmethod
    def _build_system_health_embed(status: dict[str, Any]) -> discord.Embed:
        """Build a system health embed.

        Expected *status* keys:
            title, message, severity, component, details
        """
        severity = str(status.get("severity", "info")).lower()
        color_map = {
            "critical": 0xFF1744,
            "warning": 0xFF9800,
            "info": 0x2196F3,
            "ok": 0x00C853,
        }
        color = color_map.get(severity, 0x9E9E9E)

        severity_emoji = {
            "critical": "\U0001f534",
            "warning": "\U0001f7e0",
            "info": "\U0001f535",
            "ok": "\U0001f7e2",
        }
        emoji = severity_emoji.get(severity, "\u26aa")

        title = status.get("title", "系统状态")
        embed = discord.Embed(
            title=f"{emoji} {title}",
            description=status.get("message", ""),
            color=color,
        )

        component = status.get("component")
        if component:
            embed.add_field(name="组件", value=component, inline=True)

        details = status.get("details")
        if details:
            if isinstance(details, dict):
                detail_lines = [f"{k}: {v}" for k, v in details.items()]
                detail_text = "\n".join(detail_lines)
            else:
                detail_text = str(details)
            embed.add_field(
                name="详情",
                value=detail_text[:1024],
                inline=False,
            )

        embed.set_footer(text="系统监控 | A股分析师")
        return embed


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ChannelRouter(bot))
