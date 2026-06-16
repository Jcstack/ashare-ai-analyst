"""Bridges the intelligence hub to the trading loop (ORIENT phase).

When fresh intel arrives, the bridge scans recent items, maps them to held
positions, evaluates thesis impact via keyword matching, and generates
signals for the decision pipeline.  No LLM calls — purely rule-based for
low-latency integration.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from src.agent_loop.models import AggregatedSignal, SignalDirection, UrgencyTier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Impact keyword sets (Chinese A-share context)
# ---------------------------------------------------------------------------

_POSITIVE_KEYWORDS: list[str] = [
    "利好",
    "增长",
    "上涨",
    "突破",
    "利润",
    "营收增长",
    "政策支持",
    "超预期",
    "回购",
    "增持",
    "分红",
    "扩产",
    "中标",
    "创新高",
    "盈利",
    "大幅增长",
    "签约",
    "获批",
    "订单",
]

_NEGATIVE_KEYWORDS: list[str] = [
    "利空",
    "下跌",
    "亏损",
    "违规",
    "处罚",
    "减持",
    "退市",
    "暴跌",
    "质押",
    "爆仓",
    "诉讼",
    "立案",
    "业绩下滑",
    "预亏",
    "停产",
    "监管",
    "ST",
    "警示",
    "风险",
    "下调",
]

# Conviction adjustment magnitudes
_CONVICTION_BOOST = 0.08
_CONVICTION_REDUCE = -0.10
_INVALIDATION_THRESHOLD = 0.15  # thesis conviction below this → invalidate


class IntelBridge:
    """Bridges intelligence hub -> trading loop.

    Scans recent intel, maps to portfolio positions, evaluates thesis impact,
    and generates signals for the decision pipeline.
    """

    def __init__(
        self,
        info_store: Any = None,
        impact_chain_engine: Any = None,
        thesis_store: Any = None,
        config: dict | None = None,
    ) -> None:
        self._info_store = info_store
        self._impact_chain = impact_chain_engine
        self._thesis_store = thesis_store
        self._lookback_minutes = (config or {}).get("intel_lookback_minutes", 30)
        self._min_relevance = (config or {}).get("intel_min_relevance", 0.1)
        self._last_scan_time: datetime | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_and_evaluate(
        self,
        positions: list[dict],
        signal_aggregator: Any,
    ) -> list[dict]:
        """Scan recent intel, evaluate impact on positions, generate signals.

        Args:
            positions: List of position dicts, each with at least ``symbol``
                and ``name`` keys.
            signal_aggregator: A :class:`SignalAggregator` instance to receive
                generated signals.

        Returns:
            List of impact summaries::

                [{"symbol": str, "intel_title": str, "impact": str,
                  "action_taken": str}, ...]
        """
        if not self._info_store:
            logger.warning("IntelBridge: no info_store configured, skipping scan")
            return []

        # 1. Determine time window
        since = self._last_scan_time or (
            datetime.now(UTC) - timedelta(minutes=self._lookback_minutes)
        )
        since_str = since.strftime("%Y-%m-%d %H:%M:%S")

        # 2. Fetch recent intel items
        recent_items = self._fetch_recent_intel(since_str)
        if not recent_items:
            self._last_scan_time = datetime.now(UTC)
            return []

        logger.info(
            "IntelBridge: scanning %d intel items since %s against %d positions",
            len(recent_items),
            since_str,
            len(positions),
        )

        # 3. Build position lookup
        position_symbols = {
            p.get("symbol", ""): p.get("name", "") for p in positions if p.get("symbol")
        }

        impact_summaries: list[dict] = []

        for item in recent_items:
            # 4. Find affected symbols among held positions
            affected = self._extract_affected_symbols(item, positions)

            for symbol in affected:
                name = position_symbols.get(symbol, "")

                # 5. Evaluate impact direction
                impact = self._evaluate_impact(item, symbol)

                # 6. Update thesis and optionally generate signal
                action = self._process_impact(
                    symbol, name, item, impact, signal_aggregator
                )

                impact_summaries.append(
                    {
                        "symbol": symbol,
                        "intel_title": item.get("title", "")[:60],
                        "impact": impact,
                        "action_taken": action,
                    }
                )

            # 7. Check for new opportunities (intel mentions symbols we don't hold)
            new_opps = self._check_new_opportunities(item, position_symbols)
            for opp in new_opps:
                impact_summaries.append(opp)

        self._last_scan_time = datetime.now(UTC)

        if impact_summaries:
            logger.info(
                "IntelBridge: produced %d impact summaries (%d positions affected)",
                len(impact_summaries),
                len({s["symbol"] for s in impact_summaries}),
            )

        return impact_summaries

    # ------------------------------------------------------------------
    # Internal: intel fetching
    # ------------------------------------------------------------------

    def _fetch_recent_intel(self, since_str: str) -> list[dict]:
        """Fetch recent intel items from the info store.

        Tries ``get_feed`` with a tight time window.  Falls back gracefully
        if the store API differs.
        """
        try:
            # InfoStore.get_feed supports days-based filtering; compute days
            # from since_str, but use a 1-day minimum to avoid empty results.
            items = self._info_store.get_feed(limit=100, days=1)
            # Filter client-side to items published after `since_str`
            filtered = []
            for item in items:
                published = item.get("published_at") or item.get("fetched_at", "")
                if published and published >= since_str:
                    filtered.append(item)
            return filtered
        except Exception:
            logger.debug("IntelBridge: get_feed failed, trying fallback", exc_info=True)

        # Fallback: try get_recent (some store implementations)
        try:
            return self._info_store.get_recent(limit=50)  # type: ignore[union-attr]
        except (AttributeError, TypeError):
            logger.warning("IntelBridge: unable to fetch recent intel from store")
            return []

    # ------------------------------------------------------------------
    # Internal: symbol matching
    # ------------------------------------------------------------------

    def _extract_affected_symbols(
        self, intel_item: dict, positions: list[dict]
    ) -> list[str]:
        """Find which held symbols are affected by this intel item.

        Matches by:
        1. Explicit ``related_symbols`` overlap with position symbols.
        2. Symbol or name appearing in the intel title/summary text.
        """
        position_symbols = {
            p.get("symbol", ""): p.get("name", "") for p in positions if p.get("symbol")
        }
        affected: list[str] = []

        # Parse related_symbols (may be JSON string or list)
        related = intel_item.get("related_symbols", [])
        if isinstance(related, str):
            try:
                related = json.loads(related)
            except (json.JSONDecodeError, TypeError):
                related = []

        related_set = set(related) if isinstance(related, list) else set()

        title = intel_item.get("title", "")
        summary = intel_item.get("summary", "") or ""
        text = f"{title} {summary}"

        for symbol, name in position_symbols.items():
            # Direct symbol mention in related_symbols
            if symbol in related_set:
                affected.append(symbol)
                continue

            # Symbol code in text
            if symbol in text:
                affected.append(symbol)
                continue

            # Company name in text (if name is non-empty and at least 2 chars)
            if name and len(name) >= 2 and name in text:
                affected.append(symbol)
                continue

        return affected

    # ------------------------------------------------------------------
    # Internal: impact evaluation
    # ------------------------------------------------------------------

    def _evaluate_impact(self, intel_item: dict, symbol: str) -> str:
        """Evaluate whether intel is positive/negative/neutral for a symbol.

        Uses simple keyword matching in the intel title and summary.
        Returns ``'positive'``, ``'negative'``, or ``'neutral'``.
        """
        title = intel_item.get("title", "")
        summary = intel_item.get("summary", "") or ""
        text = f"{title} {summary}"

        pos_hits = sum(1 for kw in _POSITIVE_KEYWORDS if kw in text)
        neg_hits = sum(1 for kw in _NEGATIVE_KEYWORDS if kw in text)

        if pos_hits > neg_hits:
            return "positive"
        if neg_hits > pos_hits:
            return "negative"
        return "neutral"

    # ------------------------------------------------------------------
    # Internal: thesis + signal processing
    # ------------------------------------------------------------------

    def _process_impact(
        self,
        symbol: str,
        name: str,
        intel_item: dict,
        impact: str,
        signal_aggregator: Any,
    ) -> str:
        """Update thesis and generate signal based on impact.

        Returns a short description of the action taken.
        """
        title = intel_item.get("title", "")[:60]

        # Update thesis conviction if thesis store is available
        if self._thesis_store:
            self._update_thesis_from_intel(symbol, name, intel_item, impact)

        # Generate signal for significant impacts
        if impact == "negative":
            # Check if thesis is now invalidated
            thesis = self._get_active_thesis(symbol)
            if thesis and thesis.conviction < _INVALIDATION_THRESHOLD:
                # Thesis invalidated — generate SELL signal
                signal = AggregatedSignal(
                    symbol=symbol,
                    name=name,
                    direction=SignalDirection.SELL,
                    source="intel_bridge",
                    confidence=0.85,
                    urgency=UrgencyTier.HIGH,
                    reason=f"情报触发论文失效: {title}",
                    metadata={
                        "intel_title": title,
                        "impact": impact,
                        "trigger": "thesis_invalidation",
                    },
                )
                signal_aggregator.add_signal(signal)
                return "thesis_invalidated → SELL signal"

            # Negative but thesis still valid — generate REDUCE signal
            signal = AggregatedSignal(
                symbol=symbol,
                name=name,
                direction=SignalDirection.REDUCE,
                source="intel_bridge",
                confidence=0.6,
                urgency=UrgencyTier.NORMAL,
                reason=f"负面情报: {title}",
                metadata={
                    "intel_title": title,
                    "impact": impact,
                    "trigger": "negative_intel",
                },
            )
            signal_aggregator.add_signal(signal)
            return "negative_intel → REDUCE signal"

        if impact == "positive":
            # Positive intel — generate ADD signal if conviction is strong
            thesis = self._get_active_thesis(symbol)
            if thesis and thesis.conviction >= 0.6:
                signal = AggregatedSignal(
                    symbol=symbol,
                    name=name,
                    direction=SignalDirection.ADD,
                    source="intel_bridge",
                    confidence=0.55,
                    urgency=UrgencyTier.NORMAL,
                    reason=f"正面情报印证: {title}",
                    metadata={
                        "intel_title": title,
                        "impact": impact,
                        "trigger": "positive_intel",
                    },
                )
                signal_aggregator.add_signal(signal)
                return "positive_intel → ADD signal"
            return "positive_intel → conviction boosted"

        return "neutral → no action"

    def _update_thesis_from_intel(
        self, symbol: str, name: str, intel_item: dict, impact: str
    ) -> None:
        """Update thesis conviction based on intel impact.

        - Positive impact: boost conviction by ``_CONVICTION_BOOST``.
        - Negative impact: reduce conviction by ``_CONVICTION_REDUCE``.
        - Neutral: no change.

        If conviction drops below ``_INVALIDATION_THRESHOLD``, the thesis is
        marked invalidated but NOT deleted (kept for learning).
        """
        if not self._thesis_store:
            return

        title = intel_item.get("title", "")[:60]

        if impact == "positive":
            self._thesis_store.update_conviction(
                symbol,
                _CONVICTION_BOOST,
                f"正面情报: {title}",
            )
            logger.info(
                "Thesis conviction boosted for %s (%s): +%.2f — %s",
                symbol,
                name,
                _CONVICTION_BOOST,
                title,
            )

        elif impact == "negative":
            self._thesis_store.update_conviction(
                symbol,
                _CONVICTION_REDUCE,
                f"负面情报: {title}",
            )
            logger.info(
                "Thesis conviction reduced for %s (%s): %.2f — %s",
                symbol,
                name,
                _CONVICTION_REDUCE,
                title,
            )

            # Check if thesis should be invalidated
            thesis = self._get_active_thesis(symbol)
            if thesis and thesis.conviction < _INVALIDATION_THRESHOLD:
                self._thesis_store.invalidate(
                    symbol,
                    f"情报触发失效 (conviction={thesis.conviction:.2f}): {title}",
                )
                logger.warning(
                    "Thesis INVALIDATED for %s (%s) — conviction %.2f below threshold %.2f",
                    symbol,
                    name,
                    thesis.conviction,
                    _INVALIDATION_THRESHOLD,
                )

    def _get_active_thesis(self, symbol: str) -> Any:
        """Safely retrieve the active thesis for a symbol."""
        if not self._thesis_store:
            return None
        try:
            return self._thesis_store.get(symbol)
        except Exception:
            logger.debug("Failed to get thesis for %s", symbol, exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Internal: new opportunity detection
    # ------------------------------------------------------------------

    def _check_new_opportunities(
        self,
        intel_item: dict,
        held_symbols: dict[str, str],
    ) -> list[dict]:
        """Check if intel mentions symbols we do NOT hold (potential new BUY).

        Only flags high-priority positive intel for symbols not in portfolio.
        Returns impact summary dicts (no signals generated — just logging).
        """
        priority = intel_item.get("priority", "normal")
        if priority not in ("high", "urgent", "critical"):
            return []

        impact = self._evaluate_impact(intel_item, "")
        if impact != "positive":
            return []

        # Parse related_symbols
        related = intel_item.get("related_symbols", [])
        if isinstance(related, str):
            try:
                related = json.loads(related)
            except (json.JSONDecodeError, TypeError):
                related = []

        if not isinstance(related, list):
            return []

        new_symbols = [s for s in related if s and s not in held_symbols]
        if not new_symbols:
            return []

        title = intel_item.get("title", "")[:60]
        summaries = []
        for sym in new_symbols[:3]:  # cap at 3 to avoid noise
            logger.info(
                "IntelBridge: new opportunity detected — %s mentioned in '%s'",
                sym,
                title,
            )
            summaries.append(
                {
                    "symbol": sym,
                    "intel_title": title,
                    "impact": "positive",
                    "action_taken": "new_opportunity_flagged",
                }
            )

        return summaries
