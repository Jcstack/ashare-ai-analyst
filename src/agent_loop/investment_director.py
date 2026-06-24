"""Investment Director — top-level orchestrator for the AI investor agent.

Coordinates 7 agent teams through the daily lifecycle:

  08:00  pre_market_brief()      — overnight analysis, daily plan
  09:15  call_auction_monitor()  — auction signals, candidate confirmation
  09:30  morning_session()       — early-session regime check
  09:30-14:30  intraday via handle_event()  — event-driven micro-OODA
  14:30  late_session()          — signal aggregation, debate, execution plans
  15:05  close_briefing()        — quick close summary
  15:30  post_market_review()    — outcome tracking, calibration, thesis decay

Reads and writes SharedBeliefState for cross-team coordination.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.agent_loop.models import (
    AggregatedSignal,
    CycleState,
    SignalDirection,
    TradeProposal,
    UrgencyTier,
)
from src.agent_loop.shared_belief_state import (
    DailyPlan,
    SharedBeliefState,
)

logger = logging.getLogger(__name__)

_CST = ZoneInfo("Asia/Shanghai")


class InvestmentDirector:
    """Top-level orchestrator coordinating agent teams through the daily lifecycle.

    Lifecycle:
        08:00  pre_market_brief()
        09:15  call_auction_monitor()
        09:30  morning_session()
        09:30-14:30  intraday_monitor() / handle_event()
        14:30  late_session()
        15:05  close_briefing()
        15:30  post_market_review()
    """

    def __init__(
        self,
        belief_state: SharedBeliefState | None = None,
        signal_aggregator: Any = None,
        decision_pipeline: Any = None,
        portfolio_store: Any = None,
        capital_service: Any = None,
        notification_dispatcher: Any = None,
        regime_detector: Any = None,
        debate_engine: Any = None,
        thesis_store: Any = None,
        global_market_fetcher: Any = None,
        decision_log: Any = None,
        calibrator: Any = None,
        call_auction_provider: Any = None,
        convergence_engine: Any = None,
        thesis_tracker: Any = None,
        action_queue_service: Any = None,
        signal_collector: Any = None,
        knowledge_graph: Any = None,
        causal_chain_constructor: Any = None,
        risk_agent: Any = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._belief = belief_state or SharedBeliefState()
        self._signal_agg = signal_aggregator
        self._pipeline = decision_pipeline
        self._portfolio = portfolio_store
        self._capital = capital_service
        self._notifier = notification_dispatcher
        self._regime = regime_detector
        self._debate = debate_engine
        self._thesis_store = thesis_store
        self._global_market = global_market_fetcher
        self._decision_log_store = decision_log
        self._action_queue = action_queue_service
        self._calibrator = calibrator
        self._call_auction = call_auction_provider
        self._convergence = convergence_engine
        self._thesis_tracker = thesis_tracker
        self._signal_collector = signal_collector
        self._knowledge_graph = knowledge_graph
        self._chain_constructor = causal_chain_constructor
        self._risk_agent = risk_agent

        cfg = config or {}
        self._min_confidence = cfg.get("min_confidence_to_propose", 0.6)
        self._event_severity_threshold = cfg.get("event_severity_threshold", 0.5)
        self._late_session_start = cfg.get("late_session_start", "14:30")
        self._late_session_end = cfg.get("late_session_end", "14:50")

        logger.info("InvestmentDirector initialized")

    @staticmethod
    def _fetch_market_daily_returns() -> list[float]:
        """Fetch broad market (上证指数) daily returns for regime detection.

        Returns an empty list on any failure so that RegimeDetector.detect()
        gracefully returns an 'insufficient data' report.
        """
        try:
            from src.data.fetcher import StockDataFetcher

            fetcher = StockDataFetcher()
            df = fetcher.fetch_index("000001")  # 上证综指
            if df is not None and not df.empty and "close" in df.columns:
                returns = df["close"].pct_change().dropna()
                return returns.tolist()
        except Exception as exc:
            logger.warning("Failed to fetch index returns for regime: %s", exc)
        return []

    @property
    def belief_state(self) -> SharedBeliefState:
        """Access the shared belief state."""
        return self._belief

    # ------------------------------------------------------------------
    # Core orchestration — 7 agent teams
    # ------------------------------------------------------------------

    async def coordinate_cycle(
        self,
        state: CycleState,
    ) -> list[TradeProposal]:
        """Orchestrate a full investment cycle through 7 agent teams.

        Teams execute sequentially:
          1. Sentinel  — gather and rank signals
          2. Analyst   — convergence check per signal
          3. Strategist — thesis matching / creation
          4. Risk      — portfolio risk assessment
          5. Trader    — position sizing and execution plan
          6. Reviewer  — mandatory debate for buys
          7. Messenger — format and push proposals

        Args:
            state: Current cycle state (positions, cash, regime, signals).

        Returns:
            List of actionable TradeProposals.
        """
        start = time.monotonic()
        proposals: list[TradeProposal] = []

        # ── 1. SENTINEL — gather and rank signals ──
        if state.pending_signals:
            signals = state.pending_signals
            logger.info(
                "InvestmentDirector | sentinel | using %d pre-collected signals",
                len(signals),
            )
        elif self._signal_agg:
            self._signal_agg.clear()
            await self._collect_buy_signals(state.positions)
            signals = self._signal_agg.rank_and_deduplicate()
            logger.info(
                "InvestmentDirector | sentinel | ranked %d signals from aggregator",
                len(signals),
            )
        else:
            signals = []
            logger.info(
                "InvestmentDirector | sentinel | no signal aggregator — skipped"
            )

        if not signals:
            logger.info(
                "InvestmentDirector | sentinel | no signals — cycle complete (%.1fs)",
                time.monotonic() - start,
            )
            return []

        # ── 2. ANALYST — convergence check per signal ──
        for signal in signals:
            convergence_score: float | None = None
            if self._convergence:
                try:
                    # Build minimal evidence list from aggregated signal for
                    # convergence scoring (the engine expects SignalEvidence).
                    evidence = self._build_evidence_from_signal(signal)
                    if evidence:
                        results = self._convergence.analyze(evidence)
                        if results:
                            convergence_score = results[0].convergence_score
                            signal.metadata["convergence_score"] = convergence_score
                            signal.metadata["converged"] = results[0].converged
                except Exception as exc:
                    logger.warning(
                        "InvestmentDirector | analyst | convergence failed for %s: %s",
                        signal.symbol,
                        exc,
                    )
            logger.info(
                "InvestmentDirector | analyst | %s convergence=%.3f",
                signal.symbol,
                convergence_score if convergence_score is not None else -1,
            )

        # ── 3. STRATEGIST — thesis matching ──
        signal_theses: dict[str, Any] = {}
        for signal in signals:
            thesis = None
            if self._thesis_tracker:
                try:
                    existing = self._thesis_tracker.list_theses(
                        status=None, symbol=signal.symbol
                    )
                    active = [
                        t for t in existing if t.status in ("active", "weakening")
                    ]
                    if active:
                        thesis = active[0]
                        logger.info(
                            "InvestmentDirector | strategist | %s matched thesis %s (conf=%.2f)",
                            signal.symbol,
                            thesis.id[:8],
                            thesis.current_confidence,
                        )
                    else:
                        logger.info(
                            "InvestmentDirector | strategist | %s no active thesis",
                            signal.symbol,
                        )
                except Exception as exc:
                    logger.warning(
                        "InvestmentDirector | strategist | thesis lookup failed for %s: %s",
                        signal.symbol,
                        exc,
                    )
            elif self._thesis_store:
                thesis = self._get_thesis(signal.symbol)
                if thesis:
                    logger.info(
                        "InvestmentDirector | strategist | %s matched thesis via store",
                        signal.symbol,
                    )
            signal_theses[signal.symbol] = thesis

        # ── 4. RISK — portfolio risk assessment ──
        limits = self._belief.get_position_limits()
        available_cash = state.available_cash
        risk_blocked: set[str] = set()

        if self._belief.risk_budget.is_halted:
            # All buys blocked when risk budget is exhausted
            for signal in signals:
                if signal.direction.value in ("buy", "add"):
                    risk_blocked.add(signal.symbol)
            logger.info(
                "InvestmentDirector | risk | budget halted — blocked %d buy signals",
                len(risk_blocked),
            )

        if not limits.get("buys_allowed", True):
            for signal in signals:
                if signal.direction.value in ("buy", "add"):
                    risk_blocked.add(signal.symbol)
            logger.info(
                "InvestmentDirector | risk | %s phase — buys not allowed",
                self._belief.regime.sentiment_phase,
            )

        # Sector concentration check
        total_value = available_cash + sum(
            p.get("market_value", 0) for p in state.positions
        )
        if total_value > 0:
            sector_values: dict[str, float] = {}
            for pos in state.positions:
                sector = pos.get("sector", "")
                if sector:
                    sector_values[sector] = sector_values.get(sector, 0) + pos.get(
                        "market_value", 0
                    )
            max_sector_pct = 0.40
            for sector, val in sector_values.items():
                if val / total_value >= max_sector_pct:
                    # Block buys for signals in this sector
                    for signal in signals:
                        thesis = signal_theses.get(signal.symbol)
                        signal_sector = ""
                        if thesis and hasattr(thesis, "sector"):
                            signal_sector = thesis.sector or ""
                        if not signal_sector:
                            signal_sector = signal.metadata.get("sector", "")
                        if signal_sector == sector and signal.direction.value in (
                            "buy",
                            "add",
                        ):
                            risk_blocked.add(signal.symbol)

        logger.info(
            "InvestmentDirector | risk | %d signals risk-blocked, budget_remaining=%.1f%%",
            len(risk_blocked),
            self._belief.risk_budget.remaining_pct * 100,
        )

        # ── 5. TRADER — execution planning via DecisionPipeline ──
        raw_proposals: list[TradeProposal] = []
        for signal in signals:
            if signal.symbol in risk_blocked:
                continue

            thesis = signal_theses.get(signal.symbol)
            try:
                proposal = await self._evaluate_signal(
                    signal=signal,
                    positions=state.positions,
                    available_cash=available_cash,
                    thesis=thesis,
                    limits=limits,
                )
                if proposal:
                    raw_proposals.append(proposal)
                    logger.info(
                        "InvestmentDirector | trader | %s %s %d shares @ conf=%.2f",
                        proposal.action,
                        proposal.symbol,
                        proposal.shares,
                        proposal.confidence,
                    )
            except Exception as exc:
                logger.error(
                    "InvestmentDirector | trader | evaluation error for %s: %s",
                    signal.symbol,
                    exc,
                    exc_info=True,
                )

        # ── 5.5 RISK AGENT — independent per-decision veto & position adjustment ──
        if self._risk_agent and raw_proposals:
            buy_proposals = [p for p in raw_proposals if p.action in ("buy", "add")]
            if buy_proposals:
                try:
                    from src.agent_loop.multi_agent_pm import PMDecision

                    pm_decisions = [
                        PMDecision(
                            action=p.action,
                            symbol=p.symbol,
                            shares=p.shares,
                            entry_price=p.metadata.get("entry_price", 0)
                            if hasattr(p, "metadata") and isinstance(p.metadata, dict)
                            else 0,
                            stop_loss=p.stop_loss if hasattr(p, "stop_loss") else 0,
                            target_price=p.target_price
                            if hasattr(p, "target_price")
                            else 0,
                            confidence=p.confidence,
                            reasoning=p.debate_summary or "",
                        )
                        for p in buy_proposals
                    ]

                    portfolio_text = "\n".join(
                        f"  {pos.get('symbol', '?')} {pos.get('name', '')} "
                        f"{pos.get('shares', 0)}股 成本{pos.get('cost_price', 0):.2f}"
                        for pos in state.positions
                    )

                    verdicts = await self._risk_agent.review(
                        decisions=pm_decisions,
                        portfolio_summary=portfolio_text,
                        available_cash=available_cash,
                        daily_pnl_pct=getattr(state, "daily_pnl_pct", 0.0),
                        weekly_pnl_pct=getattr(state, "weekly_pnl_pct", 0.0),
                    )
                    verdict_map = {v.symbol: v for v in verdicts}

                    vetoed = []
                    for proposal in raw_proposals:
                        verdict = verdict_map.get(proposal.symbol)
                        if not verdict:
                            continue
                        if not verdict.approved:
                            vetoed.append(proposal.symbol)
                            logger.info(
                                "InvestmentDirector | risk_agent | VETOED %s: %s",
                                proposal.symbol,
                                verdict.veto_reason,
                            )
                        elif (
                            verdict.adjusted_shares is not None
                            and verdict.adjusted_shares > 0
                        ):
                            old = proposal.shares
                            proposal.shares = verdict.adjusted_shares
                            logger.info(
                                "InvestmentDirector | risk_agent | %s shares %d→%d",
                                proposal.symbol,
                                old,
                                proposal.shares,
                            )

                    raw_proposals = [p for p in raw_proposals if p.symbol not in vetoed]
                    logger.info(
                        "InvestmentDirector | risk_agent | %d reviewed, %d vetoed",
                        len(pm_decisions),
                        len(vetoed),
                    )
                except Exception as exc:
                    logger.error(
                        "InvestmentDirector | risk_agent | review failed: %s",
                        exc,
                        exc_info=True,
                    )

        # ── 6. REVIEWER — mandatory debate for buys ──
        for proposal in raw_proposals:
            if proposal.action in ("buy", "add"):
                # Buy proposals already went through debate in DecisionPipeline.
                # If debate_summary is empty, it means debate was skipped
                # (should not happen for buys, but verify).
                if not proposal.debate_summary:
                    logger.warning(
                        "InvestmentDirector | reviewer | BUY for %s has no debate — "
                        "rejecting (debate is mandatory for buys)",
                        proposal.symbol,
                    )
                    continue
                logger.info(
                    "InvestmentDirector | reviewer | %s buy passed debate "
                    "(bull=%.2f bear=%.2f)",
                    proposal.symbol,
                    proposal.bull_score,
                    proposal.bear_score,
                )
            else:
                logger.info(
                    "InvestmentDirector | reviewer | %s %s — debate optional, passed",
                    proposal.symbol,
                    proposal.action,
                )
            proposals.append(proposal)

        # ── 7. MESSENGER — record and push proposals ──
        for proposal in proposals:
            self._record_proposal(proposal)
            self._push_notification("trade_signal", proposal.to_dict())
            logger.info(
                "InvestmentDirector | messenger | pushed %s signal for %s",
                proposal.action,
                proposal.symbol,
            )

        duration = time.monotonic() - start
        logger.info(
            "InvestmentDirector | cycle complete | %.1fs | %d signals → %d proposals",
            duration,
            len(signals),
            len(proposals),
        )

        return proposals

    # ------------------------------------------------------------------
    # Market view & daily brief
    # ------------------------------------------------------------------

    def get_market_view(self) -> dict[str, Any]:
        """Return current market view — regime, sentiment, theses, utilization.

        Aggregates from belief state and available services into a snapshot
        suitable for API responses and decision context.
        """
        view: dict[str, Any] = {
            "regime": self._belief.regime.hmm_state,
            "regime_probability": self._belief.regime.hmm_probability,
            "sentiment_phase": self._belief.regime.sentiment_phase,
            "sentiment_phase_cn": self._belief.regime.sentiment_phase_cn,
            "reflexivity_state": self._belief.regime.reflexivity_state,
            "risk_budget_remaining": self._belief.risk_budget.remaining_pct,
            "risk_halted": self._belief.risk_budget.is_halted,
            "cash_target_pct": self._belief.cash_strategy.target_cash_pct,
            "active_theses_count": 0,
            "weakening_theses_count": 0,
            "portfolio_utilization": 0.0,
            "position_count": 0,
        }

        # Active theses count
        if self._thesis_tracker:
            try:
                active = self._thesis_tracker.get_active_theses()
                view["active_theses_count"] = len(active)
                view["weakening_theses_count"] = sum(
                    1 for t in active if t.status == "weakening"
                )
            except Exception as exc:
                logger.warning(
                    "InvestmentDirector | get_market_view | thesis count failed: %s",
                    exc,
                )
        elif self._thesis_store:
            try:
                theses = self._thesis_store.get_active()
                view["active_theses_count"] = len(theses)
            except Exception as exc:
                logger.debug("Thesis store query failed: %s", exc)

        # Portfolio utilization
        positions = self._get_positions()
        available_cash = self._get_available_cash()
        total_value = available_cash + sum(p.get("market_value", 0) for p in positions)
        equity_value = sum(p.get("market_value", 0) for p in positions)

        view["position_count"] = len(positions)
        if total_value > 0:
            view["portfolio_utilization"] = round(equity_value / total_value, 4)

        # Position limits from current phase
        limits = self._belief.get_position_limits()
        view["buys_allowed"] = limits.get("buys_allowed", True)
        view["max_position_pct"] = limits.get("max_position_pct", 0.20)
        view["max_equity_pct"] = limits.get("max_equity_pct", 0.50)

        logger.info(
            "InvestmentDirector | market_view | regime=%s phase=%s theses=%d util=%.0f%%",
            view["regime"],
            view["sentiment_phase"],
            view["active_theses_count"],
            view["portfolio_utilization"] * 100,
        )

        return view

    def get_daily_brief(self) -> str:
        """Generate a plain-language daily summary.

        Covers: active theses, pending proposals, portfolio status,
        regime assessment. Returns structured text that can later be
        sent to LLM for formatting.
        """
        lines: list[str] = []
        now = datetime.now(_CST)
        lines.append(f"=== 每日简报 {now.strftime('%Y-%m-%d %H:%M')} ===")
        lines.append("")

        # 1. Regime assessment
        regime = self._belief.regime
        lines.append("【市场环境】")
        lines.append(
            f"  市场状态: {regime.hmm_state} (置信度 {regime.hmm_probability:.0%})"
        )
        lines.append(
            f"  情绪周期: {regime.sentiment_phase_cn} ({regime.sentiment_phase})"
        )
        lines.append(f"  反身性: {regime.reflexivity_state}")
        lines.append(
            f"  目标现金比例: {self._belief.cash_strategy.target_cash_pct:.0%}"
        )
        lines.append("")

        # 2. Portfolio status
        positions = self._get_positions()
        available_cash = self._get_available_cash()
        total_value = available_cash + sum(p.get("market_value", 0) for p in positions)
        equity_value = sum(p.get("market_value", 0) for p in positions)
        daily_pnl = sum(p.get("daily_pnl", 0) for p in positions)

        lines.append("【持仓概况】")
        lines.append(f"  持仓数量: {len(positions)}")
        lines.append(f"  总市值: ¥{total_value:,.0f}")
        lines.append(f"  持仓市值: ¥{equity_value:,.0f}")
        lines.append(f"  可用现金: ¥{available_cash:,.0f}")
        if total_value > 0:
            lines.append(f"  仓位占比: {equity_value / total_value:.0%}")
        lines.append(f"  当日盈亏: ¥{daily_pnl:,.2f}")
        lines.append("")

        # 3. Risk budget
        risk = self._belief.risk_budget
        lines.append("【风险预算】")
        lines.append(
            f"  日内风控余额: {risk.remaining_pct:.1%} / {risk.daily_limit_pct:.1%}"
        )
        lines.append(f"  连续亏损: {risk.consecutive_losses}次")
        if risk.is_halted:
            lines.append("  ⚠ 风险预算已耗尽 — 暂停买入")
        lines.append("")

        # 4. Active theses
        lines.append("【投资论点】")
        theses_found = False
        if self._thesis_tracker:
            try:
                theses = self._thesis_tracker.get_active_theses()
                if theses:
                    theses_found = True
                    for thesis in theses[:10]:
                        status_label = "活跃" if thesis.status == "active" else "减弱"
                        lines.append(
                            f"  {thesis.symbol} ({thesis.direction}): "
                            f"信心 {thesis.current_confidence:.0%} [{status_label}]"
                        )
                        if thesis.narrative:
                            lines.append(f"    -> {thesis.narrative[:80]}")
            except Exception as exc:
                logger.debug("Daily brief thesis query failed: %s", exc)
        elif self._thesis_store:
            try:
                theses = self._thesis_store.get_active()
                if theses:
                    theses_found = True
                    for thesis in theses[:10]:
                        lines.append(
                            f"  {thesis.symbol}: {thesis.direction} "
                            f"信心 {thesis.conviction:.0%}"
                        )
            except Exception:
                pass

        if not theses_found:
            lines.append("  无活跃论点")
        lines.append("")

        # 5. Daily plan summary
        plan = self._belief.daily_plan
        lines.append("【当日计划】")
        lines.append(f"  监控列表: {len(plan.watch_list)}只")
        lines.append(f"  买入候选: {len(plan.buy_candidates)}只")
        lines.append(f"  卖出计划: {len(plan.sell_plan)}只")
        if plan.notes:
            lines.append(f"  备注: {plan.notes}")
        lines.append("")

        # 6. Decision accuracy (if available)
        if self._decision_log_store:
            try:
                stats = self._decision_log_store.get_accuracy_stats(lookback_days=30)
                total = stats.get("total_decisions", 0)
                if total > 0:
                    accuracy = stats.get("direction_accuracy")
                    lines.append("【决策追踪 (30日)】")
                    lines.append(f"  总决策: {total}")
                    if accuracy is not None:
                        lines.append(f"  方向准确率: {accuracy:.0%}")
                    avg_t3 = stats.get("avg_t3_return")
                    if avg_t3 is not None:
                        lines.append(f"  平均T+3收益: {avg_t3:.2f}%")
                    lines.append("")
            except Exception:
                pass

        brief = "\n".join(lines)

        logger.info(
            "InvestmentDirector | daily_brief | generated %d lines",
            len(lines),
        )

        return brief

    # ------------------------------------------------------------------
    # Convergence helper
    # ------------------------------------------------------------------

    @staticmethod
    def _build_evidence_from_signal(
        signal: AggregatedSignal,
    ) -> list[Any]:
        """Build SignalEvidence list from an AggregatedSignal for convergence.

        Maps the signal's source domain to an IndependenceGroup so the
        ConvergenceEngine can score it properly.
        """
        try:
            from src.agent_loop.domain_adapter import (
                IndependenceGroup,
                SignalDirection as DomainDirection,
                SignalEvidence,
            )
        except ImportError:
            return []

        # Map source string to independence group
        source_to_group: dict[str, IndependenceGroup] = {
            "recommendation": IndependenceGroup.INTELLIGENCE,
            "technical": IndependenceGroup.PRICE_DERIVED,
            "rotation": IndependenceGroup.MACRO,
            "black_swan": IndependenceGroup.INTELLIGENCE,
            "thesis_invalidation": IndependenceGroup.INTELLIGENCE,
            "stop_loss": IndependenceGroup.PRICE_DERIVED,
            "daily_plan": IndependenceGroup.INTELLIGENCE,
            "capital_flow": IndependenceGroup.CAPITAL_FLOW,
            "microstructure": IndependenceGroup.MICROSTRUCTURE,
            "market_structure": IndependenceGroup.MARKET_STRUCTURE,
        }

        # Map signal direction
        dir_map: dict[str, DomainDirection] = {
            "buy": DomainDirection.BUY,
            "sell": DomainDirection.SELL,
            "hold": DomainDirection.HOLD,
            "add": DomainDirection.BUY,
            "reduce": DomainDirection.SELL,
        }

        group = source_to_group.get(signal.source, IndependenceGroup.PRICE_DERIVED)
        direction = dir_map.get(signal.direction.value, DomainDirection.HOLD)

        evidence = [
            SignalEvidence(
                domain=signal.source,
                signal_type=f"{signal.source}/{signal.reason[:30]}",
                symbol=signal.symbol,
                direction=direction,
                confidence=signal.confidence,
                independence_group=group,
            )
        ]

        return evidence

    # ------------------------------------------------------------------
    # Research team — causal chain intelligence from knowledge graph
    # ------------------------------------------------------------------

    async def _run_research_team(
        self,
        belief_state: SharedBeliefState | None = None,
    ) -> list[dict[str, Any]]:
        """Run research team: process recent events into causal chains.

        Queries the knowledge graph for active (non-expired) events,
        constructs causal impact chains via CausalChainConstructor,
        and returns serialized chain briefs for downstream consumption.

        Called during pre_market_brief() (SENTINEL team phase) to ensure
        overnight events are processed into tradeable intelligence.

        Args:
            belief_state: Optional belief state override (defaults to self._belief).

        Returns:
            List of causal chain dicts (from CausalChain.to_dict()).
        """
        if not self._knowledge_graph:
            return []

        # Lazy-init chain constructor from DI if not provided
        constructor = self._chain_constructor
        if constructor is None:
            try:
                from src.intelligence.causal_chain import CausalChainConstructor

                constructor = CausalChainConstructor()
            except Exception as exc:
                logger.warning(
                    "InvestmentDirector | research | CausalChainConstructor init failed: %s",
                    exc,
                )
                return []

        # Get active events from knowledge graph (valid_until not yet passed)
        try:
            active_events = self._knowledge_graph.get_active_events()
        except Exception as exc:
            logger.warning(
                "InvestmentDirector | research | failed to query active events: %s",
                exc,
            )
            return []

        if not active_events:
            logger.info(
                "InvestmentDirector | research | no active events in knowledge graph"
            )
            return []

        briefs: list[dict[str, Any]] = []
        for event_node in active_events:
            # Build event dict compatible with CausalChainConstructor
            event_dict = {
                "event_id": event_node.get("event_id", ""),
                "title": event_node.get("title", ""),
                "description": event_node.get("title", ""),
                "confidence": event_node.get("severity", 0.6),
                "event_type": event_node.get("event_type", ""),
            }

            try:
                chain = await constructor.construct_chain_async(event_dict)
            except Exception as exc:
                logger.debug(
                    "InvestmentDirector | research | chain construction failed for %s: %s",
                    event_dict.get("event_id", "?"),
                    exc,
                )
                continue

            if chain and (chain.all_stocks or chain.all_sectors):
                briefs.append(chain.to_dict())

        bs = belief_state or self._belief
        if briefs:
            # Record research findings as key events in today's daily plan
            event_summaries = [b.get("event_description", "")[:60] for b in briefs[:5]]
            bs.daily_plan.key_events.extend(event_summaries)

        logger.info(
            "InvestmentDirector | research | processed %d active events → %d causal chains",
            len(active_events),
            len(briefs),
        )
        return briefs

    # ------------------------------------------------------------------
    # 08:00 — Pre-market brief
    # ------------------------------------------------------------------

    async def pre_market_brief(self) -> dict[str, Any]:
        """Morning preparation: overnight data, thesis review, daily plan.

        1. Reset daily counters
        2. Gather overnight market data (global indices, futures)
        3. Update regime from overnight signals
        4. Check expiring theses
        5. Check T+1 outcomes for yesterday's entries
        6. Build daily_plan: watch_list + buy_candidates + sell_plan
        7. Push morning brief to MessageStore + Discord
        """
        start = time.monotonic()
        logger.info("=== Pre-market brief START ===")

        # Reset daily state
        self._belief.reset_daily()

        briefing: dict[str, Any] = {
            "date": datetime.now(_CST).strftime("%Y-%m-%d"),
            "global_summary": "",
            "regime": {},
            "thesis_status": [],
            "daily_plan": {},
            "overnight_outcomes": [],
        }

        # 1. Global market overnight changes
        global_snapshot = None
        if self._global_market:
            try:
                global_snapshot = self._global_market.get_cached_snapshot()
                if global_snapshot:
                    indices = global_snapshot.get("indices", [])
                    parts = []
                    for idx in indices[:6]:
                        name = idx.get("name", "")
                        change = idx.get("change_pct", 0)
                        parts.append(f"{name} {change:+.2f}%")
                    briefing["global_summary"] = (
                        " | ".join(parts) if parts else "暂无数据"
                    )
            except Exception as exc:
                logger.warning("Failed to fetch global markets: %s", exc)
                briefing["global_summary"] = "数据获取失败"

        # 2. Update regime state
        if self._regime:
            try:
                daily_returns = self._fetch_market_daily_returns()
                result = self._regime.detect(daily_returns)
                if hasattr(result, "current_regime"):
                    cr = result.current_regime
                    self._belief.update_regime(
                        hmm_state=cr.regime_label or "unknown",
                        hmm_probability=cr.percentile,
                        sentiment_phase=getattr(cr, "sentiment_phase", "unknown"),
                        sentiment_phase_cn=getattr(cr, "sentiment_phase_cn", "未知"),
                        reflexivity_state=getattr(cr, "reflexivity", "unknown"),
                    )
                elif isinstance(result, dict):
                    self._belief.update_regime(
                        hmm_state=result.get("regime", "unknown"),
                        hmm_probability=result.get("probability", 0.5),
                        sentiment_phase=result.get("sentiment_phase", "unknown"),
                        sentiment_phase_cn=result.get("sentiment_phase_cn", "未知"),
                        reflexivity_state=result.get("reflexivity", "unknown"),
                    )
                briefing["regime"] = self._belief.regime.__dict__.copy()
            except Exception as exc:
                logger.warning("Regime detection failed: %s", exc)

        # Update cash strategy based on new regime
        self._belief.update_cash_strategy()

        # 2b. Research team — process overnight events into causal chains
        research_briefs = await self._run_research_team(self._belief)
        if research_briefs:
            briefing["research_briefs"] = research_briefs
            logger.info(
                "Pre-market: %d causal chains from research team",
                len(research_briefs),
            )

        # 3. Thesis review — check expiring and decay
        watch_list: list[str] = []
        buy_candidates: list[dict[str, Any]] = []
        sell_plan: list[dict[str, Any]] = []

        if self._thesis_store:
            try:
                theses = self._thesis_store.get_active()
                for thesis in theses:
                    thesis_info = {
                        "symbol": thesis.symbol,
                        "name": thesis.name,
                        "direction": thesis.direction,
                        "conviction": thesis.conviction,
                    }
                    briefing["thesis_status"].append(thesis_info)
                    watch_list.append(thesis.symbol)

                    # Bullish theses with high conviction -> buy candidates
                    if thesis.direction == "bullish" and thesis.conviction >= 0.6:
                        buy_candidates.append(
                            {
                                "symbol": thesis.symbol,
                                "name": thesis.name,
                                "thesis_id": thesis.id,
                                "conviction": thesis.conviction,
                            }
                        )

                # Decay stale theses
                decayed = self._thesis_store.decay_stale()
                if decayed:
                    logger.info("Pre-market: decayed %d stale theses", decayed)
            except Exception as exc:
                logger.warning("Thesis review failed: %s", exc)

        # 4. Check positions for sell candidates
        positions = self._get_positions()
        for pos in positions:
            symbol = pos.get("symbol", "")
            if symbol not in watch_list:
                watch_list.append(symbol)

            # Flag positions with approaching stop-loss
            pnl_pct = pos.get("pnl_pct", 0)
            if pnl_pct < -0.02:
                sell_plan.append(
                    {
                        "symbol": symbol,
                        "name": pos.get("name", ""),
                        "reason": f"亏损{pnl_pct:.1%}，接近止损线",
                        "urgency": "monitor",
                    }
                )

        # 5. Check overnight outcomes (T+1 for yesterday's entries)
        if self._decision_log_store:
            try:
                pending = self._decision_log_store.get_pending_outcomes(lookback_days=1)
                if isinstance(pending, list):
                    for outcome in pending[:5]:
                        briefing["overnight_outcomes"].append(outcome)
            except Exception as exc:
                logger.debug("Overnight outcome check failed: %s", exc)

        # 6. Build daily plan
        # Include key events from research team causal chains
        key_events: list[str] = []
        for brief in research_briefs:
            desc = brief.get("event_description", "")
            if desc:
                key_events.append(desc[:80])

        plan = DailyPlan(
            date=datetime.now().strftime("%Y-%m-%d"),
            watch_list=watch_list[:20],
            buy_candidates=buy_candidates,
            sell_plan=sell_plan,
            key_events=key_events[:10],
            notes=f"regime={self._belief.regime.hmm_state}, "
            f"phase={self._belief.regime.sentiment_phase}",
        )
        self._belief.set_daily_plan(plan)
        briefing["daily_plan"] = {
            "watch_list": plan.watch_list,
            "buy_candidates": len(plan.buy_candidates),
            "sell_plan": len(plan.sell_plan),
        }

        # 7. Push briefing
        self._push_notification("morning_briefing", briefing)

        duration = time.monotonic() - start
        logger.info(
            "=== Pre-market brief END (%.1fs) — %d watch, %d buy candidates, %d sell ===",
            duration,
            len(watch_list),
            len(buy_candidates),
            len(sell_plan),
        )

        return briefing

    # ------------------------------------------------------------------
    # 09:15 — Call auction monitor
    # ------------------------------------------------------------------

    async def call_auction_monitor(
        self, symbols: list[str] | None = None
    ) -> dict[str, Any]:
        """Analyze call auction data for watch_list symbols.

        Confirm or reject buy candidates based on auction signals:
        - High auction volume = strong opening interest
        - Auction price vs previous close = gap direction
        - Match ratio = institutional participation
        """
        logger.info("=== Call auction monitor START ===")

        target_symbols = symbols or self._belief.daily_plan.watch_list
        if not target_symbols:
            logger.info("No symbols to monitor in call auction")
            return {"confirmed": [], "rejected": []}

        confirmed: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []

        if self._call_auction:
            try:
                for symbol in target_symbols[:10]:
                    auction_data = self._call_auction.get_auction_data(symbol)
                    if not auction_data:
                        continue

                    # Simple scoring: volume ratio + gap direction
                    vol_ratio = auction_data.get("volume_ratio", 1.0)
                    gap_pct = auction_data.get("gap_pct", 0.0)
                    score = vol_ratio * 0.5 + (1.0 if gap_pct > 0 else 0.3) * 0.5

                    entry = {
                        "symbol": symbol,
                        "auction_volume_ratio": vol_ratio,
                        "gap_pct": gap_pct,
                        "score": score,
                    }

                    if score >= 0.6:
                        confirmed.append(entry)
                    else:
                        rejected.append(entry)
            except Exception as exc:
                logger.warning("Call auction analysis failed: %s", exc)
        else:
            # Without auction provider, pass through existing candidates
            for candidate in self._belief.daily_plan.buy_candidates:
                confirmed.append(
                    {
                        "symbol": candidate["symbol"],
                        "auction_volume_ratio": None,
                        "gap_pct": None,
                        "score": candidate.get("conviction", 0.5),
                    }
                )

        # Update daily plan with confirmed candidates
        if confirmed:
            self._belief.daily_plan.buy_candidates = [
                c
                for c in self._belief.daily_plan.buy_candidates
                if c["symbol"] in {e["symbol"] for e in confirmed}
            ]

        result = {"confirmed": confirmed, "rejected": rejected}

        if confirmed:
            self._push_notification(
                "auction_update",
                {
                    "confirmed_count": len(confirmed),
                    "symbols": [c["symbol"] for c in confirmed],
                },
            )

        logger.info(
            "=== Call auction END — %d confirmed, %d rejected ===",
            len(confirmed),
            len(rejected),
        )
        return result

    # ------------------------------------------------------------------
    # 09:30 — Morning session
    # ------------------------------------------------------------------

    async def morning_session(self) -> dict[str, Any]:
        """Early session regime check after market opens.

        Verify pre-market expectations against actual opening behavior:
        - Did the gap match expectations?
        - Is volume confirming the thesis?
        - Any immediate regime shift?
        """
        logger.info("=== Morning session check START ===")

        result: dict[str, Any] = {
            "regime_confirmed": True,
            "alerts": [],
        }

        # Re-check regime with live data
        if self._regime:
            try:
                daily_returns = self._fetch_market_daily_returns()
                live_regime = self._regime.detect(daily_returns)
                # Extract regime label from RegimeReport or dict
                if hasattr(live_regime, "current_regime"):
                    live_phase = live_regime.current_regime.regime_label or "unknown"
                elif isinstance(live_regime, dict):
                    live_phase = live_regime.get("sentiment_phase", "unknown")
                else:
                    live_phase = "unknown"

                pre_phase = self._belief.regime.sentiment_phase
                if live_phase != pre_phase and live_phase != "unknown":
                    self._belief.update_regime(
                        sentiment_phase=live_phase,
                        sentiment_phase_cn=getattr(live_regime, "summary", "未知")
                        if hasattr(live_regime, "summary")
                        else (
                            live_regime.get("sentiment_phase_cn", "未知")
                            if isinstance(live_regime, dict)
                            else "未知"
                        ),
                    )
                    self._belief.update_cash_strategy()
                    result["regime_confirmed"] = False
                    result["alerts"].append(
                        f"情绪周期变化: {pre_phase} -> {live_phase}"
                    )
                    logger.warning(
                        "Morning: regime shift detected %s -> %s",
                        pre_phase,
                        live_phase,
                    )
            except Exception as exc:
                logger.warning("Morning regime check failed: %s", exc)

        # Check risk budget status
        if self._belief.risk_budget.is_halted:
            result["alerts"].append("风险预算耗尽 — 暂停买入")

        if result["alerts"]:
            self._push_notification("morning_alert", result)

        logger.info("=== Morning session check END ===")
        return result

    # ------------------------------------------------------------------
    # 14:30 — Late session (primary decision window)
    # ------------------------------------------------------------------

    async def late_session(
        self,
        portfolio: list[dict[str, Any]] | None = None,
        signals: list[AggregatedSignal] | None = None,
    ) -> dict[str, Any]:
        """Late session decision window — the primary buy timing.

        1. Run signal aggregation with portfolio context
        2. For each buy candidate: run mandatory debate
        3. Apply Bayesian posterior + Kelly sizing
        4. Generate execution plans with timing (14:30-14:50)
        5. Push to action queue + MessageStore + Discord
        """
        start = time.monotonic()
        logger.info("=== Late session START ===")

        positions = portfolio or self._get_positions()
        available_cash = self._get_available_cash()
        limits = self._belief.get_position_limits()

        result: dict[str, Any] = {
            "proposals": [],
            "blocked": [],
            "risk_halted": self._belief.risk_budget.is_halted,
        }

        # Check if trading is halted
        if self._belief.risk_budget.is_halted:
            logger.warning("Late session: risk budget halted — no buys")
            self._push_notification(
                "risk_halt",
                {
                    "reason": "日内风险预算已耗尽",
                    "remaining_pct": self._belief.risk_budget.remaining_pct,
                },
            )
            return result

        # Check if buys are allowed in current phase
        if not limits.get("buys_allowed", True):
            logger.info(
                "Late session: buys not allowed in %s phase",
                self._belief.regime.sentiment_phase,
            )
            result["blocked"].append(
                {
                    "reason": f"{self._belief.regime.sentiment_phase}阶段不建议买入",
                }
            )
            return result

        # Gather signals
        if signals:
            pending_signals = signals
        elif self._signal_agg:
            self._signal_agg.clear()
            await self._collect_buy_signals(positions)
            pending_signals = self._signal_agg.rank_and_deduplicate()
        else:
            pending_signals = []

        # Process each signal through decision pipeline
        proposals: list[TradeProposal] = []
        for signal in pending_signals:
            try:
                thesis = self._get_thesis(signal.symbol)
                proposal = await self._evaluate_signal(
                    signal=signal,
                    positions=positions,
                    available_cash=available_cash,
                    thesis=thesis,
                    limits=limits,
                )
                if proposal:
                    proposals.append(proposal)
                    result["proposals"].append(proposal.to_dict())
            except Exception as exc:
                logger.error(
                    "Late session: evaluation error for %s: %s",
                    signal.symbol,
                    exc,
                    exc_info=True,
                )

        # Push proposals
        for proposal in proposals:
            self._record_proposal(proposal)
            self._push_notification("trade_signal", proposal.to_dict())

        duration = time.monotonic() - start
        logger.info(
            "=== Late session END (%.1fs) — %d signals, %d proposals ===",
            duration,
            len(pending_signals),
            len(proposals),
        )

        return result

    # ------------------------------------------------------------------
    # 15:05 — Close briefing
    # ------------------------------------------------------------------

    async def close_briefing(self) -> dict[str, Any]:
        """Quick summary at market close.

        Snapshot current positions, daily P&L, any pending actions.
        """
        logger.info("=== Close briefing START ===")

        positions = self._get_positions()
        daily_pnl = sum(p.get("daily_pnl", 0) for p in positions)
        total_value = sum(p.get("market_value", 0) for p in positions)

        briefing = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "position_count": len(positions),
            "total_value": total_value,
            "daily_pnl": daily_pnl,
            "daily_pnl_pct": daily_pnl / total_value if total_value > 0 else 0,
            "regime": self._belief.regime.sentiment_phase,
            "risk_budget_remaining": self._belief.risk_budget.remaining_pct,
        }

        self._push_notification("close_briefing", briefing)
        logger.info("=== Close briefing END ===")
        return briefing

    # ------------------------------------------------------------------
    # 15:30 — Post-market review
    # ------------------------------------------------------------------

    async def post_market_review(
        self, portfolio: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """End-of-day review and learning.

        1. Run OutcomeTracker for T+1/T+3/T+5
        2. Update Bayesian tables from outcomes
        3. Apply thesis decay for all active theses
        4. Check thesis invalidations
        5. Detect missed opportunities
        6. Generate review report -> MessageStore + Discord
        """
        start = time.monotonic()
        logger.info("=== Post-market review START ===")

        positions = portfolio or self._get_positions()
        review: dict[str, Any] = {
            "date": datetime.now(_CST).strftime("%Y-%m-%d"),
            "daily_pnl": "",
            "outcomes": [],
            "thesis_updates": [],
            "calibration": {},
            "missed_opportunities": [],
        }

        # 1. Portfolio P&L
        total_pnl = sum(p.get("daily_pnl", 0) for p in positions)
        total_value = sum(p.get("market_value", 0) for p in positions)
        review["daily_pnl"] = f"¥{total_pnl:,.2f}"
        review["daily_pnl_pct"] = total_pnl / total_value if total_value > 0 else 0

        # Track loss for risk budget
        if total_value > 0 and total_pnl < 0:
            loss_pct = abs(total_pnl) / total_value
            self._belief.update_risk_budget(realized_loss=loss_pct)

        # 2. Check decision outcomes
        if self._decision_log_store:
            try:
                stats = self._decision_log_store.get_accuracy_stats(lookback_days=30)
                review["outcomes"] = stats
                if stats.get("total_decisions", 0) > 0:
                    accuracy = stats.get("direction_accuracy")
                    if accuracy is not None:
                        review["calibration"]["direction_accuracy"] = accuracy
                        # Update signal accuracy in belief state
                        self._belief.update_signal_accuracy("overall", accuracy)
            except Exception as exc:
                logger.warning("Outcome tracking failed: %s", exc)

        # 3. Calibration report
        if self._calibrator:
            try:
                cal_report = self._calibrator.get_calibration_report()
                review["calibration"]["report"] = cal_report
            except Exception as exc:
                logger.debug("Calibration report failed: %s", exc)

        # 4. Thesis decay and invalidation check
        if self._thesis_store:
            try:
                decayed = self._thesis_store.decay_stale()
                if decayed:
                    review["thesis_updates"].append(f"衰减{decayed}个过期论点")

                # Check for invalidations
                active_theses = self._thesis_store.get_active()
                for thesis in active_theses:
                    # Check if any position contradicts thesis
                    held = next(
                        (p for p in positions if p.get("symbol") == thesis.symbol),
                        None,
                    )
                    if held:
                        pnl_pct = held.get("pnl_pct", 0)
                        if thesis.direction == "bullish" and pnl_pct < -0.05:
                            review["thesis_updates"].append(
                                f"{thesis.symbol}: 看多论点与实际亏损{pnl_pct:.1%}矛盾"
                            )
            except Exception as exc:
                logger.warning("Thesis review failed: %s", exc)

        # 5. Push review
        self._push_notification("evening_review", review)

        duration = time.monotonic() - start
        logger.info(
            "=== Post-market review END (%.1fs) — pnl=¥%.0f ===",
            duration,
            total_pnl,
        )

        return review

    # ------------------------------------------------------------------
    # Event handler (intraday, event-driven)
    # ------------------------------------------------------------------

    async def handle_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Handle a significant intraday event.

        Triggered by event bus for events like:
        - Price limit approach
        - Sudden volume spike
        - Sector rotation signal
        - Black swan indicator

        Assess impact on portfolio and watch_list. If severity exceeds
        threshold, run a micro-OODA cycle.
        """
        event_type = event.get("type", "unknown")
        severity = event.get("severity", 0.0)
        symbol = event.get("symbol", "")

        logger.info(
            "Event received: type=%s symbol=%s severity=%.2f",
            event_type,
            symbol,
            severity,
        )

        # Below threshold — log and skip
        if severity < self._event_severity_threshold:
            return None

        # Check if event affects portfolio or watch_list
        positions = self._get_positions()
        held_symbols = {p.get("symbol") for p in positions}
        watch_symbols = set(self._belief.daily_plan.watch_list)

        is_relevant = symbol in held_symbols or symbol in watch_symbols

        if not is_relevant and symbol:
            logger.debug("Event for %s not relevant to portfolio/watchlist", symbol)
            return None

        result: dict[str, Any] = {
            "event_type": event_type,
            "symbol": symbol,
            "action": "none",
        }

        # Determine response based on event type
        if event_type in ("black_swan", "circuit_breaker"):
            # Critical risk event — push immediate alert
            result["action"] = "risk_alert"
            self._push_notification(
                "risk_alert",
                {
                    "symbol": symbol,
                    "event_type": event_type,
                    "severity": severity,
                    "message": event.get("message", "紧急风险事件"),
                },
            )

            # If we hold the position, flag for sell
            if symbol in held_symbols and self._signal_agg:
                self._signal_agg.add_signal(
                    AggregatedSignal(
                        symbol=symbol,
                        name=event.get("name", ""),
                        direction=SignalDirection.SELL,
                        source=f"event:{event_type}",
                        confidence=0.95,
                        urgency=UrgencyTier.CRITICAL,
                        reason=event.get("message", "紧急风险事件"),
                    )
                )
                result["action"] = "critical_sell"

        elif event_type == "thesis_invalidation":
            result["action"] = "thesis_review"
            # Thesis invalidated — notify
            self._push_notification(
                "thesis_invalidation",
                {
                    "symbol": symbol,
                    "reason": event.get("reason", "论点失效"),
                },
            )

        elif event_type in ("volume_spike", "limit_approach"):
            # Informational for held positions, potential signal for watch_list
            if symbol in held_symbols:
                result["action"] = "monitor"
                self._push_notification(
                    "intraday_alert",
                    {
                        "symbol": symbol,
                        "alert_type": event_type,
                        "message": event.get("message", ""),
                    },
                )
            elif symbol in watch_symbols:
                result["action"] = "signal_candidate"

        # ── Convergence enhancement via SignalCollectorFactory ──
        # If a signal collector and convergence engine are both available,
        # gather multi-domain evidence and check for convergence.
        if self._signal_collector and self._convergence and symbol:
            try:
                evidence = self._signal_collector.collect_all(
                    symbols=[symbol],
                    portfolio_context={
                        "held_symbols": list(held_symbols),
                        "watch_symbols": list(watch_symbols),
                    },
                )
                if evidence:
                    conv_results = self._convergence.analyze(evidence)
                    actionable = [
                        r for r in conv_results if getattr(r, "converged", False)
                    ]
                    if actionable:
                        result["convergence"] = {
                            "converged": True,
                            "count": len(actionable),
                            "score": actionable[0].convergence_score,
                        }
                        logger.info(
                            "Event convergence: %s has %d converged result(s), "
                            "score=%.3f",
                            symbol,
                            len(actionable),
                            actionable[0].convergence_score,
                        )
            except Exception as exc:
                logger.debug("Event convergence check failed for %s: %s", symbol, exc)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_positions(self) -> list[dict[str, Any]]:
        """Fetch current portfolio positions."""
        if not self._portfolio:
            return []
        try:
            return self._portfolio.list_positions()
        except Exception as exc:
            logger.warning("Failed to fetch positions: %s", exc)
            return []

    def _get_available_cash(self) -> float:
        """Fetch available cash."""
        if not self._capital:
            return 0.0
        try:
            bal = self._capital.get_balance()
            return bal.available if hasattr(bal, "available") else 0.0
        except Exception as exc:
            logger.warning("Failed to fetch capital: %s", exc)
            return 0.0

    def _get_thesis(self, symbol: str) -> Any:
        """Get active thesis for symbol."""
        if not self._thesis_store:
            return None
        try:
            return self._thesis_store.get(symbol)
        except Exception:
            return None

    async def _collect_buy_signals(self, positions: list[dict[str, Any]]) -> None:
        """Collect buy signals from daily plan candidates."""
        if not self._signal_agg:
            return

        for candidate in self._belief.daily_plan.buy_candidates:
            symbol = candidate.get("symbol", "")
            if not symbol:
                continue

            # Check if already held
            held = next((p for p in positions if p.get("symbol") == symbol), None)

            self._signal_agg.add_signal(
                AggregatedSignal(
                    symbol=symbol,
                    name=candidate.get("name", ""),
                    direction=SignalDirection.BUY if not held else SignalDirection.ADD,
                    source="daily_plan",
                    confidence=candidate.get("conviction", 0.5),
                    urgency=UrgencyTier.NORMAL,
                    reason=f"晨间计划买入候选 (信心{candidate.get('conviction', 0):.0%})",
                )
            )

    async def _evaluate_signal(
        self,
        signal: AggregatedSignal,
        positions: list[dict[str, Any]],
        available_cash: float,
        thesis: Any = None,
        limits: dict[str, Any] | None = None,
    ) -> TradeProposal | None:
        """Evaluate a single signal through the decision pipeline."""
        if not self._pipeline:
            return None

        limits = limits or self._belief.get_position_limits()

        # Build market_data context with belief state + live data for debate
        market_data = dict(signal.metadata)
        market_data["regime"] = self._belief.regime.hmm_state
        market_data["sentiment_phase"] = self._belief.regime.sentiment_phase
        market_data["max_position_pct"] = limits.get("max_position_pct", 0.20)
        market_data["risk_budget_remaining"] = self._belief.risk_budget.remaining_pct

        # Enrich with live technical + fund flow data for debate engine.
        # Without this, debate returns bull=0/bear=0 and every signal→hold.
        await self._enrich_market_data(signal.symbol, market_data)

        daily_pnl_pct = self._estimate_daily_pnl(positions)

        return await self._pipeline.evaluate(
            signal=signal,
            portfolio=positions,
            available_cash=available_cash,
            daily_pnl_pct=daily_pnl_pct,
            consecutive_losses=self._belief.risk_budget.consecutive_losses,
            thesis=thesis,
            market_data=market_data,
        )

    async def _enrich_market_data(
        self, symbol: str, market_data: dict[str, Any]
    ) -> None:
        """Inject live data into market_data for debate engine arguments.

        The debate engine checks these specific keys:
          Bull: rsi(<30), macd_golden_cross, volume_ratio(>1.5),
                capital_net_inflow(>0), macro_score(>0.2),
                sentiment_score(>0.3), northbound_inflow(>0),
                sentiment_phase(ignition/acceleration)
          Bear: rsi(>70), volume_ratio(>2 declining), capital_net_inflow(<0),
                macro_score(<-0.2)

        Without enrichment: bull=0, bear=0 → hold. Every. Single. Cycle.
        """
        import asyncio

        # 1. Realtime quote + compute volume_ratio from OHLCV
        try:
            from src.data.realtime import RealtimeQuoteManager

            mgr = RealtimeQuoteManager()
            df = await asyncio.to_thread(mgr.get_quotes, [symbol])
            if not df.empty:
                row = df.iloc[0]
                market_data["current_price"] = float(row.get("price", 0))
                pct = row.get("pct_change")
                if pct is not None:
                    market_data["price_change_pct"] = float(pct)
                # Compute volume_ratio from today's volume vs recent average
                vol = row.get("volume", 0) or row.get("amount", 0)
                if vol and float(vol) > 0:
                    # Fetch recent daily OHLCV for average volume
                    try:
                        from src.data.fetcher import StockDataFetcher

                        fetcher = StockDataFetcher()
                        ohlcv = await asyncio.to_thread(
                            fetcher.fetch_daily_ohlcv, symbol
                        )
                        if ohlcv is not None and len(ohlcv) >= 5:
                            avg_vol = ohlcv["volume"].tail(20).mean()
                            if avg_vol > 0:
                                market_data["volume_ratio"] = float(vol) / avg_vol
                    except Exception:
                        pass
        except Exception as exc:
            logger.debug("Enrich: quote failed for %s: %s", symbol, exc)

        # 2. Technical indicators from OHLCV (compute directly)
        try:
            from src.data.fetcher import StockDataFetcher

            fetcher = StockDataFetcher()
            df_ohlcv = await asyncio.to_thread(fetcher.fetch_daily_ohlcv, symbol)
            if df_ohlcv is not None and len(df_ohlcv) >= 14:
                close = df_ohlcv["close"]
                # RSI (14-period)
                delta = close.diff()
                gain = delta.clip(lower=0).rolling(14).mean()
                loss = (-delta.clip(upper=0)).rolling(14).mean()
                rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] > 0 else 100
                rsi = 100 - (100 / (1 + rs))
                market_data["rsi"] = round(rsi, 1)

                # MACD golden cross (simple check)
                ema12 = close.ewm(span=12).mean()
                ema26 = close.ewm(span=26).mean()
                macd_line = ema12 - ema26
                signal_line = macd_line.ewm(span=9).mean()
                # Golden cross: MACD crosses above signal
                if len(macd_line) >= 2:
                    prev_diff = macd_line.iloc[-2] - signal_line.iloc[-2]
                    curr_diff = macd_line.iloc[-1] - signal_line.iloc[-1]
                    market_data["macd_golden_cross"] = prev_diff < 0 and curr_diff > 0
                    market_data["macd_death_cross"] = prev_diff > 0 and curr_diff < 0
        except Exception as exc:
            logger.debug("Enrich: technicals failed for %s: %s", symbol, exc)

        # 3. Fund flow (individual stock)
        try:
            from src.data.eastmoney_client import EastMoneyClient

            client = EastMoneyClient()
            flow = await asyncio.to_thread(client.fetch_stock_fund_flow, symbol)
            if flow and isinstance(flow, dict):
                net = flow.get("main_net_inflow", flow.get("net_inflow", 0))
                if net is not None:
                    market_data["capital_net_inflow"] = float(net)
        except Exception as exc:
            logger.debug("Enrich: stock fund flow failed for %s: %s", symbol, exc)

        # 4. Global market macro score
        if self._global_market:
            try:
                snapshot = self._global_market.get_cached_snapshot()
                if not snapshot:
                    snapshot = await asyncio.to_thread(
                        self._global_market.fetch_global_snapshot
                    )
                if snapshot:
                    scores = []
                    for idx_name in ("上证指数", "深证成指", "创业板指"):
                        idx_data = snapshot.get(idx_name, {})
                        pct = idx_data.get("pct_change", 0)
                        if pct:
                            scores.append(float(pct) / 5)  # -1..1 range
                    if scores:
                        market_data["macro_score"] = sum(scores) / len(scores)
            except Exception as exc:
                logger.debug("Enrich: macro failed: %s", exc)

        # 5. Northbound flow
        try:
            from src.data.macro_flow_fetcher import MacroFlowFetcher

            fetcher = MacroFlowFetcher()
            nb = await asyncio.to_thread(fetcher.fetch_northbound_today)
            if nb and isinstance(nb, dict):
                net = nb.get("net_flow") or nb.get("net", 0)
                if net:
                    # Use the KEY that debate engine checks: northbound_inflow
                    market_data["northbound_inflow"] = float(net)
                    market_data.setdefault("macro_score", 0)
                    if float(net) > 20:
                        market_data["macro_score"] += 0.15
                    elif float(net) < -20:
                        market_data["macro_score"] -= 0.15
        except Exception as exc:
            logger.debug("Enrich: northbound failed: %s", exc)

        enriched = [
            k
            for k in (
                "rsi",
                "volume_ratio",
                "capital_net_inflow",
                "macro_score",
                "macd_golden_cross",
                "northbound_inflow",
            )
            if k in market_data
        ]
        logger.info(
            "Enriched market_data for %s: %d debate-ready keys (%s)",
            symbol,
            len(enriched),
            ", ".join(enriched),
        )

    def _estimate_daily_pnl(self, positions: list[dict[str, Any]]) -> float:
        """Rough daily P&L as fraction of portfolio."""
        if not positions:
            return 0.0
        total_value = sum(p.get("market_value", 0) for p in positions)
        daily_pnl = sum(p.get("daily_pnl", 0) for p in positions)
        if total_value <= 0:
            return 0.0
        return daily_pnl / total_value

    def _record_proposal(self, proposal: TradeProposal) -> None:
        """Record proposal in decision log and push to action queue."""
        if self._decision_log_store:
            try:
                self._decision_log_store.record(
                    proposal_id=proposal.proposal_id,
                    symbol=proposal.symbol,
                    action=proposal.action,
                    price=proposal.price_target or 0,
                )
            except Exception as exc:
                logger.error("Failed to record decision: %s", exc)

        # Push to action queue for user confirmation
        if self._action_queue:
            try:
                self._action_queue.create_action(
                    symbol=proposal.symbol,
                    action=proposal.action,
                    urgency="immediate" if proposal.confidence >= 0.8 else "today",
                    confidence=proposal.confidence,
                    execution_plan={
                        "proposal_id": proposal.proposal_id,
                        "shares": proposal.shares,
                        "price_target": proposal.price_target,
                        "stop_loss": proposal.stop_loss,
                        "take_profit": proposal.take_profit,
                        "reasoning_chain": proposal.reasoning_chain,
                        "contingencies": [
                            {
                                "condition": c.condition,
                                "action": c.action,
                                "priority": c.priority,
                            }
                            for c in proposal.contingencies
                        ],
                        "risk_notes": proposal.risk_notes,
                        "debate_summary": proposal.debate_summary,
                    },
                    thesis_id=(proposal.thesis.id if proposal.thesis else None),
                )
                logger.info(
                    "Pushed proposal %s to action queue: %s %s",
                    proposal.proposal_id,
                    proposal.action,
                    proposal.symbol,
                )
            except Exception as exc:
                logger.error("Failed to push proposal to action queue: %s", exc)

    # Map InvestmentDirector notification types to AssistantPushCog types
    _ASSISTANT_TYPE_MAP: dict[str, str] = {
        "trade_signal": "buy_signal",  # AssistantPushCog uses buy_signal/sell_signal
        "morning_briefing": "pre_market",
        "close_briefing": "post_market",
        "evening_review": "post_market",
        "risk_alert": "risk_alert",
    }

    def _push_notification(self, notification_type: str, data: Any) -> None:
        """Push notification to Redis pub/sub for Discord.

        Dual-publishes to both channels for redundancy:
          1. ``notifications:push`` — PushNotificationsCog (ChannelRouter)
          2. ``assistant:messages``  — AssistantPushCog (rate-limited, quality-filtered)
        """
        import json

        try:
            from src.web.dependencies import get_redis

            redis_client = get_redis()
        except Exception as exc:
            logger.error("Failed to get Redis for %s: %s", notification_type, exc)
            redis_client = None

        if redis_client is None:
            return

        # 1. Publish to notifications:push (PushNotificationsCog → ChannelRouter)
        try:
            payload = {"type": notification_type, "data": data}
            redis_client.publish(
                "notifications:push",
                json.dumps(payload, ensure_ascii=False, default=str),
            )
            logger.debug("Published %s to notifications:push", notification_type)
        except Exception as exc:
            logger.error(
                "Failed to publish %s to notifications:push: %s", notification_type, exc
            )

        # 2. Also publish to assistant:messages (AssistantPushCog — redundant path)
        assistant_type = self._ASSISTANT_TYPE_MAP.get(notification_type)
        if assistant_type:
            try:
                # For trade_signal, determine buy vs sell from data
                if notification_type == "trade_signal" and isinstance(data, dict):
                    action = data.get("action", "")
                    if action in ("sell", "reduce"):
                        assistant_type = "sell_signal"

                # Use AutonomousTradingLoop's payload builder to match embed schema
                from src.agent_loop.trading_loop import AutonomousTradingLoop

                assistant_payload = AutonomousTradingLoop._build_assistant_payload(
                    assistant_type, notification_type, data
                )
                redis_client.publish(
                    "assistant:messages",
                    json.dumps(assistant_payload, ensure_ascii=False, default=str),
                )
                logger.debug("Published %s to assistant:messages", assistant_type)
            except Exception as exc:
                logger.debug("Failed to publish to assistant:messages: %s", exc)

        # 3. Forward to legacy NotificationDispatcher (WeChat/DingTalk) if available
        if self._notifier:
            try:
                title = notification_type.replace("_", " ").title()
                message = json.dumps(data, ensure_ascii=False, default=str)[:500]
                self._notifier.dispatch(
                    event_type=notification_type,
                    title=title,
                    message=message,
                )
            except Exception as exc:
                logger.debug(
                    "Legacy notifier dispatch failed for %s: %s", notification_type, exc
                )
