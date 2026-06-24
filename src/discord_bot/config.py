"""Load and validate Discord bot configuration."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("discord.config")

# 5-channel alert terminal structure
CHANNELS: dict[str, str] = {
    "trading_alerts": "trading-alerts",
    "risk_alerts": "risk-alerts",
    "morning_brief": "morning-brief",
    "close_review": "close-review",
    "system_health": "system-health",
}


@lru_cache(maxsize=1)
def get_discord_config() -> dict[str, Any]:
    """Return the raw discord.yaml config (cached)."""
    return load_config("discord")


def get_timeout(key: str, default: int = 300) -> int:
    """Read a timeout value from ``config/discord.yaml`` rate_limits section."""
    cfg = get_discord_config()
    return cfg.get("rate_limits", {}).get(key, default)


def get_channel_names() -> dict[str, str]:
    """Return channel key → channel name mapping.

    Reads from ``config/discord.yaml`` channels section, falling back to
    the ``CHANNELS`` default if a key is missing.
    """
    cfg = get_discord_config()
    channels_cfg = cfg.get("channels", {})
    result = CHANNELS.copy()
    for key in CHANNELS:
        if key in channels_cfg:
            result[key] = channels_cfg[key]
    return result


def load_discord_config() -> dict[str, Any]:
    """Load config/discord.yaml and resolve env-var references.

    Returns:
        Validated config dict with resolved token, guild_id, channel_id.

    Raises:
        ValueError: If required env vars are missing.
    """
    cfg = load_config("discord")

    token = os.environ.get(cfg["bot"]["token_env"], "")
    if not token:
        raise ValueError(
            f"Missing env var {cfg['bot']['token_env']} — set DISCORD_BOT_TOKEN"
        )

    guild_id_str = os.environ.get(cfg["guild"]["id_env"], "")
    if not guild_id_str:
        raise ValueError(
            f"Missing env var {cfg['guild']['id_env']} — set DISCORD_GUILD_ID"
        )

    channel_id_str = os.environ.get(cfg["channel"]["id_env"], "")
    if not channel_id_str:
        raise ValueError(
            f"Missing env var {cfg['channel']['id_env']} — set DISCORD_CHANNEL_ID"
        )

    cfg["_resolved"] = {
        "token": token,
        "guild_id": int(guild_id_str),
        "channel_id": int(channel_id_str),
    }

    logger.info(
        "Discord config loaded: guild=%s, channel=%s",
        guild_id_str,
        channel_id_str,
    )
    return cfg
