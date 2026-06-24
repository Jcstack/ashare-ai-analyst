"""SignalCollectorFactory — creates DomainAdapters from live data sources.

Bridges the gap between live data fetchers and the DomainAdapter protocol,
enabling event-driven signal collection for convergence checking.

Per PRD v50.0 §9: all signal domains feed into ConvergenceEngine.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SignalCollectorFactory:
    """Collects signals from all 5 domains using live data sources.

    Usage::

        factory = SignalCollectorFactory(
            signal_store=..., sector_flow_fetcher=..., ...
        )
        signals = factory.collect_all(symbols=["600036"], portfolio={})
    """

    def __init__(
        self,
        signal_store: Any = None,
        sector_flow_fetcher: Any = None,
        macro_flow_fetcher: Any = None,
        leader_detector: Any = None,
        minute_bar_fetcher: Any = None,
        signal_quality: Any = None,
        info_store: Any = None,
    ) -> None:
        self._signal_store = signal_store
        self._sector_flow = sector_flow_fetcher
        self._macro_flow = macro_flow_fetcher
        self._leader_detector = leader_detector
        self._minute_bar = minute_bar_fetcher
        self._signal_quality = signal_quality
        self._info_store = info_store

    def collect_all(
        self,
        symbols: list[str],
        portfolio_context: dict[str, Any] | None = None,
    ) -> list:
        """Collect signals from all available domains.

        Gracefully skips any domain whose data source is unavailable.
        Returns a flat list of SignalEvidence from all domains.
        """
        from src.agent_loop.domain_adapter import SignalEvidence

        all_signals: list[SignalEvidence] = []

        # 1. Technical signals (from signal store)
        all_signals.extend(self._collect_technical(symbols, portfolio_context))

        # 2. Capital flow signals
        all_signals.extend(self._collect_capital_flow(symbols, portfolio_context))

        # 3. Intelligence signals
        all_signals.extend(self._collect_intelligence(symbols, portfolio_context))

        # 4. Microstructure signals
        all_signals.extend(self._collect_microstructure(symbols, portfolio_context))

        # 5. Leader signals
        all_signals.extend(self._collect_leaders(symbols, portfolio_context))

        logger.info(
            "Collected %d signals across %d symbols", len(all_signals), len(symbols)
        )
        return all_signals

    # ------------------------------------------------------------------
    # Domain collectors — each returns [] on any failure
    # ------------------------------------------------------------------

    def _collect_technical(
        self,
        symbols: list[str],
        portfolio_context: dict[str, Any] | None,
    ) -> list:
        """Collect technical signals from the SignalStore."""
        if not self._signal_store:
            return []
        try:
            from src.agent_loop.adapters.technical_adapter import TechnicalAdapter

            recent = self._signal_store.get_recent(hours=1)
            signal_dicts = [s if isinstance(s, dict) else s.to_dict() for s in recent]
            adapter = TechnicalAdapter(signal_dicts=signal_dicts)
            return adapter.collect_signals(symbols, portfolio_context)
        except Exception as exc:
            logger.debug("Technical collection failed: %s", exc)
            return []

    def _collect_capital_flow(
        self,
        symbols: list[str],
        portfolio_context: dict[str, Any] | None,
    ) -> list:
        """Collect capital flow signals from sector flow and macro flow fetchers."""
        if not self._sector_flow and not self._macro_flow:
            return []
        try:
            from src.agent_loop.adapters.capital_flow_adapter import CapitalFlowAdapter

            sector_flows: list[dict[str, Any]] = []
            northbound_flows: list[dict[str, Any]] = []

            # Sector flows → list of dicts
            if self._sector_flow:
                try:
                    df = self._sector_flow.fetch_industry_flow("today")
                    if df is not None and not df.empty:
                        sector_flows = df.to_dict(orient="records")
                except Exception as exc:
                    logger.debug("Sector flow fetch failed: %s", exc)

            # Northbound flows → list of dicts
            if self._macro_flow:
                try:
                    df = self._macro_flow._fetch_hsgt_summary("北向")
                    if df is not None and not df.empty:
                        northbound_flows = df.to_dict(orient="records")
                except Exception as exc:
                    logger.debug("Northbound flow fetch failed: %s", exc)

            adapter = CapitalFlowAdapter(
                sector_flows=sector_flows,
                northbound_flows=northbound_flows,
            )
            return adapter.collect_signals(symbols, portfolio_context)
        except Exception as exc:
            logger.debug("Capital flow collection failed: %s", exc)
            return []

    def _collect_intelligence(
        self,
        symbols: list[str],
        portfolio_context: dict[str, Any] | None,
    ) -> list:
        """Collect intelligence signals from the InfoStore."""
        if not self._info_store:
            return []
        try:
            from src.agent_loop.adapters.intelligence_adapter import IntelligenceAdapter

            # Use get_feed with a short time window for recent high-priority intel
            items = self._info_store.get_feed(limit=50, days=1, sort_by="score")
            adapter = IntelligenceAdapter(intel_items=items)
            return adapter.collect_signals(symbols, portfolio_context)
        except Exception as exc:
            logger.debug("Intelligence collection failed: %s", exc)
            return []

    def _collect_microstructure(
        self,
        symbols: list[str],
        portfolio_context: dict[str, Any] | None,
    ) -> list:
        """Collect microstructure signals (VPIN) from minute bar data.

        This is optional and expensive — returns empty if data is unavailable,
        which is expected for most runs.
        """
        if not self._minute_bar:
            return []
        try:
            from src.agent_loop.adapters.microstructure_adapter import (
                MicrostructureAdapter,
            )
            from src.quant.vpin import VpinCalculator

            vpin_calc = VpinCalculator()
            vpin_results: list[dict[str, Any]] = []

            for sym in symbols:
                try:
                    bars = self._minute_bar.get_bars(sym, period="5min", count=50)
                    if bars is None or (hasattr(bars, "empty") and bars.empty):
                        continue
                    result = vpin_calc.compute(bars)
                    if result:
                        result_dict = (
                            result if isinstance(result, dict) else vars(result)
                        )
                        result_dict.setdefault("symbol", sym)
                        vpin_results.append(result_dict)
                except Exception as exc:
                    logger.debug("VPIN computation failed for %s: %s", sym, exc)

            adapter = MicrostructureAdapter(vpin_results=vpin_results)
            return adapter.collect_signals(symbols, portfolio_context)
        except Exception as exc:
            logger.debug("Microstructure collection failed: %s", exc)
            return []

    def _collect_leaders(
        self,
        symbols: list[str],
        portfolio_context: dict[str, Any] | None,
    ) -> list:
        """Collect leader detection signals.

        Requires pre-computed LeaderCandidate data (typically from limit-up
        pool). Returns empty if leader_detector or candidate data is unavailable.
        """
        if not self._leader_detector:
            return []
        try:
            from src.agent_loop.adapters.leader_adapter import LeaderAdapter
            from src.agent_loop.leader_detector import LeaderCandidate

            # Build minimal candidates from symbols — the detector needs
            # LeaderCandidate objects. Without limit-up pool data, we can
            # only construct stubs which will score low.
            candidates = [
                LeaderCandidate(symbol=s, name="", sector="") for s in symbols
            ]
            scores = self._leader_detector.identify_leaders(candidates)

            # Convert LeaderScore dataclasses to dicts for the adapter
            score_dicts = [
                {
                    "symbol": s.symbol,
                    "name": s.name,
                    "sector": s.sector,
                    "total_score": s.total_score,
                    "is_leader": s.is_leader,
                    "scores": s.scores,
                    "reason": s.reason,
                    "confidence_level": s.confidence_level,
                }
                for s in scores
            ]

            adapter = LeaderAdapter(leader_scores=score_dicts)
            return adapter.collect_signals(symbols, portfolio_context)
        except Exception as exc:
            logger.debug("Leader collection failed: %s", exc)
            return []
