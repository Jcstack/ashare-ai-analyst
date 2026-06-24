"""Wire Digest Agent — Sentinel Team member for global market pulse summaries.

Generates periodic global market pulse summaries by combining price data
with recent news events. Uses LLM to create human-readable digests.

Per PRD v39.0 FR-GIT005.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from functools import lru_cache

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("intelligence.agents.wire_digest")


@dataclass
class MarketPulse:
    """A global market pulse snapshot with narrative."""

    timestamp: str
    indices: list[dict[str, Any]] = field(default_factory=list)
    commodities: list[dict[str, Any]] = field(default_factory=list)
    currencies: list[dict[str, Any]] = field(default_factory=list)
    bond_yields: dict[str, float] = field(default_factory=dict)
    digest_text: str = ""  # LLM-generated summary

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "indices": self.indices,
            "commodities": self.commodities,
            "currencies": self.currencies,
            "bond_yields": self.bond_yields,
            "digest_text": self.digest_text,
        }


class WireDigestAgent:
    """Sentinel team: generates periodic global market pulse digests.

    Combines GlobalMarketFetcher data with recent news to produce
    human-readable market summaries every 30 minutes.
    """

    DIGEST_SYSTEM_PROMPT = (
        "You are a global market observer. Summarize current global market dynamics "
        "in concise Chinese, focusing on changes that impact A-shares. "
        "Avoid financial jargon — use plain language. "
        "Limit to 200 Chinese characters. Output in Chinese."
    )

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        global_market_fetcher: Any | None = None,
        llm_router: Any | None = None,
        message_store: Any | None = None,
    ) -> None:
        self._config = config or self._load_config()
        self._global_market = global_market_fetcher
        self._llm_router = llm_router
        self._message_store = message_store
        self._last_digest_ts: float = 0.0
        self._digest_interval = (
            self._config.get("messenger", {})
            .get("digest", {})
            .get("interval_seconds", 1800)
        )
        logger.info("WireDigestAgent initialized")

    @staticmethod
    def _load_config() -> dict[str, Any]:
        try:
            return load_config("global_intelligence")
        except FileNotFoundError:
            return {}

    def generate_pulse(self, recent_news: list[dict] | None = None) -> MarketPulse:
        """Generate a global market pulse snapshot.

        Args:
            recent_news: Optional list of recent news items for context.

        Returns:
            MarketPulse with market data and optional LLM digest.
        """
        pulse = MarketPulse(
            timestamp=datetime.now(UTC).isoformat(),
        )

        # Fetch global market data
        if self._global_market:
            try:
                snapshot = self._global_market.fetch_global_snapshot()
                pulse.indices = snapshot.get("indices", [])
                pulse.commodities = snapshot.get("commodities", [])
                pulse.currencies = snapshot.get("currencies", [])
            except Exception as exc:
                logger.warning("Global market fetch failed: %s", exc)

            try:
                pulse.bond_yields = self._global_market.fetch_bond_yields()
            except Exception as exc:
                logger.warning("Bond yield fetch failed: %s", exc)

        # Generate LLM digest if router available
        if self._llm_router:
            try:
                digest = self._generate_digest(pulse, recent_news)
                pulse.digest_text = digest
            except Exception as exc:
                logger.warning("Digest generation failed: %s", exc)

        return pulse

    def generate_and_store(
        self,
        recent_news: list[dict] | None = None,
    ) -> MarketPulse:
        """Generate pulse and store as message.

        Returns:
            MarketPulse object.
        """
        pulse = self.generate_pulse(recent_news)

        # Store in MessageStore
        if self._message_store and pulse.digest_text:
            try:
                self._message_store.create_message(
                    msg_type="global_pulse",
                    title="全球市场脉搏",
                    summary=pulse.digest_text,
                    content=pulse.digest_text,
                    priority="normal",
                    post_market_data={
                        "indices": pulse.indices,
                        "commodities": pulse.commodities,
                        "bond_yields": pulse.bond_yields,
                    },
                )
                logger.info("Stored global_pulse message")
            except Exception as exc:
                logger.warning("Failed to store pulse message: %s", exc)

        self._last_digest_ts = time.monotonic()
        return pulse

    def _generate_digest(
        self,
        pulse: MarketPulse,
        recent_news: list[dict] | None = None,
    ) -> str:
        """Generate LLM digest from market data and news."""
        # Build prompt
        parts = ["当前全球市场数据：\n"]

        # Indices
        if pulse.indices:
            parts.append("主要指数：")
            for idx in pulse.indices:
                name = idx.get("name", idx.get("symbol", "?"))
                pct = idx.get("pct_change")
                price = idx.get("price")
                if pct is not None:
                    direction = "↑" if pct > 0 else "↓" if pct < 0 else "→"
                    parts.append(
                        f"  {name}: {price} ({direction}{abs(pct):.2f}%)",
                    )

        # Commodities
        if pulse.commodities:
            parts.append("\n大宗商品：")
            for c in pulse.commodities:
                name = c.get("name", c.get("symbol", "?"))
                pct = c.get("pct_change")
                price = c.get("price")
                if pct is not None:
                    direction = "↑" if pct > 0 else "↓" if pct < 0 else "→"
                    parts.append(
                        f"  {name}: {price} ({direction}{abs(pct):.2f}%)",
                    )

        # Bond yields
        if pulse.bond_yields:
            parts.append("\n美债收益率：")
            for k, v in pulse.bond_yields.items():
                parts.append(f"  {k}: {v}%")

        # Recent news headlines
        if recent_news:
            parts.append(f"\n最近{len(recent_news)}条新闻标题：")
            for news in recent_news[:10]:
                title = news.get("title", "")
                if title:
                    parts.append(f"  - {title}")

        prompt = "\n".join(parts)

        model = (
            self._config.get("messenger", {})
            .get("digest", {})
            .get("model", "deepseek-chat")
        )
        max_tokens = (
            self._config.get("messenger", {}).get("digest", {}).get("max_tokens", 800)
        )

        try:
            response = self._llm_router.generate(
                model=model,
                system=self.DIGEST_SYSTEM_PROMPT,
                prompt=prompt,
                max_tokens=max_tokens,
            )
            return response if isinstance(response, str) else str(response)
        except Exception as exc:
            logger.warning("LLM digest generation failed: %s", exc)
            # Fallback: generate a simple text summary
            return self._fallback_digest(pulse)

    @staticmethod
    def _fallback_digest(pulse: MarketPulse) -> str:
        """Generate a simple text summary without LLM."""
        parts = []

        # Find biggest movers
        movers = []
        for idx in pulse.indices:
            pct = idx.get("pct_change")
            if pct is not None and abs(pct) > 1.0:
                name = idx.get("name", idx.get("symbol", "?"))
                direction = "涨" if pct > 0 else "跌"
                movers.append(f"{name}{direction}{abs(pct):.1f}%")

        for c in pulse.commodities:
            pct = c.get("pct_change")
            if pct is not None and abs(pct) > 2.0:
                name = c.get("name", c.get("symbol", "?"))
                direction = "涨" if pct > 0 else "跌"
                movers.append(f"{name}{direction}{abs(pct):.1f}%")

        if movers:
            parts.append(f"主要异动: {', '.join(movers[:5])}")
        else:
            parts.append("全球市场整体平稳")

        if pulse.bond_yields:
            us_10y = pulse.bond_yields.get("US_10Y")
            us_2y = pulse.bond_yields.get("US_2Y")
            if us_10y and us_2y:
                spread_val = us_10y - us_2y
                if spread_val < 0:
                    parts.append(
                        f"美债收益率曲线倒挂(利差{spread_val:.2f}%)",
                    )

        return "。".join(parts) + "。" if parts else "暂无市场数据。"

    def should_run(self) -> bool:
        """Check if enough time has passed since last digest."""
        if self._last_digest_ts == 0:
            return True
        return (time.monotonic() - self._last_digest_ts) >= self._digest_interval


# ---------------------------------------------------------------------------
# DI singleton
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_wire_digest_agent() -> WireDigestAgent:
    from src.web.dependencies import (
        get_global_market_fetcher,
        get_llm_router,
        get_message_store,
    )

    return WireDigestAgent(
        config=load_config("global_intelligence"),
        global_market_fetcher=get_global_market_fetcher(),
        llm_router=get_llm_router(),
        message_store=get_message_store(),
    )
