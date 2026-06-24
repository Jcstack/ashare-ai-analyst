"""Eagerly initialise DI singletons for the bot process.

Calling ``init_services()`` ensures all lazily-cached services are warmed
up before the first slash command arrives.  This is a blocking call — run
it via ``asyncio.to_thread()`` from the bot's ``setup_hook``.
"""

from __future__ import annotations

from src.utils.logger import get_logger

logger = get_logger("discord.services")


def init_services() -> None:
    """Touch every DI singleton the bot needs.

    Importing is deferred so that the heavy modules load inside the
    thread pool rather than at import time.
    """
    from src.web.dependencies import (
        get_agent_service,
        get_capital_flow_service,
        get_concept_board_service,
        get_conversation_service,
        get_global_market_fetcher,
        get_intelligence_hub_service,
        get_market_service,
        get_portfolio_service,
        get_realtime_analyzer,
        get_realtime_quote_manager,
        get_redis,
        get_sentiment_report_generator,
        get_sentiment_service,
        get_stock_service,
        get_strategy_context_service,
        get_symbol_extractor,
        get_watchlist_service,
    )

    singletons = {
        "redis": get_redis,
        "realtime_quote_manager": get_realtime_quote_manager,
        "stock_service": get_stock_service,
        "market_service": get_market_service,
        "realtime_analyzer": get_realtime_analyzer,
        "intelligence_hub_service": get_intelligence_hub_service,
        "capital_flow_service": get_capital_flow_service,
        "conversation_service": get_conversation_service,
        "agent_service": get_agent_service,
        "portfolio_service": get_portfolio_service,
        "sentiment_report_generator": get_sentiment_report_generator,
        "sentiment_service": get_sentiment_service,
        "global_market_fetcher": get_global_market_fetcher,
        "concept_board_service": get_concept_board_service,
        "watchlist_service": get_watchlist_service,
        "strategy_context_service": get_strategy_context_service,
        "symbol_extractor": get_symbol_extractor,
    }

    for name, factory in singletons.items():
        try:
            factory()
            logger.debug("Initialised %s", name)
        except Exception:
            logger.warning("Failed to initialise %s", name, exc_info=True)

    logger.info("DI singletons initialised for Discord bot")
