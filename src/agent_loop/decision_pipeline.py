"""Decision Pipeline — orchestrates multi-agent debate for a single signal.

Takes an AggregatedSignal, runs through urgency-appropriate debate process,
applies risk gates, and produces a TradeProposal.

Urgency tiers:
  CRITICAL — rule-based only (stop-loss, circuit breaker)
  HIGH     — quick debate (1 round)
  NORMAL   — full debate (3 rounds)
  DEEP     — extended debate (5 rounds) + Munger checklist

Phase 5: Confidence calibration integration
Phase 6: A-share constraint checking as first-class input
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.agent_loop.ashare_constraints import AShareConstraintChecker
from src.agent_loop.bayesian_belief import BayesianBeliefEngine, BayesianPosterior
from src.agent_loop.confidence_calibrator import ConfidenceCalibrator
from src.agent_loop.leader_detector import LeaderDetector, LeaderScore
from src.agent_loop.models import (
    AggregatedSignal,
    ContingencyRule,
    InvestmentThesis,
    TradeProposal,
    UrgencyTier,
)
from src.agent_loop.sentiment_cycle import SentimentCycleDetector, SentimentPhase
from src.risk.position_sizer import PositionSizer, PositionSizingConfig

logger = logging.getLogger(__name__)


class DecisionPipeline:
    """Produces a TradeProposal from an AggregatedSignal via debate + risk check."""

    def __init__(
        self,
        debate_engine: Any = None,
        calibrator: ConfidenceCalibrator | None = None,
        constraint_checker: AShareConstraintChecker | None = None,
        position_sizer: PositionSizer | None = None,
        bayesian_engine: BayesianBeliefEngine | None = None,
        sentiment_detector: SentimentCycleDetector | None = None,
        thesis_tracker: Any = None,
        budget_tracker: Any = None,
        leader_detector: LeaderDetector | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._debate_engine = debate_engine
        self._calibrator = calibrator or ConfidenceCalibrator()
        self._constraints = constraint_checker or AShareConstraintChecker()
        self._bayesian = bayesian_engine or BayesianBeliefEngine()
        self._sentiment_detector = sentiment_detector
        self._thesis_tracker = thesis_tracker
        self._budget_tracker = budget_tracker
        self._leader_detector = leader_detector
        self._current_sentiment: SentimentPhase | None = None
        # Leader stock gate: current cycle's confirmed leaders and main themes
        self._current_leaders: dict[str, LeaderScore] = {}  # symbol → LeaderScore
        self._current_main_themes: set[str] = set()  # sectors with 3+ limit-ups
        cfg = config or {}
        self._prescreen_threshold = cfg.get("bayesian_prescreen_threshold", 0.45)
        self._position_sizer = position_sizer or PositionSizer(
            PositionSizingConfig(
                max_single_weight=cfg.get("max_position_pct", 0.30),
                kelly_fraction=cfg.get("kelly_fraction", 0.25),
                target_volatility=cfg.get("target_volatility", 0.15),
            )
        )
        self._min_confidence = cfg.get("min_confidence_to_propose", 0.6)
        self._min_buy_confidence = cfg.get("min_confidence_to_recommend_buy", 0.7)
        self._max_position_pct = cfg.get("max_position_pct", 0.30)
        self._max_sector_pct = cfg.get("max_sector_pct", 0.40)
        self._max_daily_loss_pct = cfg.get("max_daily_loss_pct", 0.03)
        self._consecutive_loss_threshold = cfg.get("consecutive_loss_threshold", 3)
        self._consecutive_loss_factor = cfg.get("consecutive_loss_size_factor", 0.5)
        self._overnight_risk_budget = cfg.get("overnight_risk_budget_pct", 0.05)
        # De-risk the LLM-debate dependency: by default a buy is refused when the
        # debate engine is unavailable. When enabled, the deterministic stack may
        # issue a damped buy off the Bayesian prescreen so a missing/failed oracle
        # degrades gracefully instead of silently dropping the signal (#56).
        self._allow_degraded_buys = cfg.get("allow_degraded_buys", False)
        self._degraded_buy_min_prob = cfg.get("degraded_buy_min_prob", 0.60)

        # Circuit breaker state (Fix 2)
        self._portfolio_drawdown_halt_pct = cfg.get("portfolio_drawdown_halt_pct", 0.05)
        self._consecutive_stoploss_pause_count = cfg.get(
            "consecutive_stoploss_pause_count", 3
        )
        self._consecutive_stoploss_pause_hours = cfg.get(
            "consecutive_stoploss_pause_hours", 2.0
        )
        self._position_drawdown_halve_pct = cfg.get("position_drawdown_halve_pct", 0.08)
        self._consecutive_stoploss_count: int = 0
        self._stoploss_pause_until: float = 0.0  # epoch timestamp

        logger.info("DecisionPipeline initialized")

    def _degraded_buy_record(
        self, signal: AggregatedSignal, prescreen_p: float
    ) -> dict[str, Any] | None:
        """Synthesize a conservative buy when the LLM debate is unavailable.

        Returns ``None`` (refuse the buy — the safe default) unless
        ``allow_degraded_buys`` is set and the Bayesian prescreen clears
        ``degraded_buy_min_prob``. Scores are damped — there is no debate
        corroboration — so a degraded buy is weaker than a debated one.
        """
        if not self._allow_degraded_buys or prescreen_p < self._degraded_buy_min_prob:
            return None
        return {
            "bull_score": round(prescreen_p * 0.8, 4),
            "bear_score": round((1.0 - prescreen_p) * 0.8, 4),
            "reasoning": (
                f"Degraded buy (no debate): Bayesian prescreen P(bull)={prescreen_p:.2f}"
            ),
            "risk_veto": False,
            "final_action": signal.direction.value.lower(),
            "verdict": {"degraded": True},
            "degraded": True,
        }

    def _bayesian_prescreen(
        self,
        signal: AggregatedSignal,
        thesis: InvestmentThesis | None,
        market_data: dict[str, Any],
        portfolio: list[dict[str, Any]] | None = None,
        available_cash: float = 0.0,
    ) -> float:
        """Lightweight Bayesian inference without debate evidence.

        Returns preliminary P(bullish) for early rejection of weak signals
        before running the expensive debate engine.
        """
        # Compute portfolio context for Bayesian prior
        portfolio = portfolio or []
        signal_sector = (thesis.sector if thesis else "") or signal.metadata.get(
            "sector", ""
        )
        total_value = available_cash + sum(p.get("market_value", 0) for p in portfolio)
        portfolio_sector_weight = None
        portfolio_position_exists = False
        if total_value > 0 and signal_sector:
            sector_value = sum(
                p.get("market_value", 0)
                for p in portfolio
                if p.get("sector", "") == signal_sector
            )
            portfolio_sector_weight = sector_value / total_value
        portfolio_position_exists = any(
            p.get("symbol") == signal.symbol for p in portfolio
        )

        # Collect multi-source signals for richer prescreen
        all_signals = self._collect_bayesian_signals(signal, market_data)

        # Use sentiment phase as regime
        regime = "unknown"
        if self._current_sentiment:
            regime = self._current_sentiment.phase
        elif market_data.get("sentiment_phase"):
            regime = market_data["sentiment_phase"]
        elif market_data.get("regime"):
            regime = market_data["regime"]

        sector = (
            (thesis.sector if thesis else "")
            or signal.metadata.get("sector", "")
            or market_data.get("sector", "")
            or "default"
        )

        posterior = self._bayesian.infer(
            symbol=signal.symbol,
            signals=all_signals,
            sector=sector,
            regime=regime,
            portfolio_sector_weight=portfolio_sector_weight,
            portfolio_position_exists=portfolio_position_exists,
        )
        return BayesianBeliefEngine.posterior_to_confidence(
            posterior, signal.direction.value
        )

    def _collect_bayesian_signals(
        self,
        trigger_signal: AggregatedSignal,
        market_data: dict[str, Any],
        debate_record: dict[str, Any] | None = None,
    ) -> list[Any]:
        """Collect ALL available signals from market_data for Bayesian fusion.

        The trigger signal is always included. Additional signals are extracted
        from market_data fields that map to known Bayesian likelihood tables:
        capital_flow, technical, sentiment, intraday_pattern, vpin, reflexivity,
        mtf_alignment, leader_detection.

        This is what makes Bayesian a weapon: 1 signal gives LR=1.9,
        but 5 independent signals give combined LR=24+ → P(bull)>95%.
        """
        from src.agent_loop.bayesian_belief import SignalEvidence

        signals: list[SignalEvidence] = [trigger_signal]
        direction = trigger_signal.direction.value

        # Capital flow
        cap_flow = market_data.get("capital_net_inflow")
        if cap_flow is not None:
            if cap_flow > 1e8:
                bucket = "large_inflow"
            elif cap_flow > 0:
                bucket = "moderate_inflow"
            elif cap_flow > -1e8:
                bucket = "moderate_outflow"
            else:
                bucket = "large_outflow"
            signals.append(
                SignalEvidence(
                    source="capital_flow",
                    direction=direction,
                    strength=min(1.0, abs(cap_flow) / 5e8),
                    symbol=trigger_signal.symbol,
                    metadata={"bucket": bucket},
                )
            )

        # Technical (RSI-based)
        rsi = market_data.get("rsi")
        if rsi is not None:
            if rsi > 70:
                bucket = "strong_bearish"
            elif rsi > 60:
                bucket = "bearish"
            elif rsi < 30:
                bucket = "strong_bullish"
            elif rsi < 40:
                bucket = "bullish"
            else:
                bucket = "neutral"
            signals.append(
                SignalEvidence(
                    source="technical",
                    direction=direction,
                    strength=abs(rsi - 50) / 50,
                    symbol=trigger_signal.symbol,
                    metadata={"bucket": bucket},
                )
            )

        # Sentiment phase
        phase = market_data.get("sentiment_phase")
        if phase and phase in ("freezing", "ignition", "acceleration", "climax", "ebb"):
            signals.append(
                SignalEvidence(
                    source="sentiment",
                    direction=direction,
                    strength=market_data.get("sentiment_confidence", 0.5),
                    symbol=trigger_signal.symbol,
                    metadata={"bucket": phase},
                )
            )

        # Volume ratio → intraday pattern proxy
        vol_ratio = market_data.get("volume_ratio")
        if vol_ratio is not None and vol_ratio > 2.0:
            signals.append(
                SignalEvidence(
                    source="intraday_pattern",
                    direction=direction,
                    strength=min(1.0, vol_ratio / 5.0),
                    symbol=trigger_signal.symbol,
                    metadata={
                        "bucket": "bullish"
                        if direction in ("buy", "add")
                        else "bearish"
                    },
                )
            )

        # Debate verdict as evidence (if available)
        if debate_record:
            bull_score = debate_record.get("bull_score", 0)
            bear_score = debate_record.get("bear_score", 0)
            net = bull_score - bear_score
            if abs(net) > 0.1:
                bucket = (
                    "bullish" if net > 0.3 else "bearish" if net < -0.3 else "neutral"
                )
                signals.append(
                    SignalEvidence(
                        source="recommendation",
                        direction=direction,
                        strength=min(1.0, abs(net)),
                        symbol=trigger_signal.symbol,
                        metadata={
                            "bucket": "buy"
                            if net > 0.3
                            else "sell"
                            if net < -0.3
                            else "watch"
                        },
                    )
                )

        return signals

    def set_sentiment_phase(self, phase: SentimentPhase) -> None:
        """Update the current sentiment phase (called by trading loop)."""
        self._current_sentiment = phase
        logger.info(
            "Sentiment phase set: %s (%s) confidence=%.2f",
            phase.phase_cn,
            phase.phase,
            phase.confidence,
        )

    def set_current_leaders(self, leaders: list[LeaderScore]) -> None:
        """Update the current cycle's confirmed leaders (called by trading loop).

        Also extracts main themes (主线) — sectors with at least one confirmed
        leader.  Sectors with 3+ followers in the leader list are high-confidence
        main themes.
        """
        self._current_leaders = {ls.symbol: ls for ls in leaders if ls.is_leader}
        # Main themes: sectors that have at least one confirmed leader
        sector_counts: dict[str, int] = {}
        for ls in leaders:
            if ls.is_leader:
                sector_counts[ls.sector] = sector_counts.get(ls.sector, 0) + 1
        self._current_main_themes = set(sector_counts.keys())
        logger.info(
            "Leader gate updated: %d leaders across %d main themes %s",
            len(self._current_leaders),
            len(self._current_main_themes),
            list(self._current_main_themes)[:5],
        )

    async def evaluate(
        self,
        signal: AggregatedSignal,
        portfolio: list[dict[str, Any]],
        available_cash: float,
        daily_pnl_pct: float = 0.0,
        consecutive_losses: int = 0,
        thesis: InvestmentThesis | None = None,
        market_data: dict[str, Any] | None = None,
    ) -> TradeProposal | None:
        """Evaluate a signal and produce a TradeProposal if actionable.

        Returns None if the signal doesn't warrant a proposal (below threshold,
        vetoed by risk, etc.).
        """
        mkt = market_data or {}

        # Risk pre-check: daily loss circuit breaker
        if daily_pnl_pct < -self._max_daily_loss_pct and signal.direction.value in (
            "buy",
            "add",
        ):
            logger.warning(
                "Daily loss %.2f%% exceeds limit — blocking buy for %s",
                daily_pnl_pct * 100,
                signal.symbol,
            )
            return None

        # Sentiment phase: ebb blocks new buys entirely
        if self._current_sentiment and self._current_sentiment.phase == "ebb":
            if signal.direction.value.lower() in ("buy", "add"):
                logger.info(
                    "Sentiment phase 退潮 — blocking new buy for %s",
                    signal.symbol,
                )
                return None

        # --- HARD GATE: 龙头股 only (leader stock in main theme) ---
        # Buy/add requires the stock to be a confirmed leader in the current
        # main theme.  Everything else is rejected before expensive debate.
        if signal.direction.value.lower() in ("buy", "add"):
            rejection = self._check_leader_gate(signal)
            if rejection:
                logger.info(
                    "HARD GATE: %s — %s",
                    signal.symbol,
                    rejection,
                )
                return None

        # --- Fix 2: Circuit breaker layer 5 ---
        # Check for position-level drawdown halving (generates reduce proposal)
        if signal.direction.value.lower() not in ("sell", "reduce"):
            halve_proposal = self._check_position_drawdown(
                signal, portfolio, available_cash, market_data or {}
            )
            if halve_proposal is not None:
                return halve_proposal

        # Check portfolio-level and consecutive stop-loss circuit breakers
        if signal.direction.value.lower() in ("buy", "add"):
            cb_reason = self._check_circuit_breakers(
                daily_pnl_pct, consecutive_losses, portfolio, available_cash
            )
            if cb_reason:
                logger.warning(
                    "Circuit breaker: %s — blocking buy for %s",
                    cb_reason,
                    signal.symbol,
                )
                return None

        # Route by urgency
        if signal.urgency == UrgencyTier.CRITICAL:
            return self._handle_critical(signal, portfolio, available_cash)

        # --- Fix 1: Convergence gate ---
        # Buy/add requires 2+ independent source domains
        if signal.direction.value.lower() in ("buy", "add"):
            if signal.source_count < 2:
                logger.info(
                    "Convergence invariant: buy blocked for %s — "
                    "only %d source domain(s), need 2+",
                    signal.symbol,
                    signal.source_count,
                )
                return None

        # --- UST: Bayesian prescreen (cheap, before expensive debate) ---
        is_buy = signal.direction.value.lower() in ("buy", "add")
        prescreen_p = 1.0
        if is_buy:
            prescreen_p = self._bayesian_prescreen(
                signal, thesis, mkt, portfolio, available_cash
            )
            if prescreen_p < self._prescreen_threshold:
                logger.info(
                    "Bayesian prescreen: P(bull)=%.2f < %.2f — skip debate %s",
                    prescreen_p,
                    self._prescreen_threshold,
                    signal.symbol,
                )
                return None

        # --- UST: LLM budget check (before expensive debate) ---
        budget_exhausted = bool(
            self._budget_tracker and not self._budget_tracker.can_call("gemini_web")
        )
        if budget_exhausted and not is_buy:
            logger.info(
                "LLM budget exhausted — sell/reduce %s passes through", signal.symbol
            )

        # Run the debate unless the budget is exhausted for a buy.
        debate_record = (
            None
            if (budget_exhausted and is_buy)
            else self._run_debate(signal, mkt, thesis)
        )
        if debate_record is None:
            if is_buy:
                # Debate unavailable (no engine, or budget exhausted). Default is
                # to refuse; allow_degraded_buys lets the deterministic stack
                # issue a damped buy off the prescreen instead (#56).
                debate_record = self._degraded_buy_record(signal, prescreen_p)
                if debate_record is None:
                    logger.warning(
                        "Debate unavailable — refusing buy for %s "
                        "(set allow_degraded_buys for graceful degradation)",
                        signal.symbol,
                    )
                    return None
                logger.info(
                    "Debate unavailable — degraded buy for %s (prescreen P=%.2f)",
                    signal.symbol,
                    prescreen_p,
                )
            else:
                # Sell/reduce: allow passthrough without debate
                logger.info(
                    "Debate engine unavailable — sell/reduce for %s passes through",
                    signal.symbol,
                )
                debate_record = {
                    "bull_score": 0.0,
                    "bear_score": signal.confidence,
                    "reasoning": signal.reason,
                    "risk_veto": False,
                    "final_action": signal.direction.value.lower(),
                    "verdict": {},
                }

        # Record LLM call in budget tracker
        if self._budget_tracker and debate_record:
            self._budget_tracker.record_call("gemini_web")

        bull_score = debate_record.get("bull_score", 0.0)
        bear_score = debate_record.get("bear_score", 0.0)
        debate_summary = debate_record.get("reasoning", "")
        risk_veto = debate_record.get("risk_veto", False)
        final_action = debate_record.get("final_action", "hold")
        verdict = debate_record.get("verdict", {})

        # Risk veto blocks actionable proposals
        if risk_veto and final_action in ("buy", "add"):
            logger.info(
                "Risk veto for %s: %s",
                signal.symbol,
                debate_record.get("risk_veto_reason", ""),
            )
            return None

        # Compute portfolio context for Bayesian prior (v50.0 §4.3)
        signal_sector = (thesis.sector if thesis else "") or signal.metadata.get(
            "sector", ""
        )
        total_value = available_cash + sum(p.get("market_value", 0) for p in portfolio)
        pf_sector_weight = None
        pf_position_exists = False
        if total_value > 0 and signal_sector:
            sector_value = sum(
                p.get("market_value", 0)
                for p in portfolio
                if p.get("sector", "") == signal_sector
            )
            pf_sector_weight = sector_value / total_value
        pf_position_exists = any(p.get("symbol") == signal.symbol for p in portfolio)

        # Bayesian posterior replaces raw confidence for Kelly sizing
        # Collect ALL available signals for multi-source fusion
        all_signals = self._collect_bayesian_signals(signal, mkt, debate_record)

        # Use sentiment phase as regime (more informative than HMM)
        regime = "unknown"
        if self._current_sentiment:
            regime = self._current_sentiment.phase
        elif mkt.get("sentiment_phase"):
            regime = mkt["sentiment_phase"]
        elif mkt.get("regime"):
            regime = mkt["regime"]

        # Extract sector from thesis, signal metadata, or market_data
        sector = (
            (thesis.sector if thesis else "")
            or signal.metadata.get("sector", "")
            or mkt.get("sector", "")
            or "default"
        )

        posterior = self._bayesian.infer(
            symbol=signal.symbol,
            signals=all_signals,
            sector=sector,
            regime=regime,
            quant_p_up=verdict.get("win_probability"),
            portfolio_sector_weight=pf_sector_weight,
            portfolio_position_exists=pf_position_exists,
        )
        raw_confidence = BayesianBeliefEngine.posterior_to_confidence(
            posterior, final_action
        )

        # Apply adaptive calibration on top of Bayesian posterior
        confidence = self._calibrator.calibrate(
            raw_confidence=raw_confidence,
            symbol=signal.symbol,
            action=final_action,
            sector=thesis.sector if thesis else "",
            regime=mkt.get("regime", "unknown"),
        )

        logger.info(
            "CONFIDENCE %s: signal=%.2f → posterior=%.2f → calibrated=%.2f",
            signal.symbol,
            signal.confidence,
            raw_confidence,
            confidence,
        )

        if confidence < self._min_confidence:
            logger.debug(
                "Confidence %.2f below threshold for %s", confidence, signal.symbol
            )
            return None

        if final_action in ("buy", "add") and confidence < self._min_buy_confidence:
            logger.debug(
                "Buy confidence %.2f below buy threshold for %s",
                confidence,
                signal.symbol,
            )
            return None

        # Sector concentration check
        signal_sector = (thesis.sector if thesis else "") or signal.metadata.get(
            "sector", ""
        )
        if final_action in ("buy", "add") and signal_sector:
            total_value = available_cash + sum(
                p.get("market_value", 0) for p in portfolio
            )
            if total_value > 0:
                sector_value = sum(
                    p.get("market_value", 0)
                    for p in portfolio
                    if p.get("sector", "") == signal_sector
                )
                sector_pct = sector_value / total_value
                if sector_pct >= self._max_sector_pct:
                    logger.info(
                        "Sector %s at %.1f%% — blocks buy for %s (limit %.0f%%)",
                        signal_sector,
                        sector_pct * 100,
                        signal.symbol,
                        self._max_sector_pct * 100,
                    )
                    return None

        # Position sizing — use Bayesian posterior as Kelly win_rate
        shares, risk_notes = self._size_position(
            signal=signal,
            action=final_action,
            portfolio=portfolio,
            available_cash=available_cash,
            price=mkt.get("current_price", signal.metadata.get("entry_price")),
            consecutive_losses=consecutive_losses,
            posterior=posterior,
        )

        if shares == 0 and final_action in ("buy", "add"):
            return None

        # A-share constraint check (Phase 6)
        total_value = available_cash + sum(p.get("market_value", 0) for p in portfolio)
        current_price = mkt.get("current_price", signal.metadata.get("entry_price", 0))
        ashare_assessment = self._constraints.assess_trade(
            symbol=signal.symbol,
            action=final_action,
            shares=shares,
            price=current_price or 0,
            portfolio_value=total_value,
            market_data=mkt,
        )

        if not ashare_assessment.tradeable:
            logger.info(
                "A-share constraints block %s for %s: %s",
                final_action,
                signal.symbol,
                ashare_assessment.constraint_violations,
            )
            return None

        # Use constraint-adjusted shares (lot-rounded)
        if ashare_assessment.shares_rounded != shares:
            shares = ashare_assessment.shares_rounded

        # Add A-share warnings to risk notes
        risk_notes.extend(ashare_assessment.risk_warnings)

        # Portfolio impact
        portfolio_impact = self._compute_portfolio_impact(
            signal.symbol,
            final_action,
            shares,
            mkt.get("current_price", 0),
            portfolio,
            available_cash,
        )

        # Overnight risk uses A-share assessment (board-specific limits)
        overnight_risk = ashare_assessment.overnight_max_loss_pct

        # Build reasoning chain
        cal_note = (
            f" [贝叶斯后验: {raw_confidence:.0%}→校准: {confidence:.0%}]"
            if abs(raw_confidence - confidence) > 0.01
            else f" [贝叶斯后验: {raw_confidence:.0%}]"
        )
        reasoning_chain = [
            f"信号来源: {signal.source} ({signal.reason})",
            f"辩论结果: 多方{bull_score:.2f} vs 空方{bear_score:.2f}",
            f"裁决: {final_action} (置信度{confidence:.0%}{cal_note})",
            f"T+1约束: {ashare_assessment.board_type}板 ±{ashare_assessment.price_limit_pct:.0f}% "
            f"隔夜最大损失{overnight_risk:.1%}",
        ]
        if self._current_sentiment:
            reasoning_chain.append(
                f"情绪周期: {self._current_sentiment.phase_cn} "
                f"(置信度{self._current_sentiment.confidence:.0%})"
            )
        if thesis:
            reasoning_chain.insert(0, f"投资论点: {thesis.thesis_text[:100]}")
        if risk_notes:
            reasoning_chain.append(f"风险提示: {'; '.join(risk_notes)}")

        proposal = TradeProposal(
            symbol=signal.symbol,
            name=signal.name,
            action=final_action,
            shares=shares,
            price_target=mkt.get("current_price"),
            stop_loss=verdict.get("stop_loss_pct"),
            take_profit=verdict.get("take_profit_pct"),
            confidence=confidence,
            risk_reward_ratio=verdict.get("risk_reward_ratio"),
            thesis=thesis,
            debate_summary=debate_summary,
            bull_score=bull_score,
            bear_score=bear_score,
            risk_notes=risk_notes,
            portfolio_impact=portfolio_impact,
            overnight_risk_pct=overnight_risk,
            reasoning_chain=reasoning_chain,
            contingencies=self._build_contingencies(
                action=final_action,
                stop_loss_pct=verdict.get("stop_loss_pct"),
                take_profit_pct=verdict.get("take_profit_pct"),
                entry_price=mkt.get("current_price"),
                thesis=thesis,
            ),
        )

        # Thesis lifecycle integration
        self._handle_thesis_lifecycle(proposal, signal, thesis, debate_summary)

        return proposal

    @staticmethod
    def _build_contingencies(
        action: str,
        stop_loss_pct: float | None,
        take_profit_pct: float | None,
        entry_price: float | None,
        thesis: InvestmentThesis | None,
    ) -> list[ContingencyRule]:
        """Generate execution contingency rules for a TradeProposal.

        Gives the execution trader clear if-then instructions for
        post-trade scenarios.
        """
        rules: list[ContingencyRule] = []

        if action in ("buy", "add"):
            # 1. Stop-loss contingency (critical)
            sl = stop_loss_pct or (thesis.stop_loss_pct if thesis else None) or 5.0
            if entry_price:
                sl_price = entry_price * (1 - sl / 100)
                rules.append(
                    ContingencyRule(
                        condition=f"价格跌破 {sl_price:.2f} 元（入场价下方 {sl:.1f}%）",
                        action="全部卖出",
                        priority="critical",
                        expiry_session="next_day",
                    )
                )
            else:
                rules.append(
                    ContingencyRule(
                        condition=f"价格跌破入场价 {sl:.1f}%",
                        action="全部卖出",
                        priority="critical",
                        expiry_session="next_day",
                    )
                )

            # 2. Take-profit contingency (important)
            tp = take_profit_pct or 8.0
            if entry_price:
                tp_price = entry_price * (1 + tp / 100)
                rules.append(
                    ContingencyRule(
                        condition=f"价格涨至 {tp_price:.2f} 元（入场价上方 {tp:.1f}%）",
                        action="考虑卖出50%锁定利润",
                        priority="important",
                        expiry_session="next_day",
                    )
                )
            else:
                rules.append(
                    ContingencyRule(
                        condition=f"涨幅超过 {tp:.1f}%",
                        action="考虑卖出50%锁定利润",
                        priority="important",
                        expiry_session="next_day",
                    )
                )

            # 3. Thesis invalidation contingency (critical)
            if thesis and thesis.invalidation_conditions:
                inv_text = "；".join(thesis.invalidation_conditions[:2])
                rules.append(
                    ContingencyRule(
                        condition=f"论点失效: {inv_text}",
                        action="立即全部卖出",
                        priority="critical",
                        expiry_session="next_day",
                    )
                )
            else:
                rules.append(
                    ContingencyRule(
                        condition="投资论点核心假设被证伪",
                        action="立即全部卖出",
                        priority="critical",
                        expiry_session="next_day",
                    )
                )

        elif action in ("sell", "reduce"):
            # Re-evaluation contingency for sells (optional)
            if entry_price:
                rules.append(
                    ContingencyRule(
                        condition=f"价格回升至 {entry_price:.2f} 元以上",
                        action="重新评估投资论点，考虑是否重新建仓",
                        priority="optional",
                        expiry_session="next_day",
                    )
                )

        return rules

    def _handle_thesis_lifecycle(
        self,
        proposal: TradeProposal,
        signal: AggregatedSignal,
        thesis: InvestmentThesis | None,
        debate_summary: str,
    ) -> None:
        """Auto-create thesis on buy, resolve thesis on sell."""
        if self._thesis_tracker is None:
            return

        try:
            if proposal.action in ("buy", "add"):
                invalidation = ""
                if proposal.stop_loss:
                    invalidation = f"跌破止损位 {proposal.stop_loss}%"
                self._thesis_tracker.create_thesis(
                    symbol=proposal.symbol,
                    direction="long",
                    narrative=debate_summary[:500] if debate_summary else signal.reason,
                    entry_condition=signal.reason,
                    invalidation_condition=invalidation,
                    confidence=proposal.confidence,
                )
                logger.info(
                    "Auto-created thesis for %s buy (conf=%.2f)",
                    proposal.symbol,
                    proposal.confidence,
                )

            elif proposal.action in ("sell", "reduce"):
                active = self._thesis_tracker.list_theses(
                    status=None, symbol=proposal.symbol
                )
                for t in active:
                    if t.status in ("active", "weakening"):
                        reason = signal.reason or debate_summary or "Position closed"
                        if proposal.confidence >= 0.5:
                            self._thesis_tracker.realize_thesis(t.id, reason)
                        else:
                            self._thesis_tracker.invalidate_thesis(t.id, reason)
                        break
        except Exception as exc:
            logger.warning("Thesis lifecycle hook failed: %s", exc)

    # ------------------------------------------------------------------
    # Fix 2: Circuit breaker layer 5
    # ------------------------------------------------------------------

    def _check_circuit_breakers(
        self,
        daily_pnl_pct: float,
        consecutive_losses: int,
        portfolio: list[dict[str, Any]],
        available_cash: float,
    ) -> str | None:
        """Return a rejection reason if any circuit breaker triggers, else None.

        Three conditions (all for buy/add only):
        1. Portfolio drawdown halt: cumulative daily loss > 5% → halt buys
        2. Consecutive stop-loss pause: 3+ consecutive stop-losses → pause 2h
        3. (Position drawdown halving is handled separately via
           _check_position_drawdown, which generates a reduce proposal.)
        """
        # 1. Portfolio drawdown halt
        if daily_pnl_pct < -self._portfolio_drawdown_halt_pct:
            return (
                f"Portfolio drawdown {daily_pnl_pct:.1%} exceeds "
                f"-{self._portfolio_drawdown_halt_pct:.0%} halt threshold"
            )

        # 2. Consecutive stop-loss pause
        if consecutive_losses >= self._consecutive_stoploss_pause_count:
            if time.time() < self._stoploss_pause_until:
                remaining = self._stoploss_pause_until - time.time()
                return (
                    f"Consecutive stop-loss pause active — "
                    f"{consecutive_losses} stop-losses, "
                    f"{remaining / 60:.0f}min remaining"
                )
            # First time hitting the threshold in this window — start pause
            if consecutive_losses > self._consecutive_stoploss_count:
                self._consecutive_stoploss_count = consecutive_losses
                self._stoploss_pause_until = (
                    time.time() + self._consecutive_stoploss_pause_hours * 3600
                )
                return (
                    f"Consecutive stop-loss pause triggered — "
                    f"{consecutive_losses} stop-losses, "
                    f"pausing buys for {self._consecutive_stoploss_pause_hours:.0f}h"
                )

        return None

    def _check_position_drawdown(
        self,
        signal: AggregatedSignal,
        portfolio: list[dict[str, Any]],
        available_cash: float,
        market_data: dict[str, Any],
    ) -> TradeProposal | None:
        """If any held position is down > 8% intraday, generate 'reduce 50%'.

        Only triggers for the specific position matching the signal symbol.
        Returns a reduce proposal or None.
        """
        held = next((p for p in portfolio if p.get("symbol") == signal.symbol), None)
        if not held:
            return None

        intraday_change = held.get("intraday_change_pct", 0.0)
        if intraday_change >= -self._position_drawdown_halve_pct:
            return None

        held_shares = held.get("shares", 0)
        reduce_shares = (held_shares // 200) * 100
        if reduce_shares < 100:
            return None

        logger.warning(
            "Position drawdown circuit breaker: %s down %.1f%% intraday "
            "— auto-generating reduce 50%% proposal (%d shares)",
            signal.symbol,
            intraday_change * 100,
            reduce_shares,
        )

        return TradeProposal(
            symbol=signal.symbol,
            name=signal.name,
            action="reduce",
            shares=reduce_shares,
            price_target=market_data.get("current_price", held.get("current_price")),
            confidence=0.90,
            debate_summary="仓位日内跌幅超限 — 自动减仓50%",
            bull_score=0.0,
            bear_score=0.9,
            risk_notes=[
                f"日内跌幅{intraday_change:.1%}超过-{self._position_drawdown_halve_pct:.0%}阈值"
            ],
            reasoning_chain=[
                f"熔断触发: {signal.symbol}日内跌幅{intraday_change:.1%}",
                f"超过-{self._position_drawdown_halve_pct:.0%}仓位熔断阈值",
                f"自动减仓50% ({reduce_shares}股)",
            ],
        )

    def reset_circuit_breakers(self) -> None:
        """Reset circuit breaker state (e.g., at start of new trading day)."""
        self._consecutive_stoploss_count = 0
        self._stoploss_pause_until = 0.0

    # ------------------------------------------------------------------
    # Fix 3: Cash target management
    # ------------------------------------------------------------------

    def _get_cash_target(self) -> float:
        """Return target cash percentage based on current sentiment phase.

        Sentiment phase → target cash %:
            冰点 (freezing):      80%
            启动 (ignition):      50%
            加速 (acceleration):  20%
            高潮 (climax):        40%
            退潮 (ebb):           80%

        Returns 0.5 (50%) when no sentiment phase is set.
        """
        if not self._current_sentiment:
            return 0.5

        return _SENTIMENT_CASH_TARGETS.get(self._current_sentiment.phase, 0.5)

    def _check_leader_gate(self, signal: AggregatedSignal) -> str | None:
        """Hard gate: reject any buy/add that is NOT a leader stock in main theme.

        Returns a rejection reason string, or None if the stock passes.

        When ``_leader_detector`` is None AND ``_current_leaders`` is empty,
        the gate is inactive (pass-through) so the system degrades gracefully
        when leader detection is not configured.
        """
        # Gate inactive — no leader detector and no cached leaders
        if not self._leader_detector and not self._current_leaders:
            return None

        # Check against cached leader list (populated by set_current_leaders)
        if self._current_leaders:
            leader = self._current_leaders.get(signal.symbol)
            if not leader:
                return "非龙头股，拒绝交易"
            # Leader confirmed — also verify it's in a main theme sector
            if (
                self._current_main_themes
                and leader.sector not in self._current_main_themes
            ):
                return f"非主线板块({leader.sector})，拒绝交易"
            return None  # passes gate

        # Fallback: leader_detector exists but no cached leaders yet.
        # This means SENSE phase hasn't run leader scan — block buys
        # conservatively (no leaders identified = nothing to buy).
        return "龙头扫描未完成，无确认龙头股，拒绝交易"

    def _handle_critical(
        self,
        signal: AggregatedSignal,
        portfolio: list[dict[str, Any]],
        available_cash: float,
    ) -> TradeProposal | None:
        """Handle CRITICAL signals (stop-loss, circuit breaker) — no debate."""
        held = next((p for p in portfolio if p.get("symbol") == signal.symbol), None)
        if not held:
            return None

        shares = held.get("shares", 0)
        return TradeProposal(
            symbol=signal.symbol,
            name=signal.name,
            action="sell",
            shares=shares,
            price_target=None,
            confidence=0.95,
            debate_summary="紧急信号 — 跳过辩论，直接风控处理",
            bull_score=0.0,
            bear_score=1.0,
            risk_notes=[signal.reason],
            reasoning_chain=[
                f"紧急信号: {signal.reason}",
                "风控规则触发，建议立即卖出",
            ],
        )

    def _run_debate(
        self,
        signal: AggregatedSignal,
        market_data: dict[str, Any],
        thesis: InvestmentThesis | None,
    ) -> dict[str, Any] | None:
        """Run bull/bear debate via DebateEngine with independent evidence.

        P1 audit fix: Bull and bear must cite evidence from DIFFERENT domains
        than the signal source.  This prevents circular reasoning where the
        debate simply restates the trigger signal.

        Returns None when debate engine is unavailable.  The caller is
        responsible for deciding whether to block the trade (buys) or
        pass through (sells).
        """
        if self._debate_engine is None:
            return None

        # Enrich market_data with thesis info and independent evidence context
        data = dict(market_data)
        if thesis:
            data["macro_score"] = data.get("macro_score", 0)
            data["t_plus_1_risk"] = True

        # P1 audit fix: inject independent evidence requirements into debate
        # Bull must cite evidence from a DIFFERENT domain than signal source;
        # Bear must cite market microstructure or macro environment data.
        data["_signal_source_domain"] = signal.source
        data["_debate_independence_rules"] = {
            "bull_excluded_domain": signal.source,
            "bull_required_domains": [
                d
                for d in (
                    "macro",
                    "capital_flow",
                    "technical",
                    "sentiment",
                    "fundamental",
                )
                if d != signal.source
            ],
            "bear_required_domains": ["macro", "capital_flow", "technical"],
            "bear_focus": "market microstructure or macro environment",
        }

        # Inject sentiment phase as debate context
        if self._current_sentiment:
            data["sentiment_phase"] = self._current_sentiment.phase
            data["sentiment_phase_cn"] = self._current_sentiment.phase_cn
            data["sentiment_confidence"] = self._current_sentiment.confidence

        # Inject available cross-domain evidence for richer debate
        if thesis:
            data["thesis_narrative"] = thesis.thesis_text[:200]
            data["thesis_confidence"] = thesis.confidence

        # Determine debate rounds by urgency (v55.0 FR-55-002)
        from src.agent_loop.models import UrgencyTier

        _URGENCY_ROUNDS = {
            UrgencyTier.CRITICAL: 0,
            UrgencyTier.HIGH: 1,
            UrgencyTier.NORMAL: 3,
            UrgencyTier.DEEP: 5,
        }
        max_rounds = _URGENCY_ROUNDS.get(signal.urgency, 3)

        try:
            from src.intelligence.debate_engine import LLMDebateEngine

            if isinstance(self._debate_engine, LLMDebateEngine):
                record = self._debate_engine.run_debate(
                    symbol=signal.symbol,
                    name=signal.name,
                    trigger=f"{signal.source}: {signal.reason}",
                    market_data=data,
                    max_rounds=max_rounds,
                )
            else:
                record = self._debate_engine.run_debate(
                    symbol=signal.symbol,
                    name=signal.name,
                    trigger=f"{signal.source}: {signal.reason}",
                    market_data=data,
                )
            return record.to_dict()
        except Exception as exc:
            logger.error("Debate engine failed for %s: %s", signal.symbol, exc)
            return None

    def _size_position(
        self,
        signal: AggregatedSignal,
        action: str,
        portfolio: list[dict[str, Any]],
        available_cash: float,
        price: float | None,
        consecutive_losses: int = 0,
        posterior: BayesianPosterior | None = None,
    ) -> tuple[int, list[str]]:
        """Calculate position size in shares (100-lot) using Kelly criterion.

        Uses PositionSizer (Kelly + vol-scaling) for buy/add sizing, with
        consecutive loss penalty, sentiment phase limits, and existing
        position cap applied on top.  The Bayesian posterior is used as
        the Kelly win_rate instead of raw signal confidence.
        """
        risk_notes: list[str] = []

        if action in ("sell", "reduce"):
            held = next(
                (p for p in portfolio if p.get("symbol") == signal.symbol), None
            )
            if not held:
                return 0, ["未持有该股票"]
            held_shares = held.get("shares", 0)
            if action == "sell":
                return held_shares, risk_notes
            # reduce: sell half
            reduce_shares = (held_shares // 200) * 100
            return max(reduce_shares, 100) if reduce_shares > 0 else 0, risk_notes

        if action == "hold":
            return 0, risk_notes

        # Buy/add sizing
        if not price or price <= 0:
            return 0, ["无法获取当前价格"]

        total_value = available_cash + sum(p.get("market_value", 0) for p in portfolio)
        existing_value = sum(
            p.get("market_value", 0)
            for p in portfolio
            if p.get("symbol") == signal.symbol
        )

        # Apply sentiment phase limits to position cap
        max_position_pct = self._max_position_pct
        max_total_equity_pct = 1.0  # default: no total equity limit
        sentiment_limits = self._get_sentiment_limits()
        if sentiment_limits:
            max_position_pct = min(
                max_position_pct, sentiment_limits["max_position_pct"]
            )
            max_total_equity_pct = sentiment_limits["max_total_equity_pct"]
            risk_notes.append(
                f"情绪周期{sentiment_limits['phase_cn']}: "
                f"单仓≤{max_position_pct:.0%}, 总仓≤{max_total_equity_pct:.0%}"
            )

        # Check total equity limit from sentiment phase
        current_equity_pct = (
            sum(p.get("market_value", 0) for p in portfolio) / total_value
            if total_value > 0
            else 0.0
        )
        if current_equity_pct >= max_total_equity_pct:
            risk_notes.append(
                f"总仓位{current_equity_pct:.0%}已达情绪周期上限{max_total_equity_pct:.0%}"
            )
            return 0, risk_notes

        # Fix 3: Cash target management — regime-dependent cash floor
        cash_target = self._get_cash_target()
        current_cash_pct = available_cash / total_value if total_value > 0 else 1.0
        if current_cash_pct <= cash_target:
            risk_notes.append(
                f"现金{current_cash_pct:.0%}已低于情绪周期目标{cash_target:.0%} — 禁止开仓"
            )
            return 0, risk_notes

        # Limit deployment so cash stays above target
        max_deployable = available_cash - (total_value * cash_target)
        if max_deployable <= 0:
            risk_notes.append(f"维持现金目标{cash_target:.0%} — 无可用资金")
            return 0, risk_notes

        # Check existing position cap
        max_allocation = total_value * max_position_pct
        remaining = min(max_allocation - existing_value, available_cash, max_deployable)

        if remaining <= 0:
            risk_notes.append(f"仓位已达上限({max_position_pct:.0%})")
            return 0, risk_notes

        # Consecutive loss penalty
        if consecutive_losses >= self._consecutive_loss_threshold:
            remaining *= self._consecutive_loss_factor
            risk_notes.append(f"连续亏损{consecutive_losses}次，仓位减半")

        # Kelly + vol-scaling via PositionSizer
        # Use Bayesian posterior as win_rate (instead of raw confidence)
        if posterior is not None:
            win_rate = min(
                BayesianBeliefEngine.posterior_to_kelly_win_rate(posterior, action),
                0.95,
            )
            logger.debug(
                "Kelly win_rate from posterior: %.3f (raw signal: %.3f)",
                win_rate,
                signal.confidence,
            )
        else:
            win_rate = min(signal.confidence, 0.95)

        avg_win = signal.metadata.get("avg_win", 0.05)
        avg_loss = signal.metadata.get("avg_loss", 0.03)
        realized_vol = signal.metadata.get("realized_vol")

        sizing = self._position_sizer.calculate_size(
            symbol=signal.symbol,
            portfolio_value=remaining,
            current_price=price,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            realized_vol=realized_vol,
        )

        risk_notes.extend(sizing.warnings)
        if sizing.capped:
            risk_notes.append("Kelly仓位已触及上限")

        shares = sizing.recommended_shares
        if shares < 100:
            return 0, risk_notes or ["资金不足一手(100股)"]

        return shares, risk_notes

    def _get_sentiment_limits(self) -> dict[str, Any] | None:
        """Return position limits based on current sentiment phase.

        P1 audit fix: tighter limits aligned with sentiment-driven risk budget.

        Sentiment phase → (max_position_pct, max_total_equity_pct):
            freezing    → 5%,  15%  (冰点: capital preservation)
            ignition    → 15%, 50%  (启动: early participation)
            acceleration→ 25%, 80%  (加速: follow momentum)
            climax      → 15%, 60%  (高潮: start reducing)
            ebb         → 5%,  10%  (退潮: sells only — buys blocked above)
        """
        phase = self._current_sentiment
        if not phase:
            return None

        limits = _SENTIMENT_POSITION_LIMITS.get(phase.phase)
        if not limits:
            return None

        return {
            "phase": phase.phase,
            "phase_cn": phase.phase_cn,
            "max_position_pct": limits[0],
            "max_total_equity_pct": limits[1],
        }

    def _compute_portfolio_impact(
        self,
        symbol: str,
        action: str,
        shares: int,
        price: float,
        portfolio: list[dict[str, Any]],
        available_cash: float,
    ) -> dict[str, Any]:
        """Compute how this trade would change portfolio composition."""
        total_value = available_cash + sum(p.get("market_value", 0) for p in portfolio)
        if total_value <= 0:
            return {}

        trade_value = shares * price if price else 0
        existing_value = sum(
            p.get("market_value", 0) for p in portfolio if p.get("symbol") == symbol
        )

        if action in ("buy", "add"):
            new_value = existing_value + trade_value
        elif action in ("sell", "reduce"):
            new_value = max(0, existing_value - trade_value)
        else:
            new_value = existing_value

        # total_value > 0 is guaranteed by the earlier `total_value <= 0` return.
        weight_after = new_value / total_value
        position_count = len(portfolio) + (
            1 if action == "buy" and existing_value == 0 else 0
        )

        return {
            "weight_after": round(weight_after, 4),
            "trade_value": round(trade_value, 2),
            "position_count": position_count,
        }

    def _estimate_overnight_risk(
        self,
        symbol: str,
        price: float,
        shares: int,
        daily_change_pct: float,
        total_portfolio_value: float,
    ) -> float | None:
        """Estimate T+1 overnight risk as % of portfolio.

        Uses board-specific price limits (±10% main, ±20% ChiNext/STAR).
        """
        if not price or not shares or total_portfolio_value <= 0:
            return None

        board = AShareConstraintChecker._detect_board_type(symbol)
        from src.agent_loop.ashare_constraints import _PRICE_LIMITS

        limit_pct = _PRICE_LIMITS.get(board, 10.0)

        position_value = price * shares
        max_loss = position_value * (limit_pct / 100.0)
        risk_pct = max_loss / total_portfolio_value

        # Penalize if stock already moved significantly today
        if abs(daily_change_pct) > limit_pct / 100.0 * 0.8:
            risk_pct *= 1.5

        return round(risk_pct, 4)


# -- Sentiment phase → position limits --
# (max_single_position_pct, max_total_equity_pct)
# P1 audit fix: tighter limits aligned with sentiment-driven risk budget
_SENTIMENT_POSITION_LIMITS: dict[str, tuple[float, float]] = {
    "freezing": (0.05, 0.15),  # 冰点: very conservative — capital preservation
    "ignition": (0.15, 0.50),  # 启动: moderate — early participation
    "acceleration": (0.25, 0.80),  # 加速: aggressive — follow momentum
    "climax": (0.15, 0.60),  # 高潮: start reducing — reversal risk
    "ebb": (0.05, 0.10),  # 退潮: minimal (sells only)
}

# -- Sentiment phase → target cash % (Fix 3) --
_SENTIMENT_CASH_TARGETS: dict[str, float] = {
    "freezing": 0.80,  # 冰点: capital preservation
    "ignition": 0.50,  # 启动: cautious participation
    "acceleration": 0.20,  # 加速: deploy capital
    "climax": 0.40,  # 高潮: start pulling back
    "ebb": 0.80,  # 退潮: preserve capital
}
