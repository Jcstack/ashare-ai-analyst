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
from zoneinfo import ZoneInfo

from src.agent_loop.confidence_calibrator import ConfidenceCalibrator
from src.agent_loop.models import (
    AggregatedSignal,
    CycleResult,
    CycleState,
    SignalDirection,
    TradeProposal,
    UrgencyTier,
)
from src.agent_loop.outcome_tracker import OutcomeTracker
from src.agent_loop.sentiment_cycle import (
    SentimentCycleDetector,
    SentimentPhase,
    SentimentSignals,
)

logger = logging.getLogger(__name__)

_CST = ZoneInfo("Asia/Shanghai")

# ---------------------------------------------------------------------------
# Emotion gate defaults (overridden by config/trading_loop.yaml)
# ---------------------------------------------------------------------------

_DEFAULT_EMOTION_GATES: dict[str, str] = {
    "ebb": "no_trade",
    "freezing": "small_position",
    "ignition": "normal",
    "climax": "cautious",
    "acceleration": "aggressive",
}

_DEFAULT_GATE_MODES: dict[str, dict] = {
    "no_trade": {
        "max_position_pct": 0.0,
        "max_single_stock_pct": 0.0,
        "stop_loss_multiplier": 0.5,
        "allow_new_buys": False,
        "force_clear": True,
    },
    "small_position": {
        "max_position_pct": 0.10,
        "max_single_stock_pct": 0.05,
        "stop_loss_multiplier": 0.7,
        "allow_new_buys": True,
        "force_clear": False,
    },
    "normal": {
        "max_position_pct": 0.50,
        "max_single_stock_pct": 0.10,
        "stop_loss_multiplier": 1.0,
        "allow_new_buys": True,
        "force_clear": False,
    },
    "cautious": {
        "max_position_pct": 0.30,
        "max_single_stock_pct": 0.08,
        "stop_loss_multiplier": 0.8,
        "allow_new_buys": True,
        "force_clear": False,
    },
    "aggressive": {
        "max_position_pct": 0.80,
        "max_single_stock_pct": 0.15,
        "stop_loss_multiplier": 1.0,
        "allow_new_buys": True,
        "force_clear": False,
    },
}


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
        reflexivity_detector: Any = None,
        sentiment_cycle_detector: Any = None,
        sector_correlation_monitor: Any = None,
        mtf_engine: Any = None,
        minute_bar_fetcher: Any = None,
        leader_detector: Any = None,
        calibrator: ConfidenceCalibrator | None = None,
        action_queue_service: Any = None,
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
        self._reflexivity = reflexivity_detector
        self._sentiment_cycle = sentiment_cycle_detector
        self._sector_corr = sector_correlation_monitor
        self._mtf = mtf_engine
        self._minute_bar = minute_bar_fetcher
        self._leader_detector = leader_detector
        self._calibrator = calibrator
        self._action_queue = action_queue_service
        self._outcome_tracker: OutcomeTracker | None = None
        self._price_fetcher: Any = None  # async (symbol, date_str) -> float|None

        cfg = config or {}
        self._min_confidence = cfg.get("min_confidence_to_propose", 0.6)
        self._decision_log: list[dict[str, Any]] = []
        self._last_sentiment_phase: str | None = None  # Track for regime change events

        # Emotion gate config
        self._emotion_gates: dict[str, str] = cfg.get(
            "emotion_gates", _DEFAULT_EMOTION_GATES
        )
        self._gate_modes: dict[str, dict] = cfg.get("gate_modes", _DEFAULT_GATE_MODES)
        self._consecutive_loss_stop: int = cfg.get("consecutive_loss_stop", 3)
        self._ebb_force_clear: bool = cfg.get("ebb_force_clear", True)
        self._max_loss_per_trade_pct: float = cfg.get("max_loss_per_trade_pct", 0.03)

        logger.info("AutonomousTradingLoop initialized")

    def set_outcome_tracker(
        self,
        tracker: OutcomeTracker,
        price_fetcher: Any = None,
    ) -> None:
        """Inject outcome tracker and optional async price fetcher."""
        self._outcome_tracker = tracker
        self._price_fetcher = price_fetcher
        logger.info("OutcomeTracker wired into trading loop")

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

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    async def run_cycle_via_director(self, director: Any) -> CycleResult:
        """Run OODA cycle using InvestmentDirector's 7-team pipeline.

        Reuses the trading loop's SENSE phase to build CycleState, then
        delegates ORIENT/DECIDE to the director's coordinate_cycle()
        (sentinel -> analyst -> strategist -> risk -> trader -> reviewer
        -> messenger), and finishes with ACT and LEARN.

        Args:
            director: An InvestmentDirector instance.

        Returns:
            CycleResult with proposals from the director pipeline.
        """
        cycle_id = str(uuid.uuid4())[:8]
        start = time.monotonic()
        errors: list[str] = []
        proposals: list[TradeProposal] = []
        outcomes_checked = 0

        logger.info("=== OODA Cycle %s START (director mode) ===", cycle_id)

        try:
            # ── SENSE ── (reuse existing infrastructure)
            state = await self._sense(cycle_id)

            # ── EMOTION GATE (hard check before director pipeline) ──
            phase, gate_mode, force_clear = self._apply_emotion_gate(
                cycle_id, state.positions
            )

            # Consecutive loss gate
            if state.consecutive_losses >= self._consecutive_loss_stop:
                logger.warning(
                    "HARD GATE [%s]: %d consecutive losses >= %d — no trading",
                    cycle_id,
                    state.consecutive_losses,
                    self._consecutive_loss_stop,
                )
                gate_mode = self._gate_modes.get("no_trade", gate_mode)
                if not force_clear and state.positions:
                    force_clear = self._build_force_clear_proposals(
                        state.positions, "连续亏损"
                    )

            # Force clear: short-circuit with sell proposals only
            if force_clear:
                proposals = force_clear
                await self._act(proposals)
                duration = time.monotonic() - start
                return CycleResult(
                    cycle_id=cycle_id,
                    timestamp=datetime.now(UTC),
                    duration_seconds=round(duration, 2),
                    signals_processed=0,
                    proposals_generated=proposals,
                    errors=[
                        f"EMOTION GATE: {phase} — force clear {len(proposals)} positions"
                    ],
                )

            # No-trade gate without positions: skip
            if not gate_mode.get("allow_new_buys", True) and not state.positions:
                logger.info(
                    "EMOTION GATE [%s]: no_trade mode, no positions — skipping director cycle",
                    cycle_id,
                )
                duration = time.monotonic() - start
                return CycleResult(
                    cycle_id=cycle_id,
                    timestamp=datetime.now(UTC),
                    duration_seconds=round(duration, 2),
                    signals_processed=0,
                    proposals_generated=[],
                    errors=[f"EMOTION GATE: {phase} — no trading allowed"],
                )

            # ── ORIENT + DECIDE via Director ──
            proposals = await director.coordinate_cycle(state)

            # Gate: filter out buy proposals when emotion phase forbids them
            if not gate_mode.get("allow_new_buys", True):
                blocked = [p for p in proposals if p.action in ("buy", "add")]
                proposals = [p for p in proposals if p.action not in ("buy", "add")]
                if blocked:
                    logger.info(
                        "EMOTION GATE [%s]: blocked %d buy proposals from director (phase=%s)",
                        cycle_id,
                        len(blocked),
                        phase,
                    )

            # ── RECORD ── track proposals in OutcomeTracker
            if self._outcome_tracker and proposals:
                for proposal in proposals:
                    # Build a minimal signal for tracking
                    direction_map = {
                        "buy": SignalDirection.BUY,
                        "sell": SignalDirection.SELL,
                        "hold": SignalDirection.HOLD,
                        "reduce": SignalDirection.REDUCE,
                        "add": SignalDirection.ADD,
                    }
                    synthetic_signal = AggregatedSignal(
                        symbol=proposal.symbol,
                        name=proposal.name,
                        direction=direction_map.get(
                            proposal.action, SignalDirection.HOLD
                        ),
                        source="director",
                        confidence=proposal.confidence,
                        urgency=UrgencyTier.NORMAL,
                        reason=proposal.debate_summary or "director proposal",
                    )
                    try:
                        await self._outcome_tracker.record_signal(
                            synthetic_signal, proposal
                        )
                    except Exception as exc:
                        logger.warning(
                            "Failed to record director proposal in OutcomeTracker: %s",
                            exc,
                        )

            # ── ACT ── (reuse existing push infrastructure)
            await self._act(proposals)

            # ── LEARN ── (reuse existing outcome checking)
            outcomes_checked = await self._learn()

        except Exception as exc:
            err = f"Director cycle error: {exc}"
            logger.error(err, exc_info=True)
            errors.append(err)

        duration = time.monotonic() - start

        result = CycleResult(
            cycle_id=cycle_id,
            timestamp=datetime.now(UTC),
            duration_seconds=round(duration, 2),
            signals_processed=len(state.pending_signals) if "state" in dir() else 0,
            proposals_generated=proposals,
            theses_updated=0,
            theses_invalidated=0,
            outcomes_checked=outcomes_checked,
            errors=errors,
        )

        logger.info(
            "=== OODA Cycle %s END (director) — %.1fs, %d proposals, %d errors ===",
            cycle_id,
            duration,
            len(proposals),
            len(errors),
        )

        return result

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

            # ── EMOTION GATE (hard check before any decisions) ──
            phase, gate_mode, force_clear = self._apply_emotion_gate(
                cycle_id, state.positions
            )

            # Consecutive loss gate
            if state.consecutive_losses >= self._consecutive_loss_stop:
                logger.warning(
                    "HARD GATE [%s]: %d consecutive losses >= %d — no trading",
                    cycle_id,
                    state.consecutive_losses,
                    self._consecutive_loss_stop,
                )
                gate_mode = self._gate_modes.get("no_trade", gate_mode)

            # Force clear: early return with only sell proposals
            if force_clear:
                proposals = force_clear
                await self._act(proposals)
                duration = time.monotonic() - start
                return CycleResult(
                    cycle_id=cycle_id,
                    timestamp=datetime.now(UTC),
                    duration_seconds=round(duration, 2),
                    signals_processed=0,
                    proposals_generated=proposals,
                    theses_updated=0,
                    theses_invalidated=0,
                    outcomes_checked=0,
                    errors=[
                        f"EMOTION GATE: {phase} — force clear {len(proposals)} positions"
                    ],
                )

            # No-trade gate without positions: skip entire cycle
            if not gate_mode.get("allow_new_buys", True) and not state.positions:
                logger.info(
                    "EMOTION GATE [%s]: no_trade mode, no positions — skipping cycle",
                    cycle_id,
                )
                duration = time.monotonic() - start
                return CycleResult(
                    cycle_id=cycle_id,
                    timestamp=datetime.now(UTC),
                    duration_seconds=round(duration, 2),
                    signals_processed=0,
                    proposals_generated=[],
                    errors=[f"EMOTION GATE: {phase} — no trading allowed"],
                )

            # ── ORIENT ──
            await self._orient(state)

            # ── DECIDE (with emotion gate filtering) ──
            signals = state.pending_signals
            allow_buys = gate_mode.get("allow_new_buys", True)

            for signal in signals:
                # Gate: block new buys when emotion phase forbids them
                if not allow_buys and signal.direction in (
                    SignalDirection.BUY,
                    SignalDirection.ADD,
                ):
                    logger.info(
                        "EMOTION GATE [%s]: blocked BUY signal for %s (phase=%s)",
                        cycle_id,
                        signal.symbol,
                        phase,
                    )
                    continue

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
                        # Gate: cap position size by emotion phase
                        max_single = gate_mode.get("max_single_stock_pct")
                        if max_single is not None and proposal.action == "buy":
                            total_capital = state.available_cash + sum(
                                p.get("market_value", 0) for p in state.positions
                            )
                            if total_capital > 0:
                                proposed_value = proposal.shares * (
                                    proposal.price_target or 0
                                )
                                max_value = total_capital * max_single
                                if proposed_value > max_value and proposal.price_target:
                                    capped_shares = (
                                        int(max_value / proposal.price_target / 100)
                                        * 100
                                    )  # Round to board lot
                                    if capped_shares <= 0:
                                        logger.info(
                                            "EMOTION GATE [%s]: position cap zeroed out %s buy",
                                            cycle_id,
                                            signal.symbol,
                                        )
                                        continue
                                    logger.info(
                                        "EMOTION GATE [%s]: capped %s from %d→%d shares (phase=%s, max=%.0f%%)",
                                        cycle_id,
                                        signal.symbol,
                                        proposal.shares,
                                        capped_shares,
                                        phase,
                                        max_single * 100,
                                    )
                                    proposal.shares = capped_shares

                        proposals.append(proposal)
                except Exception as exc:
                    err = f"Decision error for {signal.symbol}: {exc}"
                    logger.error(err, exc_info=True)
                    errors.append(err)

            # ── RECORD ── track every proposal in OutcomeTracker
            if self._outcome_tracker:
                for signal, proposal in _match_signals_to_proposals(signals, proposals):
                    try:
                        await self._outcome_tracker.record_signal(signal, proposal)
                    except Exception as exc:
                        logger.warning(
                            "Failed to record signal in OutcomeTracker: %s", exc
                        )

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
            signals_processed=len(state.pending_signals) if "state" in dir() else 0,
            proposals_generated=proposals,
            theses_updated=0,
            theses_invalidated=0,
            outcomes_checked=outcomes_checked,
            errors=errors,
        )

        logger.info(
            "=== OODA Cycle %s END — %.1fs, phase=%s, %d signals, %d proposals, %d errors ===",
            cycle_id,
            duration,
            phase,
            result.signals_processed,
            len(proposals),
            len(errors),
        )

        return result

    # ------------------------------------------------------------------
    # Emotion gate — hard trading restrictions by market phase
    # ------------------------------------------------------------------

    def _detect_emotion_phase(self) -> SentimentPhase | None:
        """Detect current market emotion phase via SentimentCycleDetector.

        Returns SentimentPhase or None if detection is unavailable.
        Uses the injected sentiment_cycle_detector or creates a temporary one.
        """
        try:
            detector = self._sentiment_cycle or SentimentCycleDetector()
            signals = self._gather_sentiment_signals()
            return detector.detect(signals)
        except Exception as exc:
            logger.warning("Emotion phase detection failed: %s", exc)
            return None

    def _get_gate_mode(self, phase: str) -> dict:
        """Map emotion phase to gate mode config.

        Returns the gate mode dict with position limits and flags.
        Falls back to 'cautious' for unknown phases (safe default).
        """
        mode_name = self._emotion_gates.get(phase, "cautious")
        return self._gate_modes.get(mode_name, self._gate_modes.get("cautious", {}))

    def _build_force_clear_proposals(
        self, positions: list[dict], phase_cn: str
    ) -> list[TradeProposal]:
        """Generate SELL proposals for all held positions (退潮 force clear)."""
        proposals: list[TradeProposal] = []
        for pos in positions:
            symbol = pos.get("symbol", "")
            name = pos.get("name", symbol)
            shares = int(pos.get("available_shares", pos.get("shares", 0)))
            if not symbol or shares <= 0:
                continue

            proposal = TradeProposal(
                proposal_id=f"ebb-clear-{symbol}-{str(uuid.uuid4())[:6]}",
                symbol=symbol,
                name=name,
                action="sell",
                shares=shares,
                confidence=0.95,
                price_target=pos.get("current_price"),
                stop_loss=None,
                take_profit=None,
                reasoning_chain=[
                    f"HARD GATE: 市场处于{phase_cn}阶段",
                    "情绪退潮期亏钱效应急剧放大，强制清仓保护本金",
                    "生存 > 盈利，退潮无多头",
                ],
                risk_notes=[f"{phase_cn}强制清仓 — 不可覆盖"],
                debate_summary=f"情绪硬门控: {phase_cn}阶段强制清仓",
            )
            proposals.append(proposal)

        return proposals

    def _apply_emotion_gate(
        self,
        cycle_id: str,
        positions: list[dict],
    ) -> tuple[str, dict, list[TradeProposal] | None]:
        """Check emotion gate and return (phase, gate_mode, force_clear_proposals).

        Returns:
            - phase: the English phase name (e.g. "ebb", "freezing")
            - gate_mode: dict with position limits and flags
            - force_clear_proposals: list of sell proposals if force_clear, else None
        """
        phase_result = self._detect_emotion_phase()
        if phase_result is None:
            # Detection failed — default to cautious
            logger.warning(
                "EMOTION GATE [%s]: detection unavailable, defaulting to cautious",
                cycle_id,
            )
            return "unknown", self._gate_modes.get("cautious", {}), None

        phase = phase_result.phase
        phase_cn = phase_result.phase_cn
        confidence = phase_result.confidence
        gate_mode = self._get_gate_mode(phase)
        mode_name = self._emotion_gates.get(phase, "cautious")

        logger.info(
            "EMOTION GATE [%s]: phase=%s(%s) conf=%.2f → mode=%s (max_pos=%.0f%%, buys=%s, clear=%s)",
            cycle_id,
            phase,
            phase_cn,
            confidence,
            mode_name,
            gate_mode.get("max_position_pct", 0) * 100,
            gate_mode.get("allow_new_buys", True),
            gate_mode.get("force_clear", False),
        )

        # Force clear in ebb phase
        force_proposals: list[TradeProposal] = []
        if gate_mode.get("force_clear") and self._ebb_force_clear and positions:
            force_proposals = self._build_force_clear_proposals(positions, phase_cn)
            logger.warning(
                "EMOTION GATE [%s]: %s — FORCE CLEAR %d positions",
                cycle_id,
                phase_cn,
                len(force_proposals),
            )
            return phase, gate_mode, force_proposals

        # Position-level enforcement: reduce positions that violate phase limits
        max_single = gate_mode.get("max_single_stock_pct", 1.0)
        if positions and max_single < 1.0 and confidence > 0.3:
            total_value = sum(float(p.get("market_value", 0)) for p in positions)
            if self._capital:
                try:
                    bal = self._capital.get_balance()
                    cash = float(bal) if isinstance(bal, (int, float)) else 0.0
                    total_value += cash
                except Exception:
                    pass

            if total_value > 0:
                for pos in positions:
                    sym = pos.get("symbol", "")
                    mv = float(pos.get("market_value", 0))
                    weight = mv / total_value
                    if weight > max_single * 1.2:  # 20% tolerance before forcing
                        excess_pct = weight - max_single
                        excess_shares = int(
                            excess_pct
                            / weight
                            * int(pos.get("available_shares", pos.get("shares", 0)))
                        )
                        # Round down to 100-share lot
                        excess_shares = (excess_shares // 100) * 100
                        if excess_shares >= 100:
                            proposal = TradeProposal(
                                proposal_id=f"gate-reduce-{sym}-{str(uuid.uuid4())[:6]}",
                                symbol=sym,
                                name=pos.get("name", sym),
                                action="reduce",
                                shares=excess_shares,
                                confidence=0.85,
                                price_target=pos.get("current_price"),
                                stop_loss=None,
                                take_profit=None,
                                reasoning_chain=[
                                    f"POSITION GATE: {sym} weight {weight:.0%} exceeds "
                                    f"{phase_cn} phase limit {max_single:.0%}",
                                    f"Reducing {excess_shares} shares to approach limit",
                                    "Position concentration violates regime risk rules",
                                ],
                                risk_notes=[
                                    f"{phase_cn}阶段单股上限{max_single:.0%}，当前{weight:.0%}"
                                ],
                                debate_summary=(
                                    f"持仓门控: {sym} 仓位{weight:.0%}超过"
                                    f"{phase_cn}阶段限制{max_single:.0%}"
                                ),
                            )
                            force_proposals.append(proposal)
                            logger.warning(
                                "POSITION GATE [%s]: %s weight=%.0f%% > limit=%.0f%% → reduce %d shares",
                                cycle_id,
                                sym,
                                weight * 100,
                                max_single * 100,
                                excess_shares,
                            )

        return phase, gate_mode, force_proposals if force_proposals else None

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

        # Available cash — CapitalService.get_balance() returns a float
        available_cash = 0.0
        if self._capital:
            try:
                bal = self._capital.get_balance()
                # get_balance() returns float; get_balance_info() returns CapitalBalance
                if isinstance(bal, (int, float)):
                    available_cash = float(bal)
                elif hasattr(bal, "available_cash"):
                    available_cash = float(bal.available_cash)
                elif hasattr(bal, "available"):
                    available_cash = float(bal.available)
                else:
                    available_cash = float(bal)
            except Exception as exc:
                logger.warning("Failed to fetch capital: %s", exc)

        # Market regime
        regime = "unknown"
        if self._regime:
            try:
                daily_returns = self._fetch_market_daily_returns()
                result = self._regime.detect(daily_returns)
                if hasattr(result, "current_regime"):
                    regime = result.current_regime.regime_label or "unknown"
                elif isinstance(result, dict):
                    regime = result.get("regime", "unknown")
                else:
                    regime = str(result)
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
                            thesis.symbol,
                            thesis.name,
                            change_pct=sl_result["change_pct"],
                            stop_loss_pct=sl_result["stop_loss_pct"],
                        )
                    elif self._check_thesis_invalidation(thesis, positions):
                        self._signal_agg.add_from_thesis_invalidation(
                            thesis.symbol, thesis.name, "论点失效条件触发"
                        )
            except Exception as exc:
                logger.warning("Failed to check thesis invalidations: %s", exc)

        # ── v52: Wire orphaned signal modules ──

        # Sentiment cycle → portfolio-wide signals
        if self._sentiment_cycle and self._signal_agg:
            try:
                from src.agent_loop.sentiment_cycle import SentimentSignals

                zt_count = self._get_limit_up_count()
                phase = self._sentiment_cycle.detect(
                    SentimentSignals(limit_up_count=zt_count)
                )
                if phase:
                    portfolio_syms = [
                        (p.get("symbol", ""), p.get("name", ""))
                        for p in positions
                        if p.get("symbol")
                    ]
                    self._signal_agg.add_from_sentiment_phase(phase, portfolio_syms)
                    logger.debug(
                        "SENSE: Sentiment phase '%s' (conf=%.2f)",
                        phase.phase,
                        phase.confidence,
                    )
                    # Publish regime change if phase changed (v50.0)
                    if phase.phase != self._last_sentiment_phase:
                        prev = self._last_sentiment_phase or "unknown"
                        self._last_sentiment_phase = phase.phase
                        try:
                            from src.event_bus.producers import publish_regime_change

                            publish_regime_change(
                                phase=phase.phase,
                                phase_cn=phase.phase_cn,
                                confidence=phase.confidence,
                                prev_phase=prev,
                            )
                        except Exception:
                            pass  # Never break the caller
            except Exception as exc:
                logger.warning("SENSE: Sentiment cycle collection failed: %s", exc)

        # Sector correlation → crisis/rotation signals
        if self._sector_corr and self._signal_agg:
            try:
                regime = self._sector_corr.detect()
                if regime and (regime.crisis_signal or regime.breaks):
                    # Build sector→symbols mapping from positions
                    sector_symbols = self._build_sector_symbols_map(positions)
                    self._signal_agg.add_from_sector_correlation(regime, sector_symbols)
                    logger.debug(
                        "SENSE: Sector correlation — %d breaks, crisis=%s",
                        regime.break_count,
                        regime.crisis_signal,
                    )
            except Exception as exc:
                logger.warning("SENSE: Sector correlation failed: %s", exc)

        # ── v54: Impact chain signals (intelligence → causal chain → trade) ──
        try:
            from src.intelligence.impact_engine import EventImpactEngine
            from src.intelligence.agents.event_state_tracker import (
                get_event_state_tracker,
            )

            tracker = get_event_state_tracker()
            active_events = tracker.get_active_events()

            if active_events:
                impact_engine = EventImpactEngine()
                chain_signals: list[dict] = []
                for event in active_events:
                    state_val = (
                        event.state.value
                        if hasattr(event.state, "value")
                        else str(event.state)
                    )
                    if state_val not in (
                        "detected",
                        "developing",
                        "escalating",
                        "relapsed",
                    ):
                        continue
                    event_dict = {
                        "title": event.title,
                        "summary": getattr(event, "ai_summary", ""),
                        "confidence": getattr(event, "probability_holds", 0.5),
                        "sectors": getattr(event, "affected_sectors", []),
                        "event_id": event.event_id,
                        "event_type": getattr(event, "event_type", "unknown"),
                    }
                    try:
                        signals = impact_engine.process_event(event_dict)
                        chain_signals.extend(signals)
                    except Exception:
                        pass

                if chain_signals and self._signal_agg:
                    added = self._signal_agg.add_from_impact_chain(chain_signals)
                    logger.info(
                        "SENSE: Impact chains → %d signals from %d active events",
                        added,
                        len(active_events),
                    )
        except Exception as exc:
            logger.warning("SENSE: Impact chain signal collection failed: %s", exc)

        # Per-symbol: reflexivity + MTF (requires minute bars)
        if self._minute_bar and positions:
            for pos in positions:
                symbol = pos.get("symbol", "")
                name = pos.get("name", "")
                if not symbol:
                    continue

                bars = None
                try:
                    bars = await self._minute_bar.fetch(symbol)
                except Exception:
                    continue

                if bars is None or (hasattr(bars, "empty") and bars.empty):
                    continue

                # Reflexivity detection
                if self._reflexivity and self._signal_agg:
                    try:
                        result = self._reflexivity.detect(bars)
                        if result:
                            self._signal_agg.add_from_reflexivity(symbol, name, result)
                    except Exception as exc:
                        logger.debug("Reflexivity failed for %s: %s", symbol, exc)

                # MTF confidence boost (modifier, not standalone signal)
                if self._mtf and self._signal_agg:
                    try:
                        confirmation = self._mtf.analyze(bars, symbol)
                        if confirmation:
                            self._signal_agg.apply_mtf_boost(symbol, confirmation)
                    except Exception as exc:
                        logger.debug("MTF boost failed for %s: %s", symbol, exc)

        # ── UST: Leader detection (龙头扫描) ──
        await self._collect_leader_signals()

    async def _collect_leader_signals(self) -> None:
        """Scan limit-up pool, identify leaders, feed into signal aggregator."""
        if not self._leader_detector or not self._signal_agg:
            return

        try:
            from src.agent_loop.leader_detector import LeaderCandidate
            from src.data.fetcher import StockDataFetcher

            fetcher = StockDataFetcher()
            zt_df = fetcher.fetch_limit_up_pool()
            if zt_df is None or zt_df.empty:
                return

            # Count limit-ups per sector
            sector_counts: dict[str, int] = {}
            if "sector" in zt_df.columns:
                sector_counts = zt_df["sector"].value_counts().to_dict()

            candidates: list[LeaderCandidate] = []
            for _, row in zt_df.iterrows():
                sector = str(row.get("sector", row.get("industry", "")))
                candidates.append(
                    LeaderCandidate(
                        symbol=str(row.get("symbol", row.get("code", ""))),
                        name=str(row.get("name", "")),
                        sector=sector,
                        is_limit_up=True,
                        limit_up_time=str(row.get("limit_up_time", ""))
                        if row.get("limit_up_time")
                        else None,
                        seal_volume=float(row.get("seal_volume", 0)),
                        total_volume=float(
                            row.get("volume", row.get("total_volume", 0))
                        ),
                        consecutive_boards=int(row.get("consecutive_boards", 0)),
                        sector_limit_up_count=sector_counts.get(sector, 0),
                        turnover_rate=float(row.get("turnover_rate", 0)),
                    )
                )

            leaders = self._leader_detector.identify_leaders(candidates)
            added = 0
            for leader in leaders:
                sig = self._signal_agg.add_from_leader(leader)
                if sig:
                    added += 1

            if added:
                logger.info(
                    "SENSE: 龙头扫描 — %d leaders from %d candidates",
                    added,
                    len(candidates),
                )

        except Exception as exc:
            logger.warning("SENSE: Leader detection failed: %s", exc)

    def _get_limit_up_count(self) -> int:
        """Fetch current limit-up count for sentiment signals."""
        try:
            from src.data.fetcher import StockDataFetcher

            zt_df = StockDataFetcher().fetch_limit_up_pool()
            if zt_df is not None and not zt_df.empty:
                return len(zt_df)
        except Exception:
            pass
        return 0

    def _gather_sentiment_signals(self) -> "SentimentSignals":
        """Gather all 5 sentiment signals for cycle detection.

        Collects: limit_up_count, max_consecutive_board, limit_down_count,
        volume_change_pct, northbound_net_flow. Each is best-effort;
        missing signals reduce confidence but don't block detection.
        """
        from src.agent_loop.sentiment_cycle import SentimentSignals

        signals = SentimentSignals()

        # 1. Limit-up count + max consecutive boards
        try:
            from src.data.fetcher import StockDataFetcher

            zt_df = StockDataFetcher().fetch_limit_up_pool()
            if zt_df is not None and not zt_df.empty:
                signals.limit_up_count = len(zt_df)
                for col in ("consecutive", "连板数"):
                    if col in zt_df.columns:
                        signals.max_consecutive_board = int(zt_df[col].max())
                        break
        except Exception as exc:
            logger.debug("Sentiment: limit_up fetch failed: %s", exc)

        # 2. Limit-down count
        try:
            import akshare as ak

            dt_df = ak.stock_zt_pool_dtgc_em(date=None)
            signals.limit_down_count = (
                len(dt_df) if dt_df is not None and not dt_df.empty else 0
            )
        except Exception as exc:
            logger.debug("Sentiment: limit_down fetch failed: %s", exc)

        # 3. Volume change % (market volume vs 20-day average)
        try:
            if self._global_market:
                snapshot = self._global_market.get_cached_snapshot()
                if snapshot:
                    for idx_name in ("上证指数", "sh000001", "000001"):
                        sh = snapshot.get(idx_name, {})
                        if sh:
                            vol = sh.get("volume", 0) or sh.get("amount", 0)
                            avg = sh.get("avg_volume_20d", 0)
                            if avg and avg > 0:
                                signals.volume_change_pct = (vol - avg) / avg * 100
                            break
        except Exception as exc:
            logger.debug("Sentiment: volume fetch failed: %s", exc)

        # 4. Northbound net flow (亿元)
        try:
            from src.data.macro_flow_fetcher import MacroFlowFetcher

            flow = MacroFlowFetcher().fetch_northbound_today()
            if flow and isinstance(flow, dict):
                signals.northbound_net_flow = flow.get("net_flow") or flow.get("net", 0)
        except Exception as exc:
            logger.debug("Sentiment: northbound fetch failed: %s", exc)

        avail = sum(
            x is not None and x != 0
            for x in [
                signals.limit_up_count,
                signals.max_consecutive_board,
                signals.limit_down_count,
                signals.volume_change_pct,
                signals.northbound_net_flow,
            ]
        )
        logger.info(
            "Sentiment signals: %d/5 avail (zt=%d board=%s dt=%s vol=%s north=%s)",
            avail,
            signals.limit_up_count,
            signals.max_consecutive_board,
            signals.limit_down_count,
            f"{signals.volume_change_pct:.0f}%"
            if signals.volume_change_pct is not None
            else "-",
            f"{signals.northbound_net_flow:.1f}"
            if signals.northbound_net_flow is not None
            else "-",
        )
        return signals

    def _check_stop_loss(self, thesis: Any, positions: list[dict]) -> dict | None:
        """Check if stop-loss price is breached. Returns change info or None."""
        if not getattr(thesis, "stop_loss_pct", None):
            return None

        held = next((p for p in positions if p.get("symbol") == thesis.symbol), None)
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

        held = next((p for p in positions if p.get("symbol") == thesis.symbol), None)
        if not held:
            return False

        # Future: check thesis.invalidation_conditions against market data
        return False

    def _build_sector_symbols_map(self, positions: list[dict]) -> dict[str, list[str]]:
        """Build sector -> [symbol] mapping from portfolio positions.

        Uses position metadata for sector info. Falls back to empty mapping
        if sector info is not available.
        """
        sector_map: dict[str, list[str]] = {}
        for pos in positions:
            symbol = pos.get("symbol", "")
            sector = pos.get("sector", pos.get("industry", ""))
            if symbol and sector:
                sector_map.setdefault(sector, []).append(symbol)
        return sector_map

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
            self._decision_log.append(
                {
                    "proposal_id": proposal.proposal_id,
                    "symbol": proposal.symbol,
                    "action": proposal.action,
                    "shares": proposal.shares,
                    "confidence": proposal.confidence,
                    "timestamp": proposal.created_at.isoformat(),
                }
            )

            # Push to Discord via Redis pub/sub
            self._push_notification("trade_signal", proposal.to_dict())
            logger.info(
                "ACT: Pushed %s signal for %s (%d shares, %.0f%% confidence)",
                proposal.action,
                proposal.symbol,
                proposal.shares,
                proposal.confidence * 100,
            )

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
                        "ACT: Pushed %s to action queue for %s",
                        proposal.action,
                        proposal.symbol,
                    )
                except Exception as exc:
                    logger.error("Failed to push proposal to action queue: %s", exc)

    # ------------------------------------------------------------------
    # LEARN — check past outcomes
    # ------------------------------------------------------------------

    async def _learn(self) -> int:
        """Check past decision outcomes and update calibration (Phase 5).

        1. Evaluate T+1/T+3/T+5 outcomes via OutcomeTracker
        2. Feed completed outcomes into ConfidenceCalibrator
        3. Log accuracy stats from DecisionLog
        """
        checked = 0

        # --- OutcomeTracker: evaluate pending signals ---
        if self._outcome_tracker:
            try:
                outcomes = await self._outcome_tracker.evaluate_pending(
                    price_fetcher=self._price_fetcher,
                )
                if outcomes:
                    logger.info(
                        "LEARN: OutcomeTracker evaluated %d outcomes", len(outcomes)
                    )
                    checked += len(outcomes)

                    # Feed outcomes into calibrator
                    if self._calibrator:
                        try:
                            self._calibrator.update_from_outcomes(outcomes)
                            logger.info(
                                "LEARN: Fed %d outcomes into ConfidenceCalibrator",
                                len(outcomes),
                            )
                        except Exception as exc:
                            logger.warning("Calibrator outcome update failed: %s", exc)
            except Exception as exc:
                logger.warning("OutcomeTracker evaluation failed: %s", exc)

        # --- DecisionLog: accuracy stats ---
        if self._decision_log_store:
            try:
                stats = self._decision_log_store.get_accuracy_stats(lookback_days=30)
                if stats.get("total_decisions", 0) > 0:
                    accuracy = stats.get("direction_accuracy")
                    accuracy_str = (
                        f"{accuracy * 100:.0f}%" if accuracy is not None else "N/A"
                    )
                    avg_t3 = stats.get("avg_t3_return")
                    avg_t3_str = f"{avg_t3:.2f}%" if avg_t3 is not None else "N/A"
                    logger.info(
                        "LEARN: %d decisions, %s direction accuracy, avg T+3 return %s",
                        stats.get("total_decisions", 0),
                        accuracy_str,
                        avg_t3_str,
                    )
                    checked += stats.get("total_decisions", 0)
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
    # Event-driven mode
    # ------------------------------------------------------------------

    async def run_event_driven(self, event_bus: Any, timeout: int = 300) -> CycleResult:
        """Run event-driven micro-OODA cycles using v50.0 Redis Streams event bus.

        Subscribes to event bus streams (events:market, events:news,
        events:signal) via consumer groups and runs targeted micro-cycles
        when events arrive for specific symbols.

        Args:
            event_bus: An EventBus instance (from src.event_bus.bus).
            timeout: Max seconds to wait for events before falling back to
                     a full scheduled cycle.

        Returns:
            CycleResult from either event-driven micro-cycles or the
            fallback scheduled cycle.
        """
        import asyncio
        import json as json_mod

        cycle_id = f"evt-{str(uuid.uuid4())[:8]}"
        start = time.monotonic()
        errors: list[str] = []
        proposals: list[TradeProposal] = []
        signals_processed = 0

        logger.info(
            "=== Event-driven mode %s START (timeout=%ds) ===", cycle_id, timeout
        )

        # v50.0 event bus streams
        streams = [
            "events:market",
            "events:news",
            "events:signal",
        ]

        # Collect events from the bus via a bounded subscribe read
        all_events: list[dict] = []

        def _collect(stream: str, entry_id: str, parsed: dict) -> None:
            data_raw = parsed.get("data", {})
            # parsed["data"] is already a dict from EventBus._deserialize,
            # but handle the case where it might still be a JSON string.
            if isinstance(data_raw, str):
                try:
                    data = json_mod.loads(data_raw)
                except (json_mod.JSONDecodeError, TypeError):
                    data = {"raw": data_raw}
            else:
                data = data_raw
            all_events.append(
                {
                    "stream": stream,
                    "entry_id": entry_id,
                    "type": parsed.get("type", "unknown"),
                    "data": data,
                }
            )

        try:
            event_bus.subscribe(
                streams=streams,
                consumer_group="trading_loop",
                consumer_name="ooda-worker",
                callback=_collect,
                batch_size=50,
                block_ms=1000,
                max_iterations=1,
            )
        except Exception as exc:
            logger.debug("Event bus subscribe failed: %s", exc)

        if not all_events:
            logger.info(
                "Event-driven mode: no recent events, falling back to scheduled cycle"
            )
            return await self.run_cycle()

        logger.info(
            "Event-driven mode: %d events found across %d streams",
            len(all_events),
            len(streams),
        )

        try:
            # Extract unique symbols from events for targeted micro-cycles
            target_symbols: set[str] = set()
            for evt in all_events:
                symbol = evt["data"].get("symbol")
                if symbol:
                    target_symbols.add(symbol)

            if not target_symbols:
                logger.info(
                    "Event-driven mode: no symbol-specific events, running full cycle"
                )
                return await self.run_cycle()

            # Run micro-OODA for each target symbol
            for symbol in target_symbols:
                try:
                    proposal = await self._micro_ooda(cycle_id, symbol, all_events)
                    if proposal:
                        proposals.append(proposal)
                    signals_processed += 1
                except Exception as exc:
                    err = f"Micro-OODA error for {symbol}: {exc}"
                    logger.error(err, exc_info=True)
                    errors.append(err)

            # ACT on any proposals generated
            if proposals:
                await self._act(proposals)

        except asyncio.TimeoutError:
            logger.info("Event-driven mode: timed out, falling back to scheduled cycle")
            return await self.run_cycle()
        except Exception as exc:
            err = f"Event-driven cycle error: {exc}"
            logger.error(err, exc_info=True)
            errors.append(err)

        duration = time.monotonic() - start

        result = CycleResult(
            cycle_id=cycle_id,
            timestamp=datetime.now(UTC),
            duration_seconds=round(duration, 2),
            signals_processed=signals_processed,
            proposals_generated=proposals,
            theses_updated=0,
            theses_invalidated=0,
            outcomes_checked=0,
            errors=errors,
        )

        logger.info(
            "=== Event-driven %s END — %.1fs, %d symbols, %d proposals, %d errors ===",
            cycle_id,
            duration,
            signals_processed,
            len(proposals),
            len(errors),
        )

        return result

    async def _micro_ooda(
        self,
        cycle_id: str,
        symbol: str,
        events: list[dict],
    ) -> TradeProposal | None:
        """Run a targeted micro-OODA cycle for a single symbol.

        Checks if the event-driven signal is actionable, evaluates via
        the decision pipeline, and returns a proposal if warranted.

        Args:
            cycle_id: Parent cycle ID for logging.
            symbol: Target stock symbol.
            events: All recent bus events (dicts with stream/type/data keys,
                    filtered by symbol internally).

        Returns:
            TradeProposal if the signal is actionable, None otherwise.
        """
        # Filter events for this symbol
        symbol_events = [e for e in events if e["data"].get("symbol") == symbol]
        if not symbol_events:
            return None

        # Determine signal direction from event data
        from src.agent_loop.models import AggregatedSignal, SignalDirection, UrgencyTier

        # Pick the highest-severity event (fall back to z_score / 5 if no severity)
        def _event_severity(e: dict) -> float:
            sev = e["data"].get("severity", 0)
            if sev:
                return float(sev)
            z = e["data"].get("z_score", 0)
            return float(z) / 5.0 if z else 0.0

        best_event = max(symbol_events, key=_event_severity)
        event_data = best_event["data"]

        # Map event type to signal direction
        # "type" lives on the envelope (from the bus), not inside data
        event_type = best_event.get("type", "")
        direction_str = event_data.get("direction", "")
        if event_type in (
            "PRICE_SPIKE",
            "PATTERN_DETECTED",
            "SIGNAL_DETECTED",
            "price_spike",
            "pattern_detected",
            "signal_detected",
        ):
            if direction_str in ("bearish", "down"):
                direction = SignalDirection.SELL
            else:
                direction = SignalDirection.BUY
        elif event_type in ("POLICY_EVENT", "policy_event"):
            rotation_signal = event_data.get("rotation_signal", "")
            if rotation_signal in ("exit", "reduce"):
                direction = SignalDirection.SELL
            else:
                direction = SignalDirection.HOLD
        else:
            direction = SignalDirection.HOLD

        if direction == SignalDirection.HOLD:
            logger.debug("Micro-OODA %s/%s: HOLD signal, skipping", cycle_id, symbol)
            return None

        # Build a synthetic AggregatedSignal from event data
        severity = _event_severity(best_event)
        if severity == 0.0:
            severity = 0.5
        signal = AggregatedSignal(
            symbol=symbol,
            name=event_data.get("name", symbol),
            direction=direction,
            source=f"event_bus:{event_type}",
            confidence=severity,
            urgency=UrgencyTier.HIGH if severity >= 0.7 else UrgencyTier.NORMAL,
            reason=event_data.get("description", f"Event: {event_type}"),
            metadata=event_data,
        )

        # Skip if no decision pipeline available
        if not self._pipeline:
            logger.debug("Micro-OODA %s/%s: no decision pipeline", cycle_id, symbol)
            return None

        # Get portfolio context
        positions = []
        available_cash = 0.0
        if self._portfolio:
            try:
                positions = self._portfolio.list_positions()
            except Exception:
                pass
        if self._capital:
            try:
                bal = self._capital.get_balance()
                available_cash = bal.available if hasattr(bal, "available") else 0.0
            except Exception:
                pass

        thesis = self._get_thesis(symbol)

        proposal = await self._pipeline.evaluate(
            signal=signal,
            portfolio=positions,
            available_cash=available_cash,
            daily_pnl_pct=self._estimate_daily_pnl(positions),
            consecutive_losses=self._count_consecutive_losses(),
            thesis=thesis,
            market_data=event_data,
        )

        if proposal:
            logger.info(
                "Micro-OODA %s/%s: generated %s proposal (confidence=%.0f%%)",
                cycle_id,
                symbol,
                proposal.action,
                proposal.confidence * 100,
            )

        return proposal

    # ------------------------------------------------------------------
    # Scheduled routines
    # ------------------------------------------------------------------

    async def run_premarket(self) -> str:
        """Morning prep — 08:00. Returns morning briefing text."""
        logger.info("=== Pre-market briefing START ===")

        briefing: dict[str, Any] = {
            "date": datetime.now(_CST).strftime("%Y-%m-%d"),
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
                    briefing["global_summary"] = (
                        " | ".join(parts) if parts else "暂无数据"
                    )
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

        # Push briefing via Redis pub/sub
        self._push_notification("morning_briefing", briefing)

        logger.info("=== Pre-market briefing END ===")
        return str(briefing)

    async def run_postmarket(self) -> str:
        """Evening review — 15:30. Returns evening summary text."""
        logger.info("=== Post-market review START ===")

        review: dict[str, Any] = {
            "date": datetime.now(_CST).strftime("%Y-%m-%d"),
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
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        today_decisions = [
            d for d in self._decision_log if d.get("timestamp", "").startswith(today)
        ]
        review["trades"] = today_decisions

        # Post-market outcome evaluation (T+1/T+3/T+5)
        if self._outcome_tracker:
            try:
                outcomes = await self._outcome_tracker.evaluate_pending(
                    price_fetcher=self._price_fetcher,
                )
                if outcomes:
                    logger.info(
                        "Post-market: evaluated %d signal outcomes", len(outcomes)
                    )
                    # Feed into calibrator for next-day adjustments
                    if self._calibrator:
                        self._calibrator.update_from_outcomes(outcomes)
                    review["outcomes_evaluated"] = len(outcomes)
            except Exception as exc:
                logger.warning("Post-market outcome check failed: %s", exc)

        # Push review via Redis pub/sub
        self._push_notification("evening_review", review)

        logger.info("=== Post-market review END ===")
        return str(review)

    async def run_fast_scan(self) -> dict[str, Any]:
        """5-minute fast scan: stop-loss, thesis invalidation, black swan, leaders, sentiment.

        Lightweight — no LLM debate. Only processes CRITICAL signals.
        Returns a summary dict.
        """
        cycle_id = f"fast-{str(uuid.uuid4())[:6]}"
        start = time.monotonic()
        critical_count = 0
        proposals: list[TradeProposal] = []
        errors: list[str] = []

        logger.info("=== Fast Scan %s START ===", cycle_id)

        try:
            # Gather positions
            positions: list[dict[str, Any]] = []
            if self._portfolio:
                try:
                    positions = self._portfolio.list_positions()
                except Exception as exc:
                    errors.append(f"Portfolio: {exc}")

            if self._signal_agg:
                self._signal_agg.clear()

            # Stop-loss + thesis invalidation
            if self._thesis_store and self._signal_agg:
                try:
                    for thesis in self._thesis_store.get_active():
                        sl_result = self._check_stop_loss(thesis, positions)
                        if sl_result:
                            self._signal_agg.add_from_stop_loss(
                                thesis.symbol,
                                thesis.name,
                                change_pct=sl_result["change_pct"],
                                stop_loss_pct=sl_result["stop_loss_pct"],
                            )
                        elif self._check_thesis_invalidation(thesis, positions):
                            self._signal_agg.add_from_thesis_invalidation(
                                thesis.symbol, thesis.name, "论点失效条件触发"
                            )
                except Exception as exc:
                    errors.append(f"Thesis check: {exc}")

            # Black swan
            if self._black_swan and self._global_market and self._signal_agg:
                try:
                    snapshot = self._global_market.get_cached_snapshot()
                    if snapshot:
                        alert = self._black_swan.scan(snapshot)
                        if alert and alert.get("alert_level") != "normal":
                            self._signal_agg.add_from_black_swan(alert)
                except Exception as exc:
                    errors.append(f"Black swan: {exc}")

            # Leader detection
            await self._collect_leader_signals()

            # Sentiment cycle
            if self._sentiment_cycle and self._signal_agg:
                try:
                    signals = self._gather_sentiment_signals()
                    phase = self._sentiment_cycle.detect(signals)
                    if phase:
                        portfolio_syms = [
                            (p.get("symbol", ""), p.get("name", ""))
                            for p in positions
                            if p.get("symbol")
                        ]
                        self._signal_agg.add_from_sentiment_phase(phase, portfolio_syms)
                except Exception as exc:
                    errors.append(f"Sentiment: {exc}")

            # Only process CRITICAL signals (no debate)
            if self._signal_agg:
                ranked = self._signal_agg.rank_and_deduplicate()
                # Publish all ranked signals to event bus
                try:
                    from src.event_bus.producers import publish_signal_detected

                    for signal in ranked:
                        publish_signal_detected(
                            symbol=signal.symbol,
                            direction=signal.direction,
                            source=f"fast_scan:{signal.source}",
                            confidence=signal.confidence,
                            reason=signal.reason[:200] if signal.reason else "",
                        )
                except Exception as exc:
                    logger.warning("Event bus publish failed: %s", exc)

                for signal in ranked:
                    if signal.urgency != UrgencyTier.CRITICAL:
                        continue
                    critical_count += 1
                    if self._pipeline:
                        try:
                            available_cash = 0.0
                            if self._capital:
                                try:
                                    available_cash = self._capital.available_cash
                                except Exception:
                                    pass
                            proposal = await self._pipeline.evaluate(
                                signal=signal,
                                portfolio=positions,
                                available_cash=available_cash,
                            )
                            if proposal:
                                proposals.append(proposal)
                        except Exception as exc:
                            errors.append(f"Pipeline {signal.symbol}: {exc}")

            # Push critical proposals
            if proposals:
                await self._act(proposals)

        except Exception as exc:
            errors.append(f"Fast scan: {exc}")
            logger.error("Fast scan failed: %s", exc, exc_info=True)

        duration = time.monotonic() - start
        logger.info(
            "=== Fast Scan %s END — %.1fs, %d critical, %d proposals ===",
            cycle_id,
            duration,
            critical_count,
            len(proposals),
        )

        return {
            "cycle_id": cycle_id,
            "duration_seconds": round(duration, 2),
            "critical_signals": critical_count,
            "proposals": len(proposals),
            "errors": errors,
        }

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

    # Map trading loop notification types to AssistantPushCog types
    _ASSISTANT_TYPE_MAP: dict[str, str] = {
        "trade_signal": "buy_signal",
        "morning_briefing": "pre_market",
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
                if notification_type == "trade_signal" and isinstance(data, dict):
                    action = data.get("action", "")
                    if action in ("sell", "reduce"):
                        assistant_type = "sell_signal"

                assistant_payload = self._build_assistant_payload(
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

    @staticmethod
    def _build_assistant_payload(
        assistant_type: str, notification_type: str, data: Any
    ) -> dict[str, Any]:
        """Translate TradeProposal/briefing dict to AssistantPushCog embed schema.

        AssistantPushCog's embed builder expects: type, title, summary,
        action_advice, risk_note, symbol, confidence.  TradeProposal.to_dict()
        has different field names.  This bridges the gap.
        """
        raw = dict(data) if isinstance(data, dict) else {"data": data}
        payload: dict[str, Any] = {"type": assistant_type}

        # Pass through common fields
        payload["symbol"] = raw.get("symbol", "")
        payload["name"] = raw.get("name", "")
        payload["confidence"] = raw.get("confidence", 0)

        if notification_type == "trade_signal":
            action = raw.get("action", "unknown")
            name = raw.get("name", raw.get("symbol", ""))
            symbol = raw.get("symbol", "")
            action_cn = {
                "buy": "建议买入",
                "sell": "建议卖出",
                "add": "建议加仓",
                "reduce": "建议减仓",
                "hold": "建议持有",
            }.get(action, action)
            payload["title"] = f"{action_cn} {name}({symbol})"

            # summary from debate_summary
            payload["summary"] = raw.get("debate_summary", "")

            # action_advice from stop_loss / price_target / shares
            advice_parts = []
            if raw.get("shares"):
                advice_parts.append(f"数量: {raw['shares']}股")
            if raw.get("stop_loss"):
                advice_parts.append(f"止损: ¥{raw['stop_loss']}")
            if raw.get("price_target"):
                advice_parts.append(f"目标: ¥{raw['price_target']}")
            contingencies = raw.get("contingencies", [])
            if contingencies:
                for c in contingencies[:2]:
                    cond = c.get("condition", "") if isinstance(c, dict) else ""
                    act = c.get("action", "") if isinstance(c, dict) else ""
                    if cond:
                        advice_parts.append(f"应急: {cond} → {act}")
            payload["action_advice"] = (
                " | ".join(advice_parts) if advice_parts else None
            )

            # risk_note from risk_notes list
            risk_notes = raw.get("risk_notes", [])
            payload["risk_note"] = "; ".join(risk_notes) if risk_notes else None

        elif notification_type == "risk_alert":
            payload["title"] = raw.get("title", "风险警报")
            payload["summary"] = raw.get("message", raw.get("summary", ""))
            payload["risk_note"] = raw.get("alert_message", raw.get("risk_note", ""))

        else:
            # Briefings (morning_briefing, evening_review) — pass through
            payload["title"] = raw.get("title", notification_type)
            payload["summary"] = raw.get("summary", "")
            # Merge remaining data for embed builder
            for k, v in raw.items():
                if k not in payload:
                    payload[k] = v

        return payload

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


def _match_signals_to_proposals(
    signals: list[Any],
    proposals: list[TradeProposal],
) -> list[tuple[Any, TradeProposal | None]]:
    """Match each signal to its resulting proposal (if any) for tracking.

    Returns list of (signal, proposal_or_None) pairs. Every signal is
    included; unmatched signals get None as proposal.
    """
    proposal_by_symbol: dict[str, TradeProposal] = {}
    for p in proposals:
        proposal_by_symbol[p.symbol] = p

    result: list[tuple[Any, TradeProposal | None]] = []
    for signal in signals:
        sym = getattr(signal, "symbol", "")
        result.append((signal, proposal_by_symbol.get(sym)))
    return result
