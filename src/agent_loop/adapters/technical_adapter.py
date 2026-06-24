"""Technical signal adapter — wraps existing technical signal generation.

Reads from signal_aggregator's technical signal dict format and produces
typed SignalEvidence with independence_group=PRICE_DERIVED.
"""

from __future__ import annotations

import logging
from typing import Any

from src.agent_loop.domain_adapter import (
    IndependenceGroup,
    SignalDirection,
    SignalEvidence,
)

logger = logging.getLogger(__name__)

# Maps raw direction strings to SignalDirection
_DIRECTION_MAP: dict[str, SignalDirection] = {
    "buy": SignalDirection.BUY,
    "bullish": SignalDirection.BUY,
    "long": SignalDirection.BUY,
    "sell": SignalDirection.SELL,
    "bearish": SignalDirection.SELL,
    "short": SignalDirection.SELL,
    "hold": SignalDirection.HOLD,
    "neutral": SignalDirection.HOLD,
}

# Maps signal_type keywords to canonical signal types
_SIGNAL_TYPE_MAP: dict[str, str] = {
    "macd": "technical/momentum_breakout",
    "rsi": "technical/mean_reversion",
    "bollinger": "technical/mean_reversion",
    "ma_cross": "technical/trend_following",
    "trend": "technical/trend_following",
    "momentum": "technical/momentum_breakout",
    "breakout": "technical/momentum_breakout",
    "reversal": "technical/mean_reversion",
}


def _classify_signal_type(raw_type: str) -> str:
    """Map a raw signal type string to a canonical Bayesian lookup key."""
    raw_lower = raw_type.lower()
    for keyword, canonical in _SIGNAL_TYPE_MAP.items():
        if keyword in raw_lower:
            return canonical
    return "technical/momentum_breakout"


class TechnicalAdapter:
    """Adapter that converts technical signal dicts to SignalEvidence.

    Delegates to existing technical signal logic — this adapter only
    translates the output format, it does not recompute signals.
    """

    domain: str = "technical"

    def __init__(self, signal_dicts: list[dict[str, Any]] | None = None) -> None:
        """Optionally pre-load signal dicts for batch conversion.

        Args:
            signal_dicts: Pre-computed technical signal dicts. If provided,
                these are used by :meth:`collect_signals` instead of
                fetching new signals.
        """
        self._preloaded = signal_dicts or []

    def collect_signals(
        self,
        symbols: list[str],
        portfolio_context: dict[str, Any] | None = None,
    ) -> list[SignalEvidence]:
        """Convert pre-loaded technical signal dicts to SignalEvidence."""
        results: list[SignalEvidence] = []
        symbol_set = set(symbols)

        for sig_dict in self._preloaded:
            symbol = sig_dict.get("symbol", "")
            if symbol_set and symbol not in symbol_set:
                continue

            raw_dir = sig_dict.get("direction", "hold")
            direction = _DIRECTION_MAP.get(
                raw_dir.lower().strip(), SignalDirection.HOLD
            )
            confidence = float(sig_dict.get("confidence", 0))
            if confidence <= 0:
                continue

            raw_type = sig_dict.get("signal_type", "")
            signal_type = _classify_signal_type(raw_type)

            evidence = SignalEvidence(
                domain=self.domain,
                signal_type=signal_type,
                symbol=symbol,
                direction=direction,
                confidence=min(1.0, max(0.0, confidence)),
                independence_group=IndependenceGroup.PRICE_DERIVED,
                metadata={
                    "original_type": raw_type,
                    "name": sig_dict.get("name", ""),
                },
                source_description=sig_dict.get("summary_short", ""),
            )
            results.append(evidence)

        logger.debug("TechnicalAdapter produced %d signals", len(results))
        return results

    def get_signal_types(self) -> list[str]:
        """Return signal types this adapter produces."""
        return [
            "technical/momentum_breakout",
            "technical/mean_reversion",
            "technical/trend_following",
        ]
