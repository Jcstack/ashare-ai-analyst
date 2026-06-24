"""Event Impact Engine — transforms raw events into tradeable signal evidence.

Sits between the event detection layer (InfoAggregator, intelligence sources)
and the signal engine (SignalAggregator). Processes events through causal
impact chains and produces per-stock signal evidence dicts.

Part of v50.0 Intelligence System Redesign.
"""

from __future__ import annotations

import logging
from typing import Any

from src.intelligence.causal_chain import CausalChain, CausalChainConstructor

logger = logging.getLogger(__name__)


class EventImpactEngine:
    """Transforms raw events into tradeable impact chains.

    Pipeline:
        event dict → CausalChainConstructor → CausalChain → per-stock signals

    The output signal dicts are compatible with SignalAggregator.add_from_impact().
    """

    def __init__(
        self,
        chain_constructor: CausalChainConstructor | None = None,
        stock_sector_map: dict[str, list[str]] | None = None,
    ) -> None:
        self._constructor = chain_constructor or CausalChainConstructor()
        self._sector_stocks: dict[str, list[str]] = stock_sector_map or {}

    def process_event(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        """Process an event through the impact chain and produce signal evidence.

        Args:
            event: Dict with keys like title, summary, confidence, sectors, etc.

        Returns:
            List of signal evidence dicts ready for SignalAggregator, one per
            affected stock. Each dict contains: symbol, direction, confidence,
            source, signal_type, and metadata.
        """
        chain = self._constructor.construct_chain(event)
        if not chain:
            return []

        return self._chain_to_signals(chain)

    async def process_event_async(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        """Async version with LLM fallback for novel events."""
        chain = await self._constructor.construct_chain_async(event)
        if not chain:
            return []

        return self._chain_to_signals(chain)

    def _chain_to_signals(self, chain: CausalChain) -> list[dict[str, Any]]:
        """Convert a CausalChain into per-stock signal evidence dicts."""
        signals: list[dict[str, Any]] = []

        for link in chain.chain:
            stocks = self._resolve_stocks(link.sectors)
            for stock in stocks:
                signals.append(
                    {
                        "symbol": stock,
                        "direction": link.direction,
                        "confidence": link.confidence,
                        "source": f"impact_chain:{chain.event_type}",
                        "signal_type": f"intel/{chain.event_type}",
                        "metadata": {
                            "event": chain.event_description,
                            "impact_order": link.order,
                            "impact": link.impact,
                            "chain_id": chain.event_id,
                            "base_confidence": chain.base_confidence,
                        },
                    }
                )

        logger.info(
            "Event '%s' → %d signals via %d chain links",
            chain.event_description[:40],
            len(signals),
            len(chain.chain),
        )
        return signals

    def _resolve_stocks(self, sectors: list[str]) -> list[str]:
        """Map sector names to stock symbols using the sector-stock mapping."""
        stocks: list[str] = []
        for sector in sectors:
            sector_stocks = self._sector_stocks.get(sector, [])
            for s in sector_stocks:
                if s not in stocks:
                    stocks.append(s)
        return stocks

    def update_sector_map(self, sector_stocks: dict[str, list[str]]) -> None:
        """Update the sector-to-stocks mapping at runtime."""
        self._sector_stocks = sector_stocks
        logger.info(
            "Updated sector map: %d sectors, %d total stocks",
            len(sector_stocks),
            sum(len(v) for v in sector_stocks.values()),
        )
