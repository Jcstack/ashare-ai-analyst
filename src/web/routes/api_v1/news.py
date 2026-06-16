"""News, anomaly, and research API endpoints.

Per PRD v2.0 FR-NF001, FR-AD001.
Per PRD v2.4 FR-RI004.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, Query

from src.analysis.sentiment import SentimentAnalyzer
from src.data.news_fetcher import NewsFetcher
from src.web.dependencies import get_news_fetcher, get_sentiment_analyzer
from src.web.utils import sanitize_records
from src.web.routes.api_v1.schemas import (
    AnomalyItem,
    HotRankItem,
    ResearchResult,
    SentimentSummary,
    StockNewsItem,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["news"])


@router.get("/stock/{symbol}/news", response_model=list[StockNewsItem])
async def get_stock_news(
    symbol: str,
    limit: int = Query(20, ge=1, le=100, description="Max news items"),
    fetcher: NewsFetcher = Depends(get_news_fetcher),
) -> list[dict]:
    """Get recent news for a stock."""
    df = fetcher.fetch_stock_news(symbol)
    records = df.head(limit).to_dict(orient="records")
    return sanitize_records(records)


@router.get("/stock/{symbol}/anomalies", response_model=list[AnomalyItem])
async def get_stock_anomalies(
    symbol: str,
    fetcher: NewsFetcher = Depends(get_news_fetcher),
) -> list[dict]:
    """Get unusual trading activity for a stock."""
    df = fetcher.fetch_stock_anomalies(symbol)
    records = df.to_dict(orient="records")
    return sanitize_records(records)


@router.get("/stock/{symbol}/sentiment", response_model=SentimentSummary)
async def get_stock_sentiment(
    symbol: str,
    fetcher: NewsFetcher = Depends(get_news_fetcher),
    analyzer: SentimentAnalyzer = Depends(get_sentiment_analyzer),
) -> dict:
    """Get AI-powered news sentiment analysis for a stock."""

    df = fetcher.fetch_stock_news(symbol)
    if df.empty:
        return {
            "symbol": symbol,
            "overall": "neutral",
            "positive_count": 0,
            "negative_count": 0,
            "neutral_count": 0,
            "total_count": 0,
            "score": 0.0,
            "summary": None,
        }

    news_items = df.to_dict(orient="records")
    result = analyzer.analyze_batch(news_items, symbol=symbol)
    result["symbol"] = symbol
    return result


@router.get("/stock/{symbol}/research", response_model=ResearchResult)
async def get_stock_research(
    symbol: str,
    fetcher: NewsFetcher = Depends(get_news_fetcher),
    analyzer: SentimentAnalyzer = Depends(get_sentiment_analyzer),
) -> dict:
    """Get aggregated research data: news + sentiment + fund holdings + analyst ratings.

    Per PRD v2.4 FR-RI004.
    """

    research = await asyncio.to_thread(fetcher.fetch_stock_research, symbol)

    # Add sentiment analysis
    sentiment = None
    news_items = research.get("news", [])
    if news_items:
        try:
            sentiment_result = analyzer.analyze_batch(news_items, symbol=symbol)
            sentiment_result["symbol"] = symbol
            sentiment = sentiment_result
        except Exception:
            logger.warning("Sentiment analysis failed for research %s", symbol)

    # Clean NaN in nested dicts
    for key in ("news", "fund_holdings", "analyst_ratings"):
        sanitize_records(research.get(key, []))

    return {
        "symbol": symbol,
        "news": research.get("news", []),
        "sentiment": sentiment,
        "fund_holdings": research.get("fund_holdings", []),
        "analyst_ratings": research.get("analyst_ratings", []),
    }


@router.get("/market/hot-rank", response_model=list[HotRankItem])
async def get_hot_rank(
    fetcher: NewsFetcher = Depends(get_news_fetcher),
) -> list[dict]:
    """Get hot stock rankings."""
    df = fetcher.fetch_hot_rank()
    records = df.to_dict(orient="records")
    return sanitize_records(records)
