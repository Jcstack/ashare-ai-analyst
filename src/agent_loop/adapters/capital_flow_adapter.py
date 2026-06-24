"""Capital flow adapter — wraps sector flow, northbound flow, institutional flow.

Produces SignalEvidence with independence_group=CAPITAL_FLOW.
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


def _flow_direction(net_inflow: float, threshold: float = 0.0) -> SignalDirection:
    """Determine signal direction from net inflow value."""
    if net_inflow > threshold:
        return SignalDirection.BUY
    if net_inflow < -threshold:
        return SignalDirection.SELL
    return SignalDirection.HOLD


def _flow_confidence(net_inflow: float, scale: float = 1e8) -> float:
    """Map net inflow magnitude to confidence [0, 1].

    Uses a simple sigmoid-like mapping: confidence = |inflow| / (|inflow| + scale).
    """
    abs_flow = abs(net_inflow)
    return min(1.0, abs_flow / (abs_flow + scale))


class CapitalFlowAdapter:
    """Adapter that converts capital flow data to SignalEvidence.

    Accepts pre-computed flow data dicts from sector_flow_fetcher,
    northbound flow APIs, or macro_flow_fetcher output.
    """

    domain: str = "capital_flow"

    def __init__(
        self,
        sector_flows: list[dict[str, Any]] | None = None,
        northbound_flows: list[dict[str, Any]] | None = None,
        institutional_flows: list[dict[str, Any]] | None = None,
    ) -> None:
        self._sector_flows = sector_flows or []
        self._northbound_flows = northbound_flows or []
        self._institutional_flows = institutional_flows or []

    def collect_signals(
        self,
        symbols: list[str],
        portfolio_context: dict[str, Any] | None = None,
    ) -> list[SignalEvidence]:
        """Convert pre-loaded flow data to SignalEvidence."""
        results: list[SignalEvidence] = []
        symbol_set = set(symbols)

        for flow in self._sector_flows:
            symbol = flow.get("symbol", "")
            if symbol_set and symbol not in symbol_set:
                continue
            net_inflow = float(flow.get("net_inflow", 0))
            direction = _flow_direction(net_inflow)
            if direction == SignalDirection.HOLD:
                continue

            results.append(
                SignalEvidence(
                    domain=self.domain,
                    signal_type="flow/sector_rotation",
                    symbol=symbol,
                    direction=direction,
                    confidence=_flow_confidence(net_inflow),
                    independence_group=IndependenceGroup.CAPITAL_FLOW,
                    metadata={
                        "net_inflow": net_inflow,
                        "sector_name": flow.get("sector_name", ""),
                    },
                    source_description=flow.get("description", "Sector flow signal"),
                )
            )

        for flow in self._northbound_flows:
            symbol = flow.get("symbol", "")
            if symbol_set and symbol not in symbol_set:
                continue
            net_inflow = float(flow.get("net_buy", 0))
            direction = _flow_direction(net_inflow)
            if direction == SignalDirection.HOLD:
                continue

            results.append(
                SignalEvidence(
                    domain=self.domain,
                    signal_type="flow/northbound",
                    symbol=symbol,
                    direction=direction,
                    confidence=_flow_confidence(net_inflow, scale=5e7),
                    independence_group=IndependenceGroup.CAPITAL_FLOW,
                    metadata={"net_buy": net_inflow},
                    source_description=flow.get(
                        "description", "Northbound flow signal"
                    ),
                )
            )

        for flow in self._institutional_flows:
            symbol = flow.get("symbol", "")
            if symbol_set and symbol not in symbol_set:
                continue
            net_inflow = float(flow.get("institutional_net", 0))
            direction = _flow_direction(net_inflow)
            if direction == SignalDirection.HOLD:
                continue

            results.append(
                SignalEvidence(
                    domain=self.domain,
                    signal_type="flow/institutional",
                    symbol=symbol,
                    direction=direction,
                    confidence=_flow_confidence(net_inflow, scale=2e7),
                    independence_group=IndependenceGroup.CAPITAL_FLOW,
                    metadata={"institutional_net": net_inflow},
                    source_description=flow.get(
                        "description", "Institutional flow signal"
                    ),
                )
            )

        logger.debug("CapitalFlowAdapter produced %d signals", len(results))
        return results

    def get_signal_types(self) -> list[str]:
        """Return signal types this adapter produces."""
        return [
            "flow/northbound",
            "flow/institutional",
            "flow/sector_rotation",
        ]
