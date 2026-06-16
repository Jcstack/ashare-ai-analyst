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
from typing import Any

from src.agent_loop.ashare_constraints import AShareConstraintChecker
from src.agent_loop.confidence_calibrator import ConfidenceCalibrator
from src.agent_loop.models import (
    AggregatedSignal,
    InvestmentThesis,
    TradeProposal,
    UrgencyTier,
)
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
        config: dict[str, Any] | None = None,
    ) -> None:
        self._debate_engine = debate_engine
        self._calibrator = calibrator or ConfidenceCalibrator()
        self._constraints = constraint_checker or AShareConstraintChecker()
        cfg = config or {}
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
        logger.info("DecisionPipeline initialized")

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

        # Route by urgency
        if signal.urgency == UrgencyTier.CRITICAL:
            return self._handle_critical(signal, portfolio, available_cash)

        # Run debate
        debate_record = self._run_debate(signal, mkt, thesis)
        bull_score = debate_record.get("bull_score", 0.0)
        bear_score = debate_record.get("bear_score", 0.0)
        debate_summary = debate_record.get("reasoning", "")
        risk_veto = debate_record.get("risk_veto", False)
        final_action = debate_record.get("final_action", "hold")
        verdict = debate_record.get("verdict", {})

        # Risk veto blocks actionable proposals
        if risk_veto and final_action in ("buy", "add"):
            logger.info("Risk veto for %s: %s", signal.symbol, debate_record.get("risk_veto_reason", ""))
            return None

        # Confidence gate — apply adaptive calibration (Phase 5)
        raw_confidence = verdict.get("win_probability", signal.confidence)
        confidence = self._calibrator.calibrate(
            raw_confidence=raw_confidence,
            symbol=signal.symbol,
            action=final_action,
            sector=thesis.sector if thesis else "",
            regime=mkt.get("regime", "unknown"),
        )
        if confidence < self._min_confidence:
            logger.debug("Confidence %.2f below threshold for %s", confidence, signal.symbol)
            return None

        if final_action in ("buy", "add") and confidence < self._min_buy_confidence:
            logger.debug("Buy confidence %.2f below buy threshold for %s", confidence, signal.symbol)
            return None

        # Sector concentration check
        signal_sector = (thesis.sector if thesis else "") or signal.metadata.get("sector", "")
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
                        signal_sector, sector_pct * 100, signal.symbol,
                        self._max_sector_pct * 100,
                    )
                    return None

        # Position sizing
        shares, risk_notes = self._size_position(
            signal=signal,
            action=final_action,
            portfolio=portfolio,
            available_cash=available_cash,
            price=mkt.get("current_price", signal.metadata.get("entry_price")),
            consecutive_losses=consecutive_losses,
        )

        if shares == 0 and final_action in ("buy", "add"):
            return None

        # A-share constraint check (Phase 6)
        total_value = available_cash + sum(
            p.get("market_value", 0) for p in portfolio
        )
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
            f" [校准: {raw_confidence:.0%}→{confidence:.0%}]"
            if abs(raw_confidence - confidence) > 0.01
            else ""
        )
        reasoning_chain = [
            f"信号来源: {signal.source} ({signal.reason})",
            f"辩论结果: 多方{bull_score:.2f} vs 空方{bear_score:.2f}",
            f"裁决: {final_action} (置信度{confidence:.0%}{cal_note})",
            f"T+1约束: {ashare_assessment.board_type}板 ±{ashare_assessment.price_limit_pct:.0f}% "
            f"隔夜最大损失{overnight_risk:.1%}",
        ]
        if thesis:
            reasoning_chain.insert(0, f"投资论点: {thesis.thesis_text[:100]}")
        if risk_notes:
            reasoning_chain.append(f"风险提示: {'; '.join(risk_notes)}")

        return TradeProposal(
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
        )

    def _handle_critical(
        self,
        signal: AggregatedSignal,
        portfolio: list[dict[str, Any]],
        available_cash: float,
    ) -> TradeProposal | None:
        """Handle CRITICAL signals (stop-loss, circuit breaker) — no debate."""
        held = next(
            (p for p in portfolio if p.get("symbol") == signal.symbol), None
        )
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
    ) -> dict[str, Any]:
        """Run bull/bear debate via DebateEngine."""
        if self._debate_engine is None:
            return {
                "bull_score": signal.confidence * 0.6,
                "bear_score": (1 - signal.confidence) * 0.6,
                "reasoning": signal.reason,
                "risk_veto": False,
                "final_action": signal.direction.value.lower(),
                "verdict": {
                    "win_probability": signal.confidence,
                    "risk_reward_ratio": 1.5,
                    "stop_loss_pct": -3.0,
                    "take_profit_pct": 5.0,
                },
            }

        # Enrich market_data with thesis info
        data = dict(market_data)
        if thesis:
            data["macro_score"] = data.get("macro_score", 0)
            data["t_plus_1_risk"] = True

        record = self._debate_engine.run_debate(
            symbol=signal.symbol,
            name=signal.name,
            trigger=f"{signal.source}: {signal.reason}",
            market_data=data,
        )

        return record.to_dict()

    def _size_position(
        self,
        signal: AggregatedSignal,
        action: str,
        portfolio: list[dict[str, Any]],
        available_cash: float,
        price: float | None,
        consecutive_losses: int = 0,
    ) -> tuple[int, list[str]]:
        """Calculate position size in shares (100-lot) using Kelly criterion.

        Uses PositionSizer (Kelly + vol-scaling) for buy/add sizing, with
        consecutive loss penalty and existing position cap applied on top.
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

        total_value = available_cash + sum(
            p.get("market_value", 0) for p in portfolio
        )
        existing_value = sum(
            p.get("market_value", 0)
            for p in portfolio
            if p.get("symbol") == signal.symbol
        )

        # Check existing position cap
        max_allocation = total_value * self._max_position_pct
        remaining = min(max_allocation - existing_value, available_cash)

        if remaining <= 0:
            risk_notes.append(
                f"仓位已达上限({self._max_position_pct:.0%})"
            )
            return 0, risk_notes

        # Consecutive loss penalty
        if consecutive_losses >= self._consecutive_loss_threshold:
            remaining *= self._consecutive_loss_factor
            risk_notes.append(
                f"连续亏损{consecutive_losses}次，仓位减半"
            )

        # Kelly + vol-scaling via PositionSizer
        # Map signal confidence to win_rate, use signal metadata for returns
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
        total_value = available_cash + sum(
            p.get("market_value", 0) for p in portfolio
        )
        if total_value <= 0:
            return {}

        trade_value = shares * price if price else 0
        existing_value = sum(
            p.get("market_value", 0)
            for p in portfolio
            if p.get("symbol") == symbol
        )

        if action in ("buy", "add"):
            new_value = existing_value + trade_value
        elif action in ("sell", "reduce"):
            new_value = max(0, existing_value - trade_value)
        else:
            new_value = existing_value

        weight_after = new_value / total_value if total_value > 0 else 0
        position_count = len(portfolio) + (1 if action == "buy" and existing_value == 0 else 0)

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
