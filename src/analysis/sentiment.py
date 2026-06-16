"""AI-powered news sentiment analysis using LLM router.

Classifies stock news items as positive/negative/neutral using the
cheapest available LLM model via cost-based routing.

Per PRD v2.0 FR-NF003.
"""

import json
import re
from typing import Any

from src.llm.base import LLMMessage, LLMProviderError
from src.llm.router import LLMRouter, RoutingStrategy
from src.utils.logger import get_logger

logger = get_logger("analysis.sentiment")


class SentimentAnalyzer:
    """LLM-powered news sentiment classifier.

    Uses the cheapest available model to classify news sentiment,
    with batch processing to minimize API calls.

    Args:
        router: LLM router instance for API calls.
    """

    def __init__(self, router: LLMRouter | None = None) -> None:
        self._router = router or LLMRouter()

    def analyze_batch(
        self,
        news_items: list[dict[str, Any]],
        symbol: str = "",
    ) -> dict[str, Any]:
        """Analyze sentiment for a batch of news items.

        Args:
            news_items: List of news dicts with 'title' and optional 'content'.
            symbol: Stock symbol for context.

        Returns:
            Dict with overall sentiment, per-item classifications, and counts.
        """
        if not news_items:
            return {
                "overall": "neutral",
                "positive_count": 0,
                "negative_count": 0,
                "neutral_count": 0,
                "total_count": 0,
                "score": 0.0,
                "items": [],
                "summary": None,
            }

        # Build batch prompt
        news_text = "\n".join(
            f"{i + 1}. {item.get('title', '无标题')}"
            for i, item in enumerate(news_items[:20])
        )

        messages = [
            LLMMessage(
                role="system",
                content=(
                    "你是金融新闻情感分析师。对每条新闻判断对股价的影响。\n"
                    "严格按照JSON格式输出：\n"
                    "```json\n"
                    "{\n"
                    '  "overall": "positive | negative | neutral",\n'
                    '  "score": -1.0 ~ 1.0,\n'
                    '  "items": [\n'
                    '    {"index": 1, "sentiment": "positive|negative|neutral", "impact": "high|medium|low"}\n'
                    "  ],\n"
                    '  "summary": "一句话总结情感倾向"\n'
                    "}\n"
                    "```"
                ),
            ),
            LLMMessage(
                role="user",
                content=(
                    f"股票: {symbol}\n\n"
                    f"新闻列表:\n{news_text}\n\n"
                    "请分析每条新闻对该股票的情感倾向。"
                ),
            ),
        ]

        try:
            response = self._router.complete(
                messages=messages,
                caller="sentiment_analyzer.analyze_batch",
                strategy=RoutingStrategy.COST,
                max_tokens=1024,
                temperature=0.1,
                symbol=symbol,
                analysis_type="sentiment",
            )
            result = self._parse_response(response.text, len(news_items))
            return result
        except (LLMProviderError, Exception) as exc:
            logger.error("Sentiment analysis failed for %s: %s", symbol, exc)
            return {
                "overall": "neutral",
                "positive_count": 0,
                "negative_count": 0,
                "neutral_count": 0,
                "total_count": len(news_items),
                "score": 0.0,
                "items": [],
                "summary": None,
            }

    def classify_news_impact(self, news_item: dict[str, Any]) -> dict[str, Any]:
        """Classify a single news item's sentiment and impact.

        Args:
            news_item: Dict with 'title' and optional 'content'.

        Returns:
            Dict with sentiment and impact_level.
        """
        result = self.analyze_batch([news_item])
        if result["items"]:
            return result["items"][0]
        return {"sentiment": "neutral", "impact": "low"}

    def _parse_response(self, text: str, total_items: int) -> dict[str, Any]:
        """Parse sentiment analysis JSON response."""
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        json_str = match.group(1).strip() if match else text.strip()
        if not json_str.startswith("{"):
            match2 = re.search(r"\{[\s\S]*\}", json_str)
            json_str = match2.group(0) if match2 else json_str

        try:
            data = json.loads(json_str)
            items = data.get("items", [])
            pos = sum(1 for i in items if i.get("sentiment") == "positive")
            neg = sum(1 for i in items if i.get("sentiment") == "negative")
            neu = total_items - pos - neg
            data["positive_count"] = pos
            data["negative_count"] = neg
            data["neutral_count"] = neu
            data["total_count"] = total_items
            return data
        except json.JSONDecodeError:
            logger.warning("Failed to parse sentiment response")
            return {
                "overall": "neutral",
                "positive_count": 0,
                "negative_count": 0,
                "neutral_count": 0,
                "total_count": total_items,
                "score": 0.0,
                "items": [],
                "summary": None,
            }
