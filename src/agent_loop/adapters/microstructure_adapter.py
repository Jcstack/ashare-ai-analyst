"""Microstructure adapter — wraps VPIN, L2 order book, and seal quality signals.

Produces SignalEvidence with independence_group=MICROSTRUCTURE.
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


class MicrostructureAdapter:
    """Adapter that converts microstructure data to SignalEvidence.

    Accepts pre-computed results from VpinCalculator, SignalQualityAnalyzer
    (seal quality, order book quality), and order flow imbalance data.
    """

    domain: str = "microstructure"

    def __init__(
        self,
        vpin_results: list[dict[str, Any]] | None = None,
        seal_results: list[dict[str, Any]] | None = None,
        order_imbalance_results: list[dict[str, Any]] | None = None,
    ) -> None:
        self._vpin_results = vpin_results or []
        self._seal_results = seal_results or []
        self._order_imbalance = order_imbalance_results or []

    def collect_signals(
        self,
        symbols: list[str],
        portfolio_context: dict[str, Any] | None = None,
    ) -> list[SignalEvidence]:
        """Convert microstructure data to SignalEvidence."""
        results: list[SignalEvidence] = []
        symbol_set = set(symbols)

        # VPIN toxicity signals
        for vpin in self._vpin_results:
            symbol = vpin.get("symbol", "")
            if symbol_set and symbol not in symbol_set:
                continue

            toxicity = vpin.get("toxicity_level", "low")
            vpin_val = float(vpin.get("vpin", 0))
            alert = vpin.get("alert", False)

            # High toxicity = informed trading = potential adverse move
            if toxicity in ("elevated", "high") or alert:
                direction = SignalDirection.SELL
                confidence = min(1.0, vpin_val)
            else:
                continue  # Low toxicity is not actionable

            results.append(
                SignalEvidence(
                    domain=self.domain,
                    signal_type="micro/vpin_toxicity",
                    symbol=symbol,
                    direction=direction,
                    confidence=confidence,
                    independence_group=IndependenceGroup.MICROSTRUCTURE,
                    metadata={
                        "vpin": vpin_val,
                        "toxicity_level": toxicity,
                        "alert": alert,
                        "trend": vpin.get("trend", "stable"),
                    },
                    source_description=vpin.get("description", ""),
                )
            )

        # Seal quality signals
        for seal in self._seal_results:
            symbol = seal.get("symbol", "")
            if symbol_set and symbol not in symbol_set:
                continue

            grade = seal.get("grade", "weak")
            ratio = float(seal.get("ratio", 0))

            if grade == "strong":
                direction = SignalDirection.BUY
                confidence = min(1.0, 0.5 + ratio)
            elif grade == "weak":
                direction = SignalDirection.SELL
                confidence = min(1.0, 0.7)
            else:
                continue  # "normal" is not actionable

            results.append(
                SignalEvidence(
                    domain=self.domain,
                    signal_type="micro/seal_quality",
                    symbol=symbol,
                    direction=direction,
                    confidence=confidence,
                    independence_group=IndependenceGroup.MICROSTRUCTURE,
                    metadata={"grade": grade, "ratio": ratio},
                    source_description=seal.get("description", "Seal quality signal"),
                )
            )

        # Order imbalance signals
        for oib in self._order_imbalance:
            symbol = oib.get("symbol", "")
            if symbol_set and symbol not in symbol_set:
                continue

            imbalance = float(oib.get("imbalance", 0))
            if abs(imbalance) < 0.2:
                continue  # Not significant

            direction = SignalDirection.BUY if imbalance > 0 else SignalDirection.SELL
            confidence = min(1.0, abs(imbalance))

            results.append(
                SignalEvidence(
                    domain=self.domain,
                    signal_type="micro/order_imbalance",
                    symbol=symbol,
                    direction=direction,
                    confidence=confidence,
                    independence_group=IndependenceGroup.MICROSTRUCTURE,
                    metadata={"imbalance": imbalance},
                    source_description=oib.get("description", "Order imbalance signal"),
                )
            )

        logger.debug("MicrostructureAdapter produced %d signals", len(results))
        return results

    def get_signal_types(self) -> list[str]:
        """Return signal types this adapter produces."""
        return [
            "micro/vpin_toxicity",
            "micro/seal_quality",
            "micro/order_imbalance",
        ]
