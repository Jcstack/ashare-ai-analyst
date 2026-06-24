"""Research Coordinator — routes market events to appropriate research agents.

Registers event handlers on the IntelligenceEventBus and routes
events to the appropriate agents for analysis. Results are
published back as trading signals via the SignalAggregator.

This is the central dispatcher for event-driven intelligence.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from src.intelligence.event_bus import (
    EventType,
    IntelligenceEventBus,
    MarketEvent,
)
from src.utils.logger import get_logger

logger = get_logger("intelligence.agents.research_coordinator")

# Timeout for individual agent processing (seconds)
_AGENT_TIMEOUT_S = 60


class ResearchCoordinator:
    """Coordinates research agents in response to market events.

    Registers event handlers on the IntelligenceEventBus and routes
    events to the appropriate agents for analysis. Results are
    published back as trading signals.
    """

    def __init__(
        self,
        event_bus: IntelligenceEventBus,
        causal_chain_agent: Any | None = None,
        opportunity_scanner: Any | None = None,
        macro_pulse_agent: Any | None = None,
        event_understanding_agent: Any | None = None,
        signal_aggregator: Any | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._causal_chain_agent = causal_chain_agent
        self._opportunity_scanner = opportunity_scanner
        self._macro_pulse_agent = macro_pulse_agent
        self._event_understanding_agent = event_understanding_agent
        self._signal_aggregator = signal_aggregator
        self._processed_count = 0

        # Register handlers
        event_bus.register_handler(EventType.NEWS, self._handle_news)
        event_bus.register_handler(EventType.PRICE_SPIKE, self._handle_price_spike)
        event_bus.register_handler(EventType.POLICY, self._handle_policy)
        event_bus.register_handler(EventType.LIMIT_UP, self._handle_limit_up)
        event_bus.register_handler(
            EventType.CAPITAL_FLOW_ANOMALY, self._handle_flow_anomaly
        )
        event_bus.register_handler(
            EventType.SECTOR_ROTATION, self._handle_sector_rotation
        )

        logger.info(
            "ResearchCoordinator initialized with agents: "
            "causal_chain=%s, opportunity=%s, macro=%s, understanding=%s",
            causal_chain_agent is not None,
            opportunity_scanner is not None,
            macro_pulse_agent is not None,
            event_understanding_agent is not None,
        )

    async def _handle_news(self, event: MarketEvent) -> None:
        """Route news to event understanding + causal chain agent -> produce signals."""
        logger.debug("Handling news event: %s", event.data.get("title", "")[:60])

        understanding = None
        # Step 1: Understand the event
        if self._event_understanding_agent:
            try:
                understanding = self._event_understanding_agent.analyze_item(
                    title=event.data.get("title", ""),
                    summary=event.data.get("summary", ""),
                    layer=event.data.get("layer", "L4"),
                    url=event.data.get("url", ""),
                )
            except Exception as exc:
                logger.warning("Event understanding failed: %s", exc)

        # Step 2: Build causal chains if relevant
        if self._causal_chain_agent and understanding:
            if understanding.a_share_relevance >= 0.3:
                try:
                    chains = self._causal_chain_agent.build_chains(
                        event_text=understanding.one_line_summary
                        or event.data.get("title", ""),
                        event_type=understanding.event_type,
                        domains=understanding.affected_domains,
                        sectors=understanding.key_sectors,
                        a_share_relevance=understanding.a_share_relevance,
                    )
                    # Step 3: Scan for opportunities from chains
                    if chains and self._opportunity_scanner:
                        await self._scan_opportunities(understanding.to_dict(), chains)
                except Exception as exc:
                    logger.warning("Causal chain building failed: %s", exc)

        self._processed_count += 1

    async def _handle_price_spike(self, event: MarketEvent) -> None:
        """Route price spikes to opportunity scanner."""
        logger.debug(
            "Handling price spike: %s pct=%.2f",
            event.symbol,
            event.data.get("pct_change", 0),
        )

        if self._opportunity_scanner:
            try:
                event_dict = {
                    "one_line_summary": (
                        f"{event.symbol} "
                        f"{'大涨' if event.data.get('pct_change', 0) > 0 else '大跌'}"
                        f"{abs(event.data.get('pct_change', 0)):.1f}%"
                    ),
                    "event_type": "market_move",
                    "a_share_relevance": 0.9,
                }

                # Build a simple causal chain for the spike
                chains = [
                    {
                        "trigger_type": "market_move",
                        "paths": [
                            {
                                "cause": event_dict["one_line_summary"],
                                "effect": "板块联动效应",
                                "direction": (
                                    "positive"
                                    if event.data.get("pct_change", 0) > 0
                                    else "negative"
                                ),
                                "magnitude": (
                                    "strong"
                                    if abs(event.data.get("pct_change", 0)) > 5
                                    else "moderate"
                                ),
                                "affected_stocks": (
                                    [event.symbol] if event.symbol else []
                                ),
                                "affected_sectors": [],
                                "lag": "immediate",
                            }
                        ],
                        "confidence": event.severity,
                    }
                ]
                await self._scan_opportunities(event_dict, chains)
            except Exception as exc:
                logger.warning("Price spike handling failed: %s", exc)

        self._processed_count += 1

    async def _handle_policy(self, event: MarketEvent) -> None:
        """Route policy events to macro pulse agent for sector analysis."""
        logger.debug("Handling policy event: %s", event.data.get("title", "")[:60])

        understanding = None
        # Understand the policy event
        if self._event_understanding_agent:
            try:
                understanding = self._event_understanding_agent.analyze_item(
                    title=event.data.get("title", ""),
                    summary=event.data.get("summary", ""),
                    layer="L1",  # policy events are high-credibility
                )
            except Exception as exc:
                logger.warning("Policy understanding failed: %s", exc)

        # Build sector-wide causal chains
        if self._causal_chain_agent:
            try:
                sectors = event.data.get("affected_sectors", [])
                if understanding:
                    sectors = understanding.key_sectors or sectors

                chains = self._causal_chain_agent.build_chains(
                    event_text=event.data.get("title", ""),
                    event_type="policy_change",
                    domains=["regulatory", "monetary"],
                    sectors=sectors,
                    a_share_relevance=0.9,
                )
                if chains and self._opportunity_scanner:
                    event_dict = (
                        understanding.to_dict()
                        if understanding
                        else {
                            "one_line_summary": event.data.get("title", ""),
                            "event_type": "policy_change",
                        }
                    )
                    await self._scan_opportunities(event_dict, chains)
            except Exception as exc:
                logger.warning("Policy chain building failed: %s", exc)

        self._processed_count += 1

    async def _handle_limit_up(self, event: MarketEvent) -> None:
        """Route limit-up events for leader detection and sector analysis."""
        logger.debug(
            "Handling limit-up: %s (%s) seal=%.2f",
            event.symbol,
            event.data.get("name", ""),
            event.data.get("seal_ratio", 0),
        )

        # Limit-up events generate buy signals directly via signal aggregator
        if self._signal_aggregator:
            try:
                seal_ratio = event.data.get("seal_ratio", 0.5)
                confidence = min(0.8, 0.5 + seal_ratio * 0.3)

                self._signal_aggregator.add_from_global_intelligence(
                    {
                        "stock_code": event.symbol,
                        "stock_name": event.data.get("name", ""),
                        "direction": "long",
                        "strength": event.severity,
                        "source_event": (
                            f"{event.data.get('name', event.symbol)} 涨停"
                            f" 封单比{seal_ratio:.0%}"
                        ),
                        "causal_path": (
                            f"涨停 -> {event.data.get('sector', '板块')}联动效应"
                        ),
                        "time_horizon": "immediate",
                        "confidence": confidence,
                    }
                )
            except Exception as exc:
                logger.warning("Limit-up signal injection failed: %s", exc)

        self._processed_count += 1

    async def _handle_flow_anomaly(self, event: MarketEvent) -> None:
        """Route capital flow anomalies to opportunity scanner."""
        logger.debug(
            "Handling capital flow anomaly: %s", event.data.get("description", "")[:60]
        )

        if self._opportunity_scanner:
            try:
                event_dict = {
                    "one_line_summary": event.data.get("description", "资金流异常"),
                    "event_type": "capital_flow",
                    "a_share_relevance": 0.8,
                }
                chains = [
                    {
                        "trigger_type": "capital_flow",
                        "paths": [
                            {
                                "cause": event.data.get("description", ""),
                                "effect": "资金集中流入/流出",
                                "direction": event.data.get("direction", "positive"),
                                "magnitude": (
                                    "strong" if event.severity > 0.7 else "moderate"
                                ),
                                "affected_stocks": (event.data.get("symbols", [])),
                                "affected_sectors": (event.data.get("sectors", [])),
                                "lag": "immediate",
                            }
                        ],
                        "confidence": event.severity,
                    }
                ]
                await self._scan_opportunities(event_dict, chains)
            except Exception as exc:
                logger.warning("Flow anomaly handling failed: %s", exc)

        self._processed_count += 1

    async def _handle_sector_rotation(self, event: MarketEvent) -> None:
        """Route sector rotation events to opportunity scanner."""
        logger.debug(
            "Handling sector rotation: %s",
            event.data.get("description", "")[:60],
        )
        # Sector rotation is informational; log and track
        self._processed_count += 1

    async def _scan_opportunities(
        self,
        event_dict: dict[str, Any],
        chains: list[dict[str, Any]],
    ) -> None:
        """Run opportunity scanner and inject results into signal aggregator."""
        if not self._opportunity_scanner:
            return

        try:
            signals = await self._opportunity_scanner.scan_opportunities(
                event=event_dict,
                causal_chains=chains,
            )

            if signals and self._signal_aggregator:
                for sig in signals:
                    self._signal_aggregator.add_from_global_intelligence(
                        {
                            "stock_code": sig.stock_code,
                            "stock_name": sig.stock_name,
                            "direction": sig.direction,
                            "strength": sig.strength,
                            "source_event": sig.source_event,
                            "causal_path": sig.causal_path,
                            "time_horizon": sig.time_horizon,
                            "confidence": sig.confidence,
                        }
                    )
                logger.info(
                    "Injected %d signals from event: %s",
                    len(signals),
                    event_dict.get("one_line_summary", "")[:40],
                )
        except Exception as exc:
            logger.warning("Opportunity scanning failed: %s", exc)

    @property
    def processed_count(self) -> int:
        """Number of events processed since initialization."""
        return self._processed_count


# ---------------------------------------------------------------------------
# DI singleton
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_research_coordinator() -> ResearchCoordinator:
    """Get the singleton ResearchCoordinator with all agents wired up."""
    from src.intelligence.event_bus import get_intelligence_event_bus
    from src.intelligence.agents.causal_chain_agent import get_causal_chain_agent
    from src.intelligence.agents.opportunity_scanner_agent import (
        get_opportunity_scanner_agent,
    )
    from src.intelligence.agents.macro_pulse_agent import get_macro_pulse_agent
    from src.intelligence.agents.event_understanding_agent import (
        get_event_understanding_agent,
    )

    return ResearchCoordinator(
        event_bus=get_intelligence_event_bus(),
        causal_chain_agent=get_causal_chain_agent(),
        opportunity_scanner=get_opportunity_scanner_agent(),
        macro_pulse_agent=get_macro_pulse_agent(),
        event_understanding_agent=get_event_understanding_agent(),
    )
