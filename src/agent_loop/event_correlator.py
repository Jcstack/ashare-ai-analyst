"""Cross-event correlation detector.

Detects when multiple events on the same symbol or sector form a
meaningful pattern within a time window. Three pattern types:

- **triple_resonance**: same symbol has price_spike + news + scanner
  candidate within 60s
- **sector_cascade**: 3+ stocks in the same sector all spike within 5 min
- **sentiment_shift**: regime change event + multiple price spikes

Pure Python — no external dependencies except logging.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("agent_loop.event_correlator")

# Time windows in seconds
_RESONANCE_WINDOW = 60.0  # triple resonance: 60s
_CASCADE_WINDOW = 300.0  # sector cascade: 5 min
_SENTIMENT_WINDOW = 300.0  # sentiment shift: 5 min
_EVENT_TTL = 300.0  # events expire after 5 min
_MAX_EVENTS = 100  # sliding window capacity


@dataclass
class Event:
    """A single event in the correlation window.

    Attributes:
        event_type: Type tag (e.g. 'price_spike', 'news', 'scanner_candidate',
            'volume_anomaly', 'regime_change').
        symbol: Stock code (6-digit) or '' for market-wide events.
        sector: Sector/concept name or ''.
        severity: Event severity score (0.0-1.0).
        timestamp: Unix timestamp when the event occurred.
        data: Arbitrary payload.
    """

    event_type: str
    symbol: str = ""
    sector: str = ""
    severity: float = 0.5
    timestamp: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class CorrelationPattern:
    """A detected cross-event correlation pattern.

    Attributes:
        pattern_type: One of 'triple_resonance', 'sector_cascade',
            'sentiment_shift'.
        symbols: Stock codes involved.
        sector: Sector involved (if applicable).
        events: The contributing events.
        severity: Combined severity score.
        detected_at: Unix timestamp of detection.
        description: Human-readable description.
    """

    pattern_type: str
    symbols: list[str] = field(default_factory=list)
    sector: str = ""
    events: list[Event] = field(default_factory=list)
    severity: float = 0.0
    detected_at: float = 0.0
    description: str = ""


class EventCorrelator:
    """Sliding-window cross-event correlation detector.

    Maintains a bounded deque of recent events and detects three
    pattern types when ``detect_patterns()`` is called.

    Args:
        max_events: Maximum events in the sliding window.
        event_ttl: Time-to-live for events in seconds.
    """

    def __init__(
        self,
        max_events: int = _MAX_EVENTS,
        event_ttl: float = _EVENT_TTL,
    ) -> None:
        self._events: deque[Event] = deque(maxlen=max_events)
        self._event_ttl = event_ttl
        # Cache of recently detected patterns to avoid duplicates
        self._recent_patterns: deque[tuple[str, float]] = deque(maxlen=50)

    def add_event(self, event: Event) -> None:
        """Add an event to the sliding window.

        Assigns a timestamp if not set, then prunes expired events.

        Args:
            event: The event to add.
        """
        if event.timestamp <= 0:
            event.timestamp = time.time()

        self._events.append(event)
        self._prune_expired()

        logger.debug(
            "Event added: type=%s symbol=%s sector=%s severity=%.2f",
            event.event_type,
            event.symbol,
            event.sector,
            event.severity,
        )

    def detect_patterns(self) -> list[CorrelationPattern]:
        """Scan the event window for correlation patterns.

        Checks for:
            1. Triple resonance (same symbol, 3 event types, 60s)
            2. Sector cascade (3+ symbols in same sector, all spiking, 5 min)
            3. Sentiment shift (regime change + price spikes, 5 min)

        Returns:
            List of detected CorrelationPattern objects. May be empty.
        """
        self._prune_expired()
        now = time.time()
        patterns: list[CorrelationPattern] = []

        # 1. Triple resonance
        patterns.extend(self._detect_triple_resonance(now))

        # 2. Sector cascade
        patterns.extend(self._detect_sector_cascade(now))

        # 3. Sentiment shift
        patterns.extend(self._detect_sentiment_shift(now))

        # Deduplicate against recently reported patterns
        novel: list[CorrelationPattern] = []
        for p in patterns:
            key = (p.pattern_type, ",".join(sorted(p.symbols)))
            if not self._is_duplicate(key, now):
                novel.append(p)
                self._recent_patterns.append((f"{key[0]}:{key[1]}", now))

        if novel:
            logger.info("Detected %d correlation patterns", len(novel))
        return novel

    def get_severity_boost(self, symbol: str) -> float:
        """Compute a severity boost for a symbol based on active correlations.

        The boost increases when a symbol appears in multiple recent
        events, indicating convergent evidence.

        Args:
            symbol: 6-digit stock code.

        Returns:
            Boost value (0.0 to 0.5). Add to the event's base severity.
        """
        if not symbol:
            return 0.0

        self._prune_expired()
        now = time.time()

        # Count distinct event types for this symbol in the last 5 min
        event_types: set[str] = set()
        total_severity = 0.0

        for event in self._events:
            if event.symbol != symbol:
                continue
            if now - event.timestamp > _EVENT_TTL:
                continue
            event_types.add(event.event_type)
            total_severity += event.severity

        n_types = len(event_types)
        if n_types <= 1:
            return 0.0

        # 2 types -> 0.1, 3 types -> 0.25, 4+ types -> 0.4
        boost = min(0.5, (n_types - 1) * 0.15)

        # Small additional boost from average severity
        if n_types > 0:
            avg_sev = total_severity / max(n_types, 1)
            boost += avg_sev * 0.1

        return min(0.5, round(boost, 3))

    # ── Pattern detectors ────────────────────────────────────

    def _detect_triple_resonance(self, now: float) -> list[CorrelationPattern]:
        """Detect triple resonance: same symbol has 3+ event types within 60s.

        A symbol that simultaneously triggers a price spike, a news hit,
        and a scanner candidate is a high-conviction signal.
        """
        # Group events by symbol within the resonance window
        symbol_events: dict[str, list[Event]] = defaultdict(list)
        for event in self._events:
            if not event.symbol:
                continue
            if now - event.timestamp > _RESONANCE_WINDOW:
                continue
            symbol_events[event.symbol].append(event)

        patterns: list[CorrelationPattern] = []
        resonance_types = {"price_spike", "news", "scanner_candidate"}

        for symbol, events in symbol_events.items():
            found_types = {e.event_type for e in events}
            matched = found_types & resonance_types
            if len(matched) >= 3:
                combined_severity = min(
                    1.0,
                    sum(e.severity for e in events) / len(events) + 0.2,
                )
                patterns.append(
                    CorrelationPattern(
                        pattern_type="triple_resonance",
                        symbols=[symbol],
                        events=list(events),
                        severity=combined_severity,
                        detected_at=now,
                        description=(
                            f"{symbol} 三重共振: "
                            f"价格异动+新闻+扫描候选 在60秒内同时出现"
                        ),
                    )
                )

        return patterns

    def _detect_sector_cascade(self, now: float) -> list[CorrelationPattern]:
        """Detect sector cascade: 3+ stocks in same sector spike within 5 min.

        When multiple stocks in a sector all show price_spike or
        volume_anomaly simultaneously, the sector itself is moving.
        """
        spike_types = {"price_spike", "volume_anomaly"}

        # Group spike events by sector
        sector_symbols: dict[str, dict[str, list[Event]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for event in self._events:
            if not event.sector or not event.symbol:
                continue
            if now - event.timestamp > _CASCADE_WINDOW:
                continue
            if event.event_type in spike_types:
                sector_symbols[event.sector][event.symbol].append(event)

        patterns: list[CorrelationPattern] = []

        for sector, sym_map in sector_symbols.items():
            if len(sym_map) < 3:
                continue

            all_events = [e for evts in sym_map.values() for e in evts]
            combined_severity = min(
                1.0,
                sum(e.severity for e in all_events) / len(all_events) + 0.15,
            )
            patterns.append(
                CorrelationPattern(
                    pattern_type="sector_cascade",
                    symbols=sorted(sym_map.keys()),
                    sector=sector,
                    events=all_events,
                    severity=combined_severity,
                    detected_at=now,
                    description=(
                        f"板块联动: {sector} 中 {len(sym_map)} 只股票在5分钟内同时异动"
                    ),
                )
            )

        return patterns

    def _detect_sentiment_shift(self, now: float) -> list[CorrelationPattern]:
        """Detect sentiment shift: regime change + multiple price spikes.

        A regime_change event followed by broad price spikes suggests
        a market-wide sentiment transition.
        """
        regime_events: list[Event] = []
        spike_events: list[Event] = []

        for event in self._events:
            if now - event.timestamp > _SENTIMENT_WINDOW:
                continue
            if event.event_type == "regime_change":
                regime_events.append(event)
            elif event.event_type in ("price_spike", "volume_anomaly"):
                spike_events.append(event)

        if not regime_events or len(spike_events) < 2:
            return []

        # Require spikes to come after the regime change
        latest_regime = max(regime_events, key=lambda e: e.timestamp)
        post_spikes = [
            e for e in spike_events if e.timestamp >= latest_regime.timestamp
        ]

        if len(post_spikes) < 2:
            return []

        all_events = [latest_regime, *post_spikes]
        spike_symbols = sorted({e.symbol for e in post_spikes if e.symbol})
        combined_severity = min(
            1.0,
            latest_regime.severity * 0.5
            + sum(e.severity for e in post_spikes) / len(post_spikes) * 0.5
            + 0.1,
        )

        return [
            CorrelationPattern(
                pattern_type="sentiment_shift",
                symbols=spike_symbols,
                events=all_events,
                severity=combined_severity,
                detected_at=now,
                description=(
                    f"情绪切换: 市场regime变化后 {len(post_spikes)} 只股票"
                    f"出现异动 ({', '.join(spike_symbols[:5])})"
                ),
            )
        ]

    # ── Internals ────────────────────────────────────────────

    def _prune_expired(self) -> None:
        """Remove events older than the TTL from the window."""
        cutoff = time.time() - self._event_ttl
        while self._events and self._events[0].timestamp < cutoff:
            self._events.popleft()

    def _is_duplicate(self, key: tuple[str, str], now: float) -> bool:
        """Check if a pattern with the same key was reported recently.

        Args:
            key: (pattern_type, sorted symbols string).
            now: Current timestamp.

        Returns:
            True if the same pattern was detected within the last 60s.
        """
        combined = f"{key[0]}:{key[1]}"
        for stored_key, ts in self._recent_patterns:
            if stored_key == combined and now - ts < 60.0:
                return True
        return False
