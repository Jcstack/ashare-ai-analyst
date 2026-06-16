"""Autonomous Trading Loop — the agent's heartbeat.

Runs a complete OODA cycle every 15 minutes during trading hours:
  SENSE  → gather portfolio, signals, regime, capital, theses
  ORIENT → intel chain analysis, thesis evaluation, macro cascade
  DECIDE → for each actionable signal, run decision pipeline
  ACT    → push proposals to Discord, record in decision log
  LEARN  → check past decision outcomes, update calibration
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from src.agent_loop.confidence_calibrator import ConfidenceCalibrator
from src.agent_loop.models import (
    CycleResult,
    CycleState,
    TradeProposal,
)

logger = logging.getLogger(__name__)


class AutonomousTradingLoop:
    """The agent's core OODA cycle service."""

    def __init__(
        self,
        thesis_store: Any = None,
        signal_aggregator: Any = None,
        decision_pipeline: Any = None,
        portfolio_store: Any = None,
        capital_service: Any = None,
        notification_dispatcher: Any = None,
        regime_detector: Any = None,
        debate_engine: Any = None,
        recommendation_service: Any = None,
        signal_store: Any = None,
        rotation_engine: Any = None,
        black_swan_detector: Any = None,
        global_market_fetcher: Any = None,
        position_macro_mapper: Any = None,
        decision_log: Any = None,
        intel_bridge: Any = None,
        calibrator: ConfidenceCalibrator | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._thesis_store = thesis_store
        self._signal_agg = signal_aggregator
        self._pipeline = decision_pipeline
        self._portfolio = portfolio_store
        self._capital = capital_service
        self._notifier = notification_dispatcher
        self._regime = regime_detector
        self._debate = debate_engine
        self._rec_service = recommendation_service
        self._signal_store = signal_store
        self._rotation = rotation_engine
        self._black_swan = black_swan_detector
        self._decision_log_store = decision_log
        self._intel_bridge = intel_bridge
        self._global_market = global_market_fetcher
        self._macro_mapper = position_macro_mapper
        self._calibrator = calibrator

        cfg = config or {}
        self._min_confidence = cfg.get("min_confidence_to_propose", 0.6)
        self._decision_log: list[dict[str, Any]] = []
        logger.info("AutonomousTradingLoop initialized")

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    async def run_cycle(self) -> CycleResult:
        """Single OODA cycle — called by Celery every 15 min during trading."""
        cycle_id = str(uuid.uuid4())[:8]
        start = time.monotonic()
        errors: list[str] = []
        proposals: list[TradeProposal] = []

        logger.info("=== OODA Cycle %s START ===", cycle_id)

        try:
            # ── SENSE ──
            state = await self._sense(cycle_id)

            # ── ORIENT ──
            await self._orient(state)

            # ── DECIDE ──
            signals = state.pending_signals
            for signal in signals:
                try:
                    thesis = self._get_thesis(signal.symbol)
                    proposal = await self._pipeline.evaluate(
                        signal=signal,
                        portfolio=state.positions,
                        available_cash=state.available_cash,
                        daily_pnl_pct=state.daily_pnl_pct,
                        consecutive_losses=state.consecutive_losses,
                        thesis=thesis,
                        market_data=signal.metadata,
                    )
                    if proposal:
                        proposals.append(proposal)
                except Exception as exc:
                    err = f"Decision error for {signal.symbol}: {exc}"
                    logger.error(err, exc_info=True)
                    errors.append(err)

            # ── ACT ──
            await self._act(proposals)

            # ── LEARN ──
            outcomes_checked = await self._learn()

        except Exception as exc:
            err = f"Cycle error: {exc}"
            logger.error(err, exc_info=True)
            errors.append(err)
            outcomes_checked = 0

        duration = time.monotonic() - start

        result = CycleResult(
            cycle_id=cycle_id,
            timestamp=datetime.now(UTC),
            duration_seconds=round(duration, 2),
            signals_processed=len(state.pending_signals) if 'state' in dir() else 0,
            proposals_generated=proposals,
            theses_updated=0,
            theses_invalidated=0,
            outcomes_checked=outcomes_checked,
            errors=errors,
        )

        logger.info(
            "=== OODA Cycle %s END — %.1fs, %d signals, %d proposals, %d errors ===",
            cycle_id,
            duration,
            result.signals_processed,
            len(proposals),
            len(errors),
        )

        return result

    # ------------------------------------------------------------------
    # SENSE — gather current state
    # ------------------------------------------------------------------

    async def _sense(self, cycle_id: str) -> CycleState:
        """Gather portfolio, signals, regime, capital, theses."""
        # Portfolio positions
        positions = []
        if self._portfolio:
            try:
                positions = self._portfolio.list_positions()
            except Exception as exc:
                logger.warning("Failed to fetch positions: %s", exc)

        # Available cash
        available_cash = 0.0
        if self._capital:
            try:
                bal = self._capital.get_balance()
                available_cash = bal.available if hasattr(bal, "available") else 0.0
            except Exception as exc:
                logger.warning("Failed to fetch capital: %s", exc)

        # Market regime
        regime = "unknown"
        if self._regime:
            try:
                result = self._regime.detect()
                regime = result.get("regime", "unknown") if isinstance(result, dict) else str(result)
            except Exception as exc:
                logger.warning("Failed to detect regime: %s", exc)

        # Active theses
        active_theses = []
        if self._thesis_store:
            try:
                active_theses = self._thesis_store.get_active()
            except Exception as exc:
                logger.warning("Failed to fetch theses: %s", exc)

        # Collect signals from all sources
        if self._signal_agg:
            self._signal_agg.clear()
            await self._collect_signals(positions)
            pending_signals = self._signal_agg.rank_and_deduplicate()
        else:
            pending_signals = []

        # Apply regime-specific strategy params (Phase 5 — FR-ALL002)
        if self._calibrator and regime != "unknown":
            regime_params = self._calibrator.get_regime_params(regime)
            logger.info("SENSE: Regime '%s' params: %s", regime, regime_params)

        # Daily P&L (approximate)
        daily_pnl_pct = self._estimate_daily_pnl(positions)
        consecutive_losses = self._count_consecutive_losses()

        state = CycleState(
            cycle_id=cycle_id,
            positions=positions,
            available_cash=available_cash,
            regime=regime,
            pending_signals=pending_signals,
            active_theses=active_theses,
            daily_pnl_pct=daily_pnl_pct,
            consecutive_losses=consecutive_losses,
        )

        logger.info(
            "SENSE: %d positions, ¥%.0f cash, %s regime, %d signals, %d theses",
            len(positions),
            available_cash,
            regime,
            len(pending_signals),
            len(active_theses),
        )

        return state

    async def _collect_signals(self, positions: list[dict]) -> None:
        """Collect signals from all sources into aggregator."""
        if not self._signal_agg:
            return

        # 1. Recommendations
        if self._rec_service:
            try:
                recs = self._rec_service.get_latest_recommendations()
                if isinstance(recs, list):
                    for rec in recs[:10]:
                        self._signal_agg.add_from_recommendation(rec)
            except Exception as exc:
                logger.warning("Failed to collect recommendation signals: %s", exc)

        # 2. Technical signals from signal store
        if self._signal_store:
            try:
                recent = self._signal_store.get_recent(hours=1)
                if isinstance(recent, list):
                    for sig in recent:
                        self._signal_agg.add_from_technical(
                            sig if isinstance(sig, dict) else sig.to_dict()
                        )
            except Exception as exc:
                logger.warning("Failed to collect technical signals: %s", exc)

        # 3. Rotation signals
        if self._rotation and positions:
            try:
                from src.intelligence.position_macro_mapper import MacroEnvironment

                env = MacroEnvironment()
                if self._macro_mapper:
                    profiles = self._macro_mapper.analyze_portfolio(positions, env)
                    for p in profiles:
                        profile_dict = p.to_dict() if hasattr(p, "to_dict") else p
                        self._signal_agg.add_from_rotation(profile_dict)
            except Exception as exc:
                logger.warning("Failed to collect rotation signals: %s", exc)

        # 4. Black swan alerts
        if self._black_swan and self._global_market:
            try:
                snapshot = self._global_market.get_cached_snapshot()
                if snapshot:
                    alert = self._black_swan.scan(snapshot)
                    if alert and alert.get("alert_level") != "normal":
                        self._signal_agg.add_from_black_swan(alert)
            except Exception as exc:
                logger.warning("Failed to collect black swan signals: %s", exc)

        # 5. Thesis invalidation + stop-loss checks
        if self._thesis_store:
            try:
                for thesis in self._thesis_store.get_active():
                    sl_result = self._check_stop_loss(thesis, positions)
                    if sl_result:
                        # Stop-loss → CRITICAL sell (no debate)
                        self._signal_agg.add_from_stop_loss(
                            thesis.symbol, thesis.name,
                            change_pct=sl_result["change_pct"],
                            stop_loss_pct=sl_result["stop_loss_pct"],
                        )
                    elif self._check_thesis_invalidation(thesis, positions):
                        self._signal_agg.add_from_thesis_invalidation(
                            thesis.symbol, thesis.name, "论点失效条件触发"
                        )
            except Exception as exc:
                logger.warning("Failed to check thesis invalidations: %s", exc)

    def _check_stop_loss(self, thesis: Any, positions: list[dict]) -> dict | None:
        """Check if stop-loss price is breached. Returns change info or None."""
        if not getattr(thesis, "stop_loss_pct", None):
            return None

        held = next(
            (p for p in positions if p.get("symbol") == thesis.symbol), None
        )
        if not held:
            return None

        current_price = held.get("current_price", 0)
        avg_cost = held.get("avg_cost", 0)
        if not current_price or not avg_cost:
            return None

        change_pct = (current_price - avg_cost) / avg_cost
        stop_loss_pct = thesis.stop_loss_pct / 100
        if change_pct <= stop_loss_pct:
            return {"change_pct": change_pct, "stop_loss_pct": stop_loss_pct}
        return None

    def _check_thesis_invalidation(self, thesis: Any, positions: list[dict]) -> bool:
        """Check if any non-stop-loss invalidation conditions are met."""
        if not thesis.invalidation_conditions:
            return False

        held = next(
            (p for p in positions if p.get("symbol") == thesis.symbol), None
        )
        if not held:
            return False

        # Future: check thesis.invalidation_conditions against market data
        return False

    # ------------------------------------------------------------------
    # ORIENT — analyze context
    # ------------------------------------------------------------------

    async def _orient(self, state: CycleState) -> None:
        """Run intel chain analysis, thesis evaluation, macro cascade."""
        # Decay stale theses
        if self._thesis_store:
            try:
                decayed = self._thesis_store.decay_stale()
                if decayed:
                    logger.info("ORIENT: Decayed %d stale theses", decayed)
            except Exception as exc:
                logger.warning("Thesis decay failed: %s", exc)

        # Intel chain → thesis impact → signal generation
        if self._intel_bridge and self._signal_agg:
            try:
                impacts = self._intel_bridge.scan_and_evaluate(
                    positions=state.positions,
                    signal_aggregator=self._signal_agg,
                )
                if impacts:
                    logger.info("ORIENT: %d intel impacts detected", len(impacts))
            except Exception as exc:
                logger.warning("Intel bridge scan failed: %s", exc)

    # ------------------------------------------------------------------
    # ACT — push proposals to Discord
    # ------------------------------------------------------------------

    async def _act(self, proposals: list[TradeProposal]) -> None:
        """Push proposals to Discord and record in decision log."""
        for proposal in proposals:
            # Record in persistent decision log
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

            # In-memory log for session tracking
            self._decision_log.append({
                "proposal_id": proposal.proposal_id,
                "symbol": proposal.symbol,
                "action": proposal.action,
                "shares": proposal.shares,
                "confidence": proposal.confidence,
                "timestamp": proposal.created_at.isoformat(),
            })

            # Push to Discord via notification dispatcher
            if self._notifier:
                try:
                    self._notifier.dispatch(
                        notification_type="trade_signal",
                        data=proposal.to_dict(),
                    )
                    logger.info(
                        "ACT: Pushed %s signal for %s (%d shares, %.0f%% confidence)",
                        proposal.action,
                        proposal.symbol,
                        proposal.shares,
                        proposal.confidence * 100,
                    )
                except Exception as exc:
                    logger.error("Failed to push proposal to Discord: %s", exc)

    # ------------------------------------------------------------------
    # LEARN — check past outcomes
    # ------------------------------------------------------------------

    async def _learn(self) -> int:
        """Check past decision outcomes and update calibration (Phase 5)."""
        if not self._decision_log_store:
            return 0

        checked = 0
        try:
            stats = self._decision_log_store.get_accuracy_stats(lookback_days=30)
            if stats.get("total_decisions", 0) > 0:
                accuracy = stats.get("direction_accuracy")
                accuracy_str = f"{accuracy * 100:.0f}%" if accuracy is not None else "N/A"
                avg_t3 = stats.get("avg_t3_return")
                avg_t3_str = f"{avg_t3:.2f}%" if avg_t3 is not None else "N/A"
                logger.info(
                    "LEARN: %d decisions, %s direction accuracy, avg T+3 return %s",
                    stats.get("total_decisions", 0),
                    accuracy_str,
                    avg_t3_str,
                )
                checked = stats.get("total_decisions", 0)
        except Exception as exc:
            logger.warning("Learning stats failed: %s", exc)

        # Log calibration report
        if self._calibrator:
            try:
                report = self._calibrator.get_calibration_report()
                if report.get("calibration_active"):
                    logger.info(
                        "LEARN: Calibration active — overall accuracy %.0f%% (%d evaluated)",
                        (report.get("overall_accuracy", 0) or 0) * 100,
                        report.get("evaluated_decisions", 0),
                    )
            except Exception as exc:
                logger.debug("Calibration report failed: %s", exc)

        return checked

    # ------------------------------------------------------------------
    # Scheduled routines
    # ------------------------------------------------------------------

    async def run_premarket(self) -> str:
        """Morning prep — 08:00. Returns morning briefing text."""
        logger.info("=== Pre-market briefing START ===")

        briefing: dict[str, Any] = {
            "date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "global_summary": "",
            "macro_events": "",
            "thesis_status": "",
            "planned_actions": "",
            "key_levels": "",
        }

        # Global market overnight changes
        if self._global_market:
            try:
                snapshot = self._global_market.get_cached_snapshot()
                if snapshot:
                    indices = snapshot.get("indices", [])
                    parts = []
                    for idx in indices[:5]:
                        name = idx.get("name", "")
                        change = idx.get("change_pct", 0)
                        parts.append(f"{name} {change:+.2f}%")
                    briefing["global_summary"] = " | ".join(parts) if parts else "暂无数据"
            except Exception:
                briefing["global_summary"] = "数据获取失败"

        # Thesis status
        if self._thesis_store:
            try:
                theses = self._thesis_store.get_active()
                if theses:
                    parts = [
                        f"{t.symbol}({t.name}): {t.direction} 信心{t.conviction:.0%}"
                        for t in theses[:5]
                    ]
                    briefing["thesis_status"] = "\n".join(parts)
                else:
                    briefing["thesis_status"] = "无活跃论点"
            except Exception:
                briefing["thesis_status"] = "获取失败"

        # Push briefing
        if self._notifier:
            try:
                self._notifier.dispatch(
                    notification_type="morning_briefing",
                    data=briefing,
                )
            except Exception as exc:
                logger.error("Failed to push morning briefing: %s", exc)

        logger.info("=== Pre-market briefing END ===")
        return str(briefing)

    async def run_postmarket(self) -> str:
        """Evening review — 15:30. Returns evening summary text."""
        logger.info("=== Post-market review START ===")

        review: dict[str, Any] = {
            "date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "daily_pnl": "",
            "trades": [],
            "thesis_updates": "",
            "intel_triggers": "",
            "outlook": "",
        }

        # Portfolio P&L
        if self._portfolio:
            try:
                positions = self._portfolio.list_positions()
                total_pnl = sum(p.get("unrealized_pnl", 0) for p in positions)
                review["daily_pnl"] = f"¥{total_pnl:,.2f}"
            except Exception:
                review["daily_pnl"] = "计算失败"

        # Today's proposals
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        today_decisions = [
            d for d in self._decision_log
            if d.get("timestamp", "").startswith(today)
        ]
        review["trades"] = today_decisions

        # Push review
        if self._notifier:
            try:
                self._notifier.dispatch(
                    notification_type="evening_review",
                    data=review,
                )
            except Exception as exc:
                logger.error("Failed to push evening review: %s", exc)

        logger.info("=== Post-market review END ===")
        return str(review)

    async def run_overnight(self) -> str:
        """Overnight research — 20:00. Deep thesis development."""
        logger.info("=== Overnight research START ===")

        # Decay stale theses
        if self._thesis_store:
            try:
                decayed = self._thesis_store.decay_stale()
                logger.info("Overnight: decayed %d stale theses", decayed)
            except Exception as exc:
                logger.warning("Overnight thesis decay failed: %s", exc)

        logger.info("=== Overnight research END ===")
        return "overnight_complete"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_thesis(self, symbol: str) -> Any:
        """Get active thesis for symbol."""
        if not self._thesis_store:
            return None
        try:
            return self._thesis_store.get(symbol)
        except Exception:
            return None

    def _estimate_daily_pnl(self, positions: list[dict]) -> float:
        """Rough daily P&L as fraction of portfolio."""
        if not positions:
            return 0.0
        total_value = sum(p.get("market_value", 0) for p in positions)
        daily_pnl = sum(p.get("daily_pnl", 0) for p in positions)
        if total_value <= 0:
            return 0.0
        return daily_pnl / total_value

    def _count_consecutive_losses(self) -> int:
        """Count recent consecutive losing decisions."""
        count = 0
        for d in reversed(self._decision_log):
            pnl = d.get("realized_pnl", None)
            if pnl is None:
                continue
            if pnl < 0:
                count += 1
            else:
                break
        return count
