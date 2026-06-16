"""Signal aggregator — merges multiple signal sources into one ranked pipeline.

Collects signals from recommendation, technical, rotation, black-swan, thesis,
and factor engines, normalizes them into AggregatedSignal, then ranks and
deduplicates for the trading loop's decision pipeline.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from src.agent_loop.models import AggregatedSignal, SignalDirection, UrgencyTier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_URGENCY_WEIGHTS: dict[UrgencyTier, float] = {
    UrgencyTier.CRITICAL: 10.0,
    UrgencyTier.HIGH: 5.0,
    UrgencyTier.NORMAL: 2.0,
    UrgencyTier.DEEP: 1.0,
}

_FRESHNESS_FULL_MINUTES = 15  # full score if signal age < 15 min
_FRESHNESS_DECAY_PER_HOUR = 0.1

# Minimum confidence threshold for recommendation signals.
_REC_CONFIDENCE_THRESHOLD = 0.3


class SignalAggregator:
    """Merge heterogeneous signal sources into a single ranked pipeline.

    Stateless between cycles — the trading loop calls :meth:`clear` at cycle
    start, feeds signals from each source, then calls
    :meth:`rank_and_deduplicate` to obtain the top-N actionable signals.
    """

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}
        self._dedup_window_hours: float = cfg.get("signal_dedup_window_hours", 1)
        self._max_signals: int = cfg.get("max_signals_per_cycle", 10)
        self._buffer: list[AggregatedSignal] = []

    # ------------------------------------------------------------------
    # Core buffer operations
    # ------------------------------------------------------------------

    def add_signal(self, signal: AggregatedSignal) -> None:
        """Add a signal to the current cycle's buffer."""
        signal.priority_score = self.compute_priority_score(signal)
        self._buffer.append(signal)
        logger.debug(
            "Buffered signal %s: %s %s (priority=%.2f)",
            signal.signal_id[:8],
            signal.direction.value,
            signal.symbol,
            signal.priority_score,
        )

    def clear(self) -> None:
        """Clear the signal buffer for next cycle."""
        self._buffer.clear()

    # ------------------------------------------------------------------
    # Source-specific converters
    # ------------------------------------------------------------------

    def add_from_recommendation(self, rec: dict) -> AggregatedSignal | None:
        """Convert a recommendation dict to *AggregatedSignal*.

        Expected keys: ``symbol``, ``name``, ``score``, ``confidence``,
        ``reasoning``, ``entry_price``, ``target_price``, ``stop_loss``.

        Returns ``None`` if confidence is below threshold.
        """
        confidence = float(rec.get("confidence", 0))
        if confidence < _REC_CONFIDENCE_THRESHOLD:
            return None

        signal = AggregatedSignal(
            symbol=rec["symbol"],
            name=rec.get("name", ""),
            direction=SignalDirection.BUY,
            source="recommendation",
            confidence=confidence,
            urgency=UrgencyTier.NORMAL,
            reason=rec.get("reasoning", ""),
            metadata={
                "score": rec.get("score"),
                "entry_price": rec.get("entry_price"),
                "target_price": rec.get("target_price"),
                "stop_loss": rec.get("stop_loss"),
            },
        )
        self.add_signal(signal)
        return signal

    def add_from_technical(self, signal_dict: dict) -> AggregatedSignal | None:
        """Convert a technical signal dict to *AggregatedSignal*.

        Expected keys: ``symbol``, ``name``, ``signal_type``, ``direction``,
        ``confidence``, ``summary_short``.
        """
        direction = self._parse_direction(signal_dict.get("direction", "hold"))
        confidence = float(signal_dict.get("confidence", 0))

        signal = AggregatedSignal(
            symbol=signal_dict["symbol"],
            name=signal_dict.get("name", ""),
            direction=direction,
            source="technical",
            confidence=confidence,
            urgency=UrgencyTier.NORMAL,
            reason=signal_dict.get("summary_short", ""),
            metadata={"signal_type": signal_dict.get("signal_type")},
        )
        self.add_signal(signal)
        return signal

    def add_from_rotation(self, profile: dict) -> AggregatedSignal | None:
        """Convert a rotation profile to *AggregatedSignal*.

        Expected keys: ``symbol``, ``name``, ``rotation_signal``,
        ``rotation_reason``, ``macro_score``.
        """
        rotation_signal = profile.get("rotation_signal", "hold")
        direction = self._parse_direction(rotation_signal)
        macro_score = float(profile.get("macro_score", 0.5))

        signal = AggregatedSignal(
            symbol=profile["symbol"],
            name=profile.get("name", ""),
            direction=direction,
            source="rotation",
            confidence=macro_score,
            urgency=UrgencyTier.NORMAL,
            reason=profile.get("rotation_reason", ""),
            metadata={"macro_score": macro_score},
        )
        self.add_signal(signal)
        return signal

    def add_from_black_swan(self, alert: dict) -> AggregatedSignal | None:
        """Convert a black-swan alert to *AggregatedSignal* instances.

        Always assigned ``CRITICAL`` urgency.  Creates one signal per
        affected symbol.  Returns the last created signal (or ``None``
        if no symbols are affected).

        Expected keys: ``alert_level``, ``message``, ``affected_symbols``
        (list of ``{"symbol": ..., "name": ...}`` dicts or plain strings).
        """
        affected = alert.get("affected_symbols", [])
        if not affected:
            return None

        last: AggregatedSignal | None = None
        for entry in affected:
            if isinstance(entry, dict):
                symbol = entry.get("symbol", "")
                name = entry.get("name", "")
            else:
                symbol = str(entry)
                name = ""

            signal = AggregatedSignal(
                symbol=symbol,
                name=name,
                direction=SignalDirection.SELL,
                source="black_swan",
                confidence=1.0,
                urgency=UrgencyTier.CRITICAL,
                reason=alert.get("message", "Black swan event detected"),
                metadata={"alert_level": alert.get("alert_level")},
            )
            self.add_signal(signal)
            last = signal

        return last

    def add_from_thesis_invalidation(
        self, symbol: str, name: str, reason: str
    ) -> AggregatedSignal:
        """Generate a SELL signal from thesis invalidation (HIGH urgency)."""
        signal = AggregatedSignal(
            symbol=symbol,
            name=name,
            direction=SignalDirection.SELL,
            source="thesis_invalidation",
            confidence=0.9,
            urgency=UrgencyTier.HIGH,
            reason=reason,
        )
        self.add_signal(signal)
        return signal

    def add_from_stop_loss(
        self, symbol: str, name: str, change_pct: float, stop_loss_pct: float
    ) -> AggregatedSignal:
        """Generate a CRITICAL SELL signal for stop-loss breach — no debate."""
        signal = AggregatedSignal(
            symbol=symbol,
            name=name,
            direction=SignalDirection.SELL,
            source="stop_loss",
            confidence=0.99,
            urgency=UrgencyTier.CRITICAL,
            reason=f"止损触发: 跌幅{change_pct:.1%} 超过止损线{stop_loss_pct:.1%}",
        )
        self.add_signal(signal)
        return signal

    # ------------------------------------------------------------------
    # Ranking & deduplication
    # ------------------------------------------------------------------

    def rank_and_deduplicate(self) -> list[AggregatedSignal]:
        """Rank buffered signals and deduplicate.

        Deduplication rule: same ``symbol`` + same ``direction`` within
        *dedup_window_hours* are merged — only the signal with the highest
        confidence is kept.

        Returns the top *max_signals_per_cycle* signals sorted descending
        by ``priority_score``.
        """
        # Recompute priority scores (timestamps may have shifted).
        for sig in self._buffer:
            sig.priority_score = self.compute_priority_score(sig)

        # Deduplicate: keep highest-confidence per (symbol, direction) within
        # the dedup window.
        window = timedelta(hours=self._dedup_window_hours)
        deduped: dict[tuple[str, SignalDirection], AggregatedSignal] = {}

        # Sort buffer by confidence descending so the first seen wins.
        for sig in sorted(self._buffer, key=lambda s: s.confidence, reverse=True):
            key = (sig.symbol, sig.direction)
            existing = deduped.get(key)
            if existing is None:
                deduped[key] = sig
            else:
                # Merge only if within the dedup window.
                delta = abs(sig.timestamp - existing.timestamp)
                if delta <= window:
                    # Already kept the higher-confidence one (sorted desc).
                    continue
                # Outside window — treat as distinct; use a unique key.
                alt_key = (f"{sig.symbol}:{sig.signal_id[:8]}", sig.direction)
                deduped[alt_key] = sig  # type: ignore[index]

        ranked = sorted(deduped.values(), key=lambda s: s.priority_score, reverse=True)
        result = ranked[: self._max_signals]

        logger.info(
            "Ranked %d signals → %d after dedup → returning top %d",
            len(self._buffer),
            len(ranked),
            len(result),
        )
        return result

    # ------------------------------------------------------------------
    # Priority scoring
    # ------------------------------------------------------------------

    @staticmethod
    def compute_priority_score(signal: AggregatedSignal) -> float:
        """Compute priority score for ranking.

        ``priority_score = urgency_weight * confidence * freshness_decay``

        * Urgency weights: CRITICAL=10, HIGH=5, NORMAL=2, DEEP=1
        * Freshness: 1.0 if signal is < 15 min old, decays 0.1 per hour
          thereafter (floored at 0.1).
        """
        urgency_weight = _URGENCY_WEIGHTS.get(signal.urgency, 2.0)
        confidence = max(0.0, min(1.0, signal.confidence))

        age = datetime.now(UTC) - signal.timestamp
        age_minutes = age.total_seconds() / 60.0

        if age_minutes <= _FRESHNESS_FULL_MINUTES:
            freshness = 1.0
        else:
            hours_past = (age_minutes - _FRESHNESS_FULL_MINUTES) / 60.0
            freshness = max(0.1, 1.0 - _FRESHNESS_DECAY_PER_HOUR * hours_past)

        return urgency_weight * confidence * freshness

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_direction(raw: str) -> SignalDirection:
        """Best-effort parse of a direction string to :class:`SignalDirection`."""
        mapping: dict[str, SignalDirection] = {
            "buy": SignalDirection.BUY,
            "bullish": SignalDirection.BUY,
            "long": SignalDirection.BUY,
            "sell": SignalDirection.SELL,
            "bearish": SignalDirection.SELL,
            "short": SignalDirection.SELL,
            "hold": SignalDirection.HOLD,
            "neutral": SignalDirection.HOLD,
            "reduce": SignalDirection.REDUCE,
            "add": SignalDirection.ADD,
        }
        return mapping.get(raw.lower().strip(), SignalDirection.HOLD)
