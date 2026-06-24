"""Information aggregator — orchestrates source → classify → score → store.

Part of v21.0 Intelligence Hub, extended in v23.0 with registry/scorer/dedup,
and Phase 2 with social guardrails, event clustering, and diversity reranking.
Extended in v26.0 Phase 4 with capital flow anomaly injection (FR-CF013).
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any

from src.intelligence_hub.classifier import InfoClassifier
from src.intelligence_hub.info_store import InfoStore
from src.intelligence_hub.models import InfoItem
from src.intelligence_hub.source_base import InformationSource
from src.intelligence_hub.sources.akshare_news_source import AkshareNewsSource
from src.intelligence_hub.sources.policy_source import PolicySource
from src.intelligence_hub.sources.reddit_source import RedditSource
from src.intelligence_hub.sources.rss_source import RssSource

if TYPE_CHECKING:
    from src.intelligence.impact_engine import EventImpactEngine
    from src.intelligence_hub.dedup import DedupChecker
    from src.intelligence_hub.event_cluster import EventClusterer
    from src.intelligence_hub.scorer import ContentScorer
    from src.intelligence_hub.social_guardrails import SocialGuardrails
    from src.intelligence_hub.source_registry import SourceRegistry
    from src.intelligence_hub.symbol_extractor import SymbolExtractor

logger = logging.getLogger(__name__)

# Severity → InfoItem priority mapping for capital flow anomalies
_SEVERITY_PRIORITY_MAP: dict[str, str] = {
    "high": "breaking",
    "medium": "high",
    "low": "normal",
}

_SOURCE_TYPE_MAP: dict[str, type[InformationSource]] = {
    "akshare_news": AkshareNewsSource,
    "policy": PolicySource,
    "reddit": RedditSource,
    "rss": RssSource,
}


class InfoAggregator:
    """Orchestrates fetching from all sources, classifying, scoring, and storing."""

    def __init__(
        self,
        store: InfoStore,
        config: dict[str, Any] | None = None,
        *,
        source_registry: SourceRegistry | None = None,
        scorer: ContentScorer | None = None,
        dedup_checker: DedupChecker | None = None,
        social_guardrails: SocialGuardrails | None = None,
        event_clusterer: EventClusterer | None = None,
        symbol_extractor: SymbolExtractor | None = None,
        impact_engine: EventImpactEngine | None = None,
    ) -> None:
        self._store = store
        self._config = config or {}
        self._classifier = InfoClassifier(self._config.get("classification"))
        self._registry = source_registry
        self._scorer = scorer
        self._dedup = dedup_checker
        self._guardrails = social_guardrails
        self._clusterer = event_clusterer
        self._symbol_extractor = symbol_extractor
        self._impact_engine = impact_engine
        self._sources = self._build_sources()
        self._last_refresh: float = 0.0
        self._refresh_interval = self._config.get("refresh_interval_seconds", 300)
        self._retention_days = self._config.get("retention_days", 30)

    def _build_sources(self) -> list[InformationSource]:
        """Instantiate source adapters from config."""
        sources: list[InformationSource] = []
        sources_cfg = self._config.get("sources", {})
        for source_id, source_cfg in sources_cfg.items():
            source_type = source_cfg.get("type", "")
            cls = _SOURCE_TYPE_MAP.get(source_type)
            if cls is None:
                logger.warning(
                    "Unknown source type '%s' for %s", source_type, source_id
                )
                continue
            if not source_cfg.get("enabled", True):
                continue
            sources.append(cls(source_id, source_cfg))
        logger.info("InfoAggregator initialized with %d sources", len(sources))
        return sources

    def _detect_and_convert_flow_anomalies(self) -> list[InfoItem]:
        """Run capital flow anomaly detection and convert events to InfoItems.

        Uses FlowAnomalyDetector to check for macro/sector anomalies and
        converts the resulting FlowAnomalyEvent objects into InfoItem objects
        for injection into the intelligence hub feed.

        Returns:
            List of InfoItem objects from detected anomalies.
        """
        try:
            from src.analysis.flow_anomaly_detector import (
                FlowAnomalyDetector,
                FlowAnomalyEvent,
            )
            from src.data.macro_flow_fetcher import MacroFlowFetcher
            from src.data.sector_flow_fetcher import SectorFlowFetcher

            detector = FlowAnomalyDetector()
            events: list[FlowAnomalyEvent] = []

            # Macro anomalies: northbound flow
            try:
                macro_fetcher = MacroFlowFetcher()
                snapshot = macro_fetcher.get_latest_snapshot()
                history = macro_fetcher.get_macro_history(days=30)
                nb_history = [
                    s.northbound_net for s in history if s.northbound_net != 0
                ]

                if snapshot.northbound_net != 0:
                    macro_events = detector.detect_macro_anomalies(
                        snapshot.northbound_net, nb_history
                    )
                    events.extend(macro_events)
            except Exception as exc:
                logger.warning("Macro anomaly detection failed: %s", exc)

            # Sector anomalies
            try:
                sector_fetcher = SectorFlowFetcher()
                df = sector_fetcher.fetch_industry_flow(period="today")
                if (
                    not df.empty
                    and "sector_name" in df.columns
                    and "net_inflow" in df.columns
                ):
                    sector_flows = dict(
                        zip(
                            df["sector_name"].astype(str),
                            df["net_inflow"].astype(float),
                        )
                    )
                    # Build sector history from multi-period data
                    sector_history: dict[str, list[float]] = {}
                    for period in ("3d", "5d", "10d"):
                        hist_df = sector_fetcher.fetch_industry_flow(period=period)
                        if not hist_df.empty and "sector_name" in hist_df.columns:
                            for _, row in hist_df.iterrows():
                                name = str(row.get("sector_name", ""))
                                val = float(row.get("net_inflow", 0) or 0)
                                sector_history.setdefault(name, []).append(val)

                    if sector_flows and sector_history:
                        sector_events = detector.detect_sector_anomalies(
                            sector_flows, sector_history
                        )
                        events.extend(sector_events)
            except Exception as exc:
                logger.warning("Sector anomaly detection failed: %s", exc)

            # Convert FlowAnomalyEvent -> InfoItem
            from datetime import UTC, datetime as _dt

            now_str = _dt.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
            items: list[InfoItem] = []
            for event in events:
                priority = _SEVERITY_PRIORITY_MAP.get(event.severity, "normal")
                item = InfoItem(
                    source_id="capital_flow_anomaly",
                    source_name="资金流向异动检测",
                    title=event.title,
                    summary=event.summary,
                    category="market",
                    priority=priority,
                    tags=[event.event_type, "capital_flow", "anomaly"],
                    related_symbols=event.related_symbols,
                    published_at=now_str,
                    extra={"anomaly_data": event.data, "event_type": event.event_type},
                )
                items.append(item)

            return items
        except Exception as exc:
            logger.warning("Capital flow anomaly injection failed: %s", exc)
            return []

    def refresh(self, force: bool = False) -> tuple[int, list[str]]:
        """Fetch from all sources, classify, deduplicate, score, and store.

        Two-phase pipeline (v23.0 Phase 2):
          Phase 1 — Per-source: fetch → health → dedup → classify → guardrails
          Phase 2 — Cross-source: event clustering → scoring (with cross-verification) → store

        Args:
            force: Bypass cooldown if True.

        Returns:
            Tuple of (new_items_count, new_item_ids).
        """
        now = time.time()
        if not force and (now - self._last_refresh) < self._refresh_interval:
            logger.debug("Refresh skipped — cooldown active")
            return 0, []

        # Reset dedup state for this refresh cycle
        if self._dedup:
            self._dedup.reset()

        # ── Phase 1: Parallel fetch from all sources ─────────────────
        all_items = []

        def _fetch_one(source: InformationSource):
            t0 = time.time()
            try:
                items = source.fetch()
                latency_ms = (time.time() - t0) * 1000
                return source, items, latency_ms, None
            except Exception as exc:
                return source, [], 0.0, exc

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_fetch_one, s): s for s in self._sources}
            fetch_results = []
            for future in as_completed(futures):
                fetch_results.append(future.result())

        # Process results sequentially (dedup/classify have shared state)
        for source, items, latency_ms, error in fetch_results:
            if error:
                if self._registry:
                    self._registry.record_failure(source.source_id, error=str(error))
                logger.warning("Source %s failed: %s", source.source_id, error)
                continue

            # Record health
            if self._registry:
                self._registry.record_success(source.source_id, latency_ms=latency_ms)

            if not items:
                continue

            # Dedup within refresh cycle
            if self._dedup:
                items = self._dedup.filter_batch(items)

            # Classify
            source_type = source.config.get("type", "")
            self._classifier.classify_batch(items, source_type=source_type)

            # Social guardrails (L5 priority downgrade + unverified tag)
            if self._guardrails:
                self._guardrails.apply_batch(items)

            # Extract stock symbols from title/summary
            if self._symbol_extractor:
                self._symbol_extractor.extract_batch(items)

            all_items.extend(items)
            logger.info(
                "Source %s: fetched=%d",
                source.source_id,
                len(items),
            )

        # ── Phase 2: Cross-source processing ─────────────────────────
        # Event clustering for cross-verification scores
        cv_map: dict[str, float] | None = None
        if self._clusterer and all_items:
            cv_map = self._clusterer.get_cross_verification_map(all_items)

        # Score with cross-verification
        if self._scorer and all_items:
            results = self._scorer.score_batch(all_items, cross_verification_map=cv_map)
            for item, result in zip(all_items, results):
                item.content_score = result.score
                item.score_explain = result.explain

        # ── Phase 3: Capital flow anomaly injection (v26.0 FR-CF013) ─
        flow_items = self._detect_and_convert_flow_anomalies()
        if flow_items:
            all_items.extend(flow_items)
            logger.info("Injected %d capital flow anomaly items", len(flow_items))

        # Store
        total_stored = 0
        new_ids: list[str] = []
        if all_items:
            total_stored, new_ids = self._store.store_batch(all_items)
            # Flush WAL to main DB so other processes (API ↔ Celery) can
            # read newly-committed items through Docker bind-mount volumes.
            self._store.checkpoint()

        self._last_refresh = time.time()

        # Periodic cleanup
        try:
            self._store.cleanup(days=self._retention_days)
        except Exception as exc:
            logger.warning("Cleanup failed: %s", exc)

        logger.info("Refresh complete: %d new items", total_stored)
        return total_stored, new_ids

    def process_event_impact(self, info_item: dict[str, Any]) -> list[dict[str, Any]]:
        """Process an info item through causal chain analysis.

        Routes the event through the EventImpactEngine to produce tradeable
        signal evidence dicts for each affected stock.

        Args:
            info_item: Event dict with keys like title, summary, confidence,
                sectors, etc.  Can also accept an InfoItem.to_dict() output.

        Returns:
            List of signal evidence dicts ready for SignalAggregator.
        """
        if self._impact_engine is None:
            try:
                from src.intelligence.causal_chain import CausalChainConstructor
                from src.intelligence.impact_engine import EventImpactEngine

                constructor = CausalChainConstructor()
                self._impact_engine = EventImpactEngine(chain_constructor=constructor)
            except Exception as exc:
                logger.warning("Failed to initialize impact engine: %s", exc)
                return []

        try:
            signals = self._impact_engine.process_event(info_item)
            if signals:
                logger.info(
                    "Event impact analysis produced %d signals for '%s'",
                    len(signals),
                    str(info_item.get("title", ""))[:40],
                )
            return signals
        except Exception as exc:
            logger.warning("Event impact processing failed: %s", exc)
            return []
