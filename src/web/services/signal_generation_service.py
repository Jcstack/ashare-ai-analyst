"""Signal generation pipeline — scans tracked stocks + policy sources and
produces real ``MarketSignal`` instances stored in ``SignalStore``.

Orchestrates:
- Technical signals via ``SignalLibrary`` for watchlist + followed stocks
- Policy/regulatory signals via ``PolicyNewsFetcher``
- Macro regime signals via ``MacroRegimeClassifier``

Each scan deduplicates against recently-stored signals to avoid flooding.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from src.web.schemas.market_signal import (
    MarketPhase,
    MarketSignal,
    RiskLevel,
    SignalType,
)

logger = logging.getLogger(__name__)

# Dedup windows
_TECHNICAL_DEDUP_HOURS = 4
_POLICY_DEDUP_HOURS = 24

# Minimum strength threshold for technical signals
_MIN_STRENGTH = 0.3


class SignalGenerationService:
    """Scans all signal sources and stores real ``MarketSignal`` instances."""

    def __init__(
        self,
        stock_service: Any,
        signal_library: Any,
        policy_fetcher: Any,
        macro_classifier: Any,
        phase_engine: Any,
        signal_store: Any,
        notification_orchestrator: Any,
        user_config_service: Any,
        macro_radar: Any | None = None,
    ) -> None:
        self._stock_service = stock_service
        self._signal_library = signal_library
        self._policy_fetcher = policy_fetcher
        self._macro_classifier = macro_classifier
        self._phase_engine = phase_engine
        self._signal_store = signal_store
        self._notification_orchestrator = notification_orchestrator
        self._user_config_service = user_config_service
        self._macro_radar = macro_radar

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_all(self) -> dict[str, int]:
        """Run the full signal generation pipeline.

        Returns:
            Dict with counts: ``{"technical": N, "policy": N, "macro": N}``.
        """
        phase = self._phase_engine.get_current_phase()
        results = {"technical": 0, "policy": 0, "macro": 0, "global_macro": 0}

        try:
            results["technical"] = self._scan_stocks(phase)
        except Exception:
            logger.exception("Technical signal scan failed")

        try:
            results["policy"] = self._scan_policy(phase)
        except Exception:
            logger.exception("Policy signal scan failed")

        try:
            results["macro"] = self._scan_macro(phase)
        except Exception:
            logger.exception("Macro signal scan failed")

        try:
            results["global_macro"] = self._scan_global_macro(phase)
        except Exception:
            logger.exception("Global macro radar scan failed")

        logger.info("Signal scan complete: %s", results)
        return results

    # ------------------------------------------------------------------
    # Technical signals
    # ------------------------------------------------------------------

    def _scan_stocks(self, phase: MarketPhase) -> int:
        from src.market_intelligence.signal_bus import SignalLibraryAdapter

        symbols = self._collect_symbols()
        if not symbols:
            logger.info("No symbols to scan")
            return 0

        recent_keys = self._load_recent_keys(
            hours=_TECHNICAL_DEDUP_HOURS,
            producer="signal_library",
        )

        count = 0
        for symbol in symbols:
            try:
                df = self._stock_service.get_stock_data(symbol)
                if df is None or df.empty or len(df) < 20:
                    continue

                closes = df["close"] if "close" in df.columns else None
                volumes = df["volume"] if "volume" in df.columns else None
                if closes is None:
                    continue

                summary = self._signal_library.evaluate(closes, volumes)

                for result in summary.signals:
                    if result.direction == "neutral":
                        continue
                    if result.strength < _MIN_STRENGTH:
                        continue

                    dedup_key = f"signal_library:{symbol}:{result.signal_name}"
                    if dedup_key in recent_keys:
                        continue

                    signal = SignalLibraryAdapter.convert(result, symbol, phase)
                    self._store_and_route(signal)
                    recent_keys.add(dedup_key)
                    count += 1

            except Exception:
                logger.warning("Failed to scan %s", symbol, exc_info=True)

        return count

    # ------------------------------------------------------------------
    # Policy signals
    # ------------------------------------------------------------------

    def _scan_policy(self, phase: MarketPhase) -> int:
        items = self._policy_fetcher.fetch_all()
        if not items:
            return 0

        recent_keys = self._load_recent_keys(
            hours=_POLICY_DEDUP_HOURS,
            producer="policy_news",
        )

        count = 0
        for item in items:
            title_hash = hashlib.md5(  # noqa: S324
                item.title.encode()
            ).hexdigest()[:12]
            dedup_key = f"policy_news::{title_hash}"
            if dedup_key in recent_keys:
                continue

            confidence = 70.0 if item.is_high_impact else 50.0
            risk_level = RiskLevel.ELEVATED if item.is_high_impact else RiskLevel.LOW

            summary_short = item.title[:50]

            signal = MarketSignal(
                signal_id=str(uuid.uuid4()),
                signal_type=SignalType.S7_POLICY_DRIVEN,
                timestamp=datetime.now(UTC),
                assets=[],
                phase=phase,
                confidence_score=confidence,
                risk_level=risk_level,
                sources=[],
                producer="policy_news",
                summary_short=summary_short,
                summary_detailed=f"{item.source_name}: {item.title}",
            )
            self._store_and_route(signal)
            recent_keys.add(dedup_key)
            count += 1

        return count

    # ------------------------------------------------------------------
    # Macro regime signals
    # ------------------------------------------------------------------

    def _scan_macro(self, phase: MarketPhase) -> int:
        result = self._macro_classifier.classify()
        regime = result.get("macro_regime", "neutral")
        explanation = result.get("explanation", "")

        # Only emit if regime changed from last stored macro signal
        last_macro = self._signal_store.get_signals(
            signal_type="S8_MACRO_DRIVEN",
            limit=1,
            days=7,
        )
        if last_macro:
            last_summary = last_macro[0].get("summary_short", "")
            if regime in last_summary:
                logger.debug("Macro regime unchanged (%s), skipping", regime)
                return 0

        confidence = 60.0
        vix = result.get("vix_level")
        if vix is not None:
            confidence = min(80.0, 50.0 + abs(vix - 20.0))

        signal = MarketSignal(
            signal_id=str(uuid.uuid4()),
            signal_type=SignalType.S8_MACRO_DRIVEN,
            timestamp=datetime.now(UTC),
            assets=[],
            phase=phase,
            confidence_score=confidence,
            risk_level=(RiskLevel.ELEVATED if regime == "risk_off" else RiskLevel.LOW),
            sources=[],
            producer="macro_classifier",
            summary_short=f"宏观体制: {regime}"[:50],
            summary_detailed=explanation or None,
        )
        self._store_and_route(signal)
        return 1

    # ------------------------------------------------------------------
    # Global macro radar
    # ------------------------------------------------------------------

    def _scan_global_macro(self, phase: MarketPhase) -> int:
        """Scan global markets and macro intel via MacroRadarService."""
        if self._macro_radar is None:
            return 0

        signals = self._macro_radar.scan_all_with_signals(phase)
        for signal in signals:
            self._store_and_route(signal)

        return len(signals)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _collect_symbols(self) -> list[str]:
        """Merge watchlist symbols with user-followed stocks."""
        symbols: set[str] = set()

        watchlist = self._stock_service.get_watchlist()
        for item in watchlist:
            code = item.get("code") or item.get("symbol", "")
            if code:
                symbols.add(code)

        try:
            follows = self._user_config_service.get_follows()
            for s in follows.get("stocks", []):
                if isinstance(s, str):
                    symbols.add(s)
                elif isinstance(s, dict):
                    code = s.get("symbol") or s.get("code", "")
                    if code:
                        symbols.add(code)
        except Exception:
            logger.debug("Could not load user follows", exc_info=True)

        return sorted(symbols)

    def _load_recent_keys(self, hours: int, producer: str) -> set[str]:
        """Build a set of dedup keys from recently stored signals."""
        keys: set[str] = set()
        try:
            recent = self._signal_store.get_signals(
                limit=500,
                days=max(1, hours // 24 + 1),
            )
            cutoff = datetime.now(UTC) - timedelta(hours=hours)
            for sig in recent:
                if sig.get("producer") != producer:
                    continue
                ts_str = sig.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=UTC)
                    if ts < cutoff:
                        continue
                except (ValueError, TypeError):
                    continue

                # Build dedup key matching the format used during scan
                import json

                assets_raw = sig.get("assets", "[]")
                if isinstance(assets_raw, str):
                    assets = json.loads(assets_raw)
                else:
                    assets = assets_raw
                symbol = assets[0] if assets else ""
                summary = sig.get("summary_short", "")

                if producer == "signal_library" and symbol:
                    # Extract signal_name from summary_short (format: "name|direction")
                    signal_name = summary.split("|")[0] if "|" in summary else summary
                    keys.add(f"signal_library:{symbol}:{signal_name}")
                elif producer == "policy_news":
                    title_hash = hashlib.md5(  # noqa: S324
                        summary.encode()
                    ).hexdigest()[:12]
                    keys.add(f"policy_news::{title_hash}")
        except Exception:
            logger.debug("Could not load recent signals for dedup", exc_info=True)
        return keys

    def _store_and_route(self, signal: MarketSignal) -> None:
        """Store signal and route through notification orchestrator."""
        try:
            self._signal_store.store(signal)
        except Exception:
            logger.warning("Failed to store signal %s", signal.signal_id, exc_info=True)

        try:
            self._notification_orchestrator.process(signal)
        except Exception:
            logger.debug(
                "Orchestrator routing failed for %s",
                signal.signal_id,
                exc_info=True,
            )
