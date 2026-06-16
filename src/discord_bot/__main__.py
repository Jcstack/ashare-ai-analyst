"""Entry point: ``python -m src.discord_bot``."""

from __future__ import annotations

from src.discord_bot.bot import AShareAnalystBot
from src.discord_bot.config import load_discord_config
from src.utils.logger import get_logger

logger = get_logger("discord")


def main() -> None:
    cfg = load_discord_config()
    bot = AShareAnalystBot(config=cfg)
    logger.info("Starting A-Share Analyst Discord Bot …")
    bot.run(cfg["_resolved"]["token"], log_handler=None)


if __name__ == "__main__":
    main()
