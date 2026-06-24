"""Missed Opportunity Detector — finds stocks that moved without a signal.

This is the key learning mechanism. By measuring what the system missed,
we identify blind spots in signal detection and adjust coverage.

Results are recorded in OutcomeTracker for long-term learning.
"""

from __future__ import annotations

import logging
from typing import Any

from src.agent_loop.outcome_tracker import MissedOpportunity, OutcomeTracker

logger = logging.getLogger(__name__)


class MissedOpportunityDetector:
    """Detects stocks that moved significantly without any system signal.

    Scans daily returns for large movers that had no corresponding signal
    in the OutcomeTracker, classifies each as preventable or unpreventable,
    and records the miss for future learning.
    """

    def __init__(
        self,
        outcome_tracker: OutcomeTracker | None = None,
        data_fetcher: Any = None,
    ) -> None:
        self._tracker = outcome_tracker or OutcomeTracker()
        self._fetcher = data_fetcher

    # ------------------------------------------------------------------
    # Daily scan
    # ------------------------------------------------------------------

    async def scan_daily(
        self, date: str, threshold_pct: float = 5.0
    ) -> list[MissedOpportunity]:
        """Find stocks that moved > threshold_pct without a signal.

        Steps:
        1. Get all A-share daily returns for the date (from data fetcher)
        2. Filter to |return| > threshold
        3. Check if OutcomeTracker has a signal for each
        4. For misses: classify as preventable/unpreventable
        5. Record in OutcomeTracker for learning
        """
        if self._fetcher is None:
            logger.warning("No data fetcher configured, skipping daily scan")
            return []

        # Step 1: Get daily returns
        big_movers = await self._get_big_movers(date, threshold_pct)
        if not big_movers:
            return []

        # Step 2: Get symbols we already had signals for
        signaled_symbols = self._get_signaled_symbols(date)

        # Step 3-4: Identify misses
        missed: list[MissedOpportunity] = []
        for mover in big_movers:
            symbol = mover["symbol"]
            if symbol in signaled_symbols:
                continue

            # Classify the miss
            had_data = await self._check_had_data(symbol, date)
            preventable = had_data  # Simplification: if we had data, it was catchable
            reason = (
                "Stock was in data universe but no signal generated"
                if had_data
                else "Stock not in data universe or insufficient history"
            )

            opportunity = MissedOpportunity(
                symbol=symbol,
                name=mover.get("name", ""),
                date=date,
                daily_return_pct=mover["return_pct"],
                had_data=had_data,
                preventable=preventable,
                reason=reason,
            )
            missed.append(opportunity)

            # Step 5: Record for learning
            await self._tracker.record_missed_opportunity(opportunity)

        logger.info(
            "Scanned %s: %d big movers, %d missed (%d preventable)",
            date,
            len(big_movers),
            len(missed),
            sum(1 for m in missed if m.preventable),
        )
        return missed

    # ------------------------------------------------------------------
    # Deep analysis
    # ------------------------------------------------------------------

    async def analyze_miss(self, symbol: str, date: str) -> dict[str, Any]:
        """Deep analysis of why a specific opportunity was missed.

        Returns analysis dict with data availability, signal status,
        sector context, and recommendations for improvement.
        """
        had_data = await self._check_had_data(symbol, date)
        had_signals = self._check_had_filtered_signals(symbol, date)
        filtered_reason = ""
        if had_signals:
            filtered_reason = self._get_filter_reason(symbol, date)

        sector_context = await self._get_sector_context(symbol, date)

        # Generate recommendation based on miss classification
        if not had_data:
            recommendation = "Expand data universe to include this stock or sector"
        elif had_signals:
            recommendation = (
                f"Review filter thresholds — signal existed but was "
                f"filtered: {filtered_reason}"
            )
        else:
            recommendation = (
                "Investigate why no signal source fired. Consider adding "
                "pattern recognition for the move type observed."
            )

        return {
            "symbol": symbol,
            "date": date,
            "had_data": had_data,
            "had_signals": had_signals,
            "filtered_reason": filtered_reason,
            "sector_context": sector_context,
            "recommendation": recommendation,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_big_movers(
        self, date: str, threshold_pct: float
    ) -> list[dict[str, Any]]:
        """Get stocks with |return| > threshold from the data fetcher."""
        try:
            if hasattr(self._fetcher, "get_daily_returns"):
                all_returns = await self._fetcher.get_daily_returns(date)
            elif hasattr(self._fetcher, "fetch_daily_returns"):
                all_returns = await self._fetcher.fetch_daily_returns(date)
            else:
                logger.warning("Data fetcher has no daily returns method")
                return []

            if not all_returns:
                return []

            return [
                r for r in all_returns if abs(r.get("return_pct", 0)) >= threshold_pct
            ]
        except Exception as exc:
            logger.warning("Failed to get daily returns for %s: %s", date, exc)
            return []

    def _get_signaled_symbols(self, date: str) -> set[str]:
        """Get symbols that had signals on or near the given date."""
        try:
            with self._tracker._conn() as conn:
                rows = conn.execute(
                    """SELECT DISTINCT symbol FROM tracked_signals
                       WHERE date(created_at) BETWEEN date(?, '-1 day')
                                                   AND date(?, '+1 day')""",
                    (date, date),
                ).fetchall()
            return {r[0] for r in rows}
        except Exception as exc:
            logger.warning("Failed to get signaled symbols: %s", exc)
            return set()

    async def _check_had_data(self, symbol: str, date: str) -> bool:
        """Check if the system had price/volume data for this stock."""
        if self._fetcher is None:
            return False
        try:
            if hasattr(self._fetcher, "has_data"):
                return await self._fetcher.has_data(symbol, date)
            # Fallback: try fetching a single quote
            if hasattr(self._fetcher, "get_stock_data"):
                data = await self._fetcher.get_stock_data(symbol)
                return data is not None
            return False
        except Exception:
            return False

    def _check_had_filtered_signals(self, symbol: str, date: str) -> bool:
        """Check if any signal source fired but the signal was filtered."""
        # Currently we only track emitted signals, not filtered ones.
        # This is a placeholder for future filter-logging integration.
        return False

    def _get_filter_reason(self, symbol: str, date: str) -> str:
        """Get the reason a signal was filtered (if applicable)."""
        return "Filter logging not yet implemented"

    async def _get_sector_context(self, symbol: str, date: str) -> str:
        """Get sector context for a missed stock."""
        try:
            if self._fetcher and hasattr(self._fetcher, "get_stock_info"):
                info = await self._fetcher.get_stock_info(symbol)
                if info and info.get("sector"):
                    return f"Sector: {info['sector']}"
        except Exception:
            pass
        return "Sector context unavailable"
