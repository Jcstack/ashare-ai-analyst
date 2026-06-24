"""JSON REST API v1 — aggregates all sub-routers under /api/v1.

Mounts alongside the existing Jinja2/htmx routes with no conflicts.
"""

from fastapi import APIRouter

from src.web.routes.api_v1 import (
    action_queue,
    admin,
    advisor,
    agent,
    agent_loop,
    ai_news,
    backtest,
    bootstrap,
    capital,
    capital_flow,
    chat,
    concept,
    conversation,
    global_market,
    holiday_research,
    intel_reports,
    intelligence,
    intelligence_hub,
    market,
    market_intelligence,
    messages,
    news,
    notifications,
    performance,
    portfolio,
    predictions,
    prompts,
    regime,
    review,
    scheduler,
    search,
    sentiment,
    settings,
    stocks,
    strategy_lab,
    theses,
    trades,
    user_config,
)

router = APIRouter(prefix="/api/v1")

router.include_router(stocks.router)
router.include_router(search.router, prefix="/stocks")
router.include_router(market.router, prefix="/market")
router.include_router(predictions.router)
router.include_router(backtest.router)
router.include_router(portfolio.router)
router.include_router(news.router)
router.include_router(agent.router)
router.include_router(conversation.router)
router.include_router(notifications.router, prefix="/notifications")
router.include_router(admin.router, prefix="/admin")
router.include_router(settings.router, prefix="/settings")
router.include_router(strategy_lab.router, prefix="/strategy-lab")
router.include_router(prompts.router, prefix="/prompts")
router.include_router(global_market.router, prefix="/global-market")
router.include_router(advisor.router, prefix="/advisor")
router.include_router(holiday_research.router, prefix="/advisor/holiday-research")
router.include_router(sentiment.router, prefix="/sentiment")
router.include_router(scheduler.router, prefix="/scheduler")
router.include_router(concept.router)
router.include_router(chat.router, prefix="/chat")
router.include_router(trades.router)
router.include_router(capital.router, prefix="/capital")
router.include_router(user_config.router, prefix="/user")
router.include_router(market_intelligence.router, prefix="/market-intelligence")
router.include_router(intelligence.router, prefix="/intelligence")
router.include_router(intelligence_hub.router, prefix="/intelligence-hub")
router.include_router(intel_reports.router)
router.include_router(capital_flow.router, prefix="/capital-flow")
router.include_router(theses.router)
router.include_router(agent_loop.router)
router.include_router(messages.router, prefix="/messages")
router.include_router(performance.router, prefix="/performance")
router.include_router(action_queue.router, prefix="/actions")
router.include_router(bootstrap.router)
router.include_router(regime.router)
router.include_router(review.router)
router.include_router(ai_news.router, prefix="/ai-news")
