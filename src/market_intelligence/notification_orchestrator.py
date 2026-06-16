"""Intelligent notification routing for the v20.0 Market Intelligence pipeline.

Wraps ``NotificationDispatcher`` with phase-awareness, risk gating,
cooldown deduplication, and quiet-mode support.  Every routing decision
is recorded in ``NotificationLog`` for audit and stats.

Pipeline:
    signal → phase gate → risk overlay block → cooldown check
    → push-decision logic → dispatch (URGENT) or queue (DIGEST)
    → log

Part of v20.0 Market Intelligence Phase 3.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from src.web.schemas.market_signal import PushDecision, RiskLevel

if TYPE_CHECKING:
    from src.market_intelligence.notification_log import NotificationLog
    from src.market_intelligence.risk_overlay import RiskOverlayEngine
    from src.web.schemas.market_signal import MarketSignal
    from src.web.services.notification_dispatcher import NotificationDispatcher

logger = logging.getLogger(__name__)


class NotificationOrchestrator:
    """Route MarketSignals through the notification pipeline.

    Combines phase gating, risk blocking, cooldown deduplication,
    and push-decision logic into a single ``process()`` call.

    Usage::

        orchestrator = NotificationOrchestrator(
            dispatcher=dispatcher,
            phase_engine=phase_engine,
            risk_overlay=risk_overlay,
            notification_log=notification_log,
        )
        result = orchestrator.process(signal, portfolio_context)
    """

    def __init__(
        self,
        dispatcher: NotificationDispatcher | None = None,
        phase_engine: Any = None,
        risk_overlay: RiskOverlayEngine | None = None,
        notification_log: NotificationLog | None = None,
        cooldown_seconds: int = 300,
    ) -> None:
        self._dispatcher = dispatcher
        self._phase_engine = phase_engine
        self._risk_overlay = risk_overlay
        self._notification_log = notification_log
        self._cooldown_seconds = cooldown_seconds

        # In-memory cooldown tracker: "{asset}:{signal_type}" -> last_push_epoch
        self._cooldown_map: dict[str, float] = {}

        # Quiet mode: all signals become DIGEST
        self._quiet_mode = False

        # Stats counters
        self._stats: dict[str, int] = {
            "total": 0,
            "URGENT": 0,
            "DIGEST": 0,
            "BLOCK": 0,
            "SUPPRESS": 0,
        }

        logger.info(
            "NotificationOrchestrator initialized (cooldown=%ds, quiet=%s)",
            self._cooldown_seconds,
            self._quiet_mode,
        )

    # ------------------------------------------------------------------
    # Main pipeline
    # ------------------------------------------------------------------

    def process(
        self,
        signal: MarketSignal,
        portfolio_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Route a signal through the orchestration pipeline.

        Pipeline:
        1. Check phase_engine.is_signal_allowed() -- if not, SUPPRESS
        2. Check risk_overlay.should_block() -- if yes, BLOCK
        3. Check cooldown -- if in cooldown, SUPPRESS
        4. Determine push decision based on signal urgency + phase config
        5. If URGENT -> dispatch immediately via dispatcher
        6. If DIGEST -> queue for batch (just log; actual batch handled by Celery)
        7. Log decision to notification_log

        Returns:
            Dict with: signal_id, push_decision, dispatched, reason.
        """
        self._stats["total"] += 1
        dispatched = False
        dispatch_result: str | None = None
        reason = ""

        signal_type_str = signal.signal_type.value
        phase_str = signal.phase.value

        # 1. Phase gate
        if self._phase_engine is not None:
            try:
                if not self._phase_engine.is_signal_allowed(signal):
                    reason = f"Signal type {signal_type_str} not allowed in phase {phase_str}"
                    return self._finalize(
                        signal,
                        PushDecision.SUPPRESS,
                        dispatched,
                        dispatch_result,
                        reason,
                    )
            except Exception:
                logger.warning(
                    "PhaseEngine.is_signal_allowed() failed; proceeding", exc_info=True
                )

        # 2. Risk overlay block
        if self._risk_overlay is not None:
            try:
                if self._risk_overlay.should_block(signal):
                    reason = (
                        f"Blocked by risk overlay: risk_level={signal.risk_level.value} "
                        f"confidence={signal.confidence_score:.0f}"
                    )
                    return self._finalize(
                        signal, PushDecision.BLOCK, dispatched, dispatch_result, reason
                    )
            except Exception:
                logger.warning(
                    "RiskOverlayEngine.should_block() failed; proceeding", exc_info=True
                )

        # 3. Cooldown check
        if self._is_in_cooldown(signal):
            reason = f"In cooldown for {self._cooldown_key(signal)}"
            return self._finalize(
                signal, PushDecision.SUPPRESS, dispatched, dispatch_result, reason
            )

        # 4. Determine push decision
        decision = self._determine_decision(signal)

        # 5. Quiet mode override
        if self._quiet_mode and decision == PushDecision.URGENT:
            decision = PushDecision.DIGEST
            reason = "Quiet mode active; downgraded URGENT to DIGEST"

        # 6. Execute decision
        if decision == PushDecision.URGENT:
            dispatched, dispatch_result = self._dispatch(signal)
            if not reason:
                reason = "Urgent dispatch"
        elif decision == PushDecision.DIGEST:
            if not reason:
                reason = "Queued for digest batch"

        # 7. Update cooldown
        self._update_cooldown(signal)

        return self._finalize(signal, decision, dispatched, dispatch_result, reason)

    # ------------------------------------------------------------------
    # Push decision logic
    # ------------------------------------------------------------------

    def _determine_decision(self, signal: MarketSignal) -> PushDecision:
        """Determine the push decision for a signal.

        URGENT when:
        - risk_level == EXTREME (always urgent for critical alerts), OR
        - confidence_score >= 70 AND current phase has urgency_boost=True

        DIGEST: everything else.
        """
        # EXTREME risk is always urgent
        if signal.risk_level == RiskLevel.EXTREME:
            return PushDecision.URGENT

        # High confidence + phase urgency boost
        if signal.confidence_score >= 70 and self._phase_has_urgency_boost(signal):
            return PushDecision.URGENT

        return PushDecision.DIGEST

    def _phase_has_urgency_boost(self, signal: MarketSignal) -> bool:
        """Check whether the current phase has urgency_boost enabled."""
        if self._phase_engine is None:
            return False
        try:
            phase_config = self._phase_engine.get_phase_config(signal.phase.value)
            return phase_config.get("urgency_boost", False) if phase_config else False
        except Exception:
            logger.warning(
                "Failed to get phase config for urgency_boost", exc_info=True
            )
            return False

    # ------------------------------------------------------------------
    # Cooldown
    # ------------------------------------------------------------------

    @staticmethod
    def _cooldown_key(signal: MarketSignal) -> str:
        """Build the cooldown deduplication key."""
        # Use first asset if available; fallback to "GLOBAL"
        asset = signal.assets[0] if signal.assets else "GLOBAL"
        return f"{asset}:{signal.signal_type.value}"

    def _is_in_cooldown(self, signal: MarketSignal) -> bool:
        """Return True if this asset+signal_type was recently pushed."""
        key = self._cooldown_key(signal)
        last_push = self._cooldown_map.get(key)
        if last_push is None:
            return False
        return (time.monotonic() - last_push) < self._cooldown_seconds

    def _update_cooldown(self, signal: MarketSignal) -> None:
        """Record the current time for this asset+signal_type cooldown."""
        key = self._cooldown_key(signal)
        self._cooldown_map[key] = time.monotonic()

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, signal: MarketSignal) -> tuple[bool, str]:
        """Dispatch a signal via NotificationDispatcher.

        Returns:
            (dispatched_bool, result_string)
        """
        if self._dispatcher is None:
            logger.warning(
                "No dispatcher configured; skipping dispatch for %s", signal.signal_id
            )
            return False, "no_dispatcher"

        try:
            # Map risk level to severity
            severity = _risk_level_to_severity(signal.risk_level)

            result = self._dispatcher.dispatch(
                event_type=signal.signal_type.value,
                title=signal.summary_short,
                message=signal.summary_detailed or signal.summary_short,
                severity=severity,
            )
            dispatched_count = result.get("dispatched", 0)
            if dispatched_count > 0:
                return True, "ok"
            return True, "no_channels"
        except Exception as exc:
            logger.warning("Dispatch failed for signal %s: %s", signal.signal_id, exc)
            return False, f"error: {exc}"

    # ------------------------------------------------------------------
    # Finalize + log
    # ------------------------------------------------------------------

    def _finalize(
        self,
        signal: MarketSignal,
        decision: PushDecision,
        dispatched: bool,
        dispatch_result: str | None,
        reason: str,
    ) -> dict[str, Any]:
        """Record the decision and return the result dict."""
        self._stats[decision.value] += 1

        # Log to NotificationLog
        if self._notification_log is not None:
            try:
                self._notification_log.log(
                    signal_id=signal.signal_id,
                    signal_type=signal.signal_type.value,
                    push_decision=decision.value,
                    phase=signal.phase.value,
                    confidence_score=signal.confidence_score,
                    risk_level=signal.risk_level.value,
                    dispatched=dispatched,
                    dispatch_result=dispatch_result,
                    reason=reason,
                )
            except Exception:
                logger.warning("Failed to write to notification log", exc_info=True)

        logger.info(
            "Signal %s -> %s (dispatched=%s, reason=%s)",
            signal.signal_id,
            decision.value,
            dispatched,
            reason,
        )

        return {
            "signal_id": signal.signal_id,
            "push_decision": decision.value,
            "dispatched": dispatched,
            "reason": reason,
        }

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return orchestration stats: total processed, by decision type."""
        return dict(self._stats)

    def set_quiet_mode(self, enabled: bool) -> None:
        """Enable/disable quiet mode (all signals become DIGEST)."""
        self._quiet_mode = enabled
        logger.info("Quiet mode %s", "enabled" if enabled else "disabled")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _risk_level_to_severity(risk_level: RiskLevel) -> str:
    """Map RiskLevel enum to dispatcher severity string."""
    mapping = {
        RiskLevel.LOW: "info",
        RiskLevel.MODERATE: "info",
        RiskLevel.ELEVATED: "warning",
        RiskLevel.EXTREME: "critical",
    }
    return mapping.get(risk_level, "info")
