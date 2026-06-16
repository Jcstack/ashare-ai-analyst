"""Extreme market conference — auto-triggered multi-agent emergency evaluation.

When the market exhibits abnormal behaviour (single-stock crash, VIX spike,
macro shock) this module convenes analyst + sentiment + risk + regime agents
for an emergency assessment with veto-based risk control.

Trigger conditions (any one suffices):
- Any tracked stock intraday amplitude > 5 %
- 3-day cumulative return > ±10 %
- VIX > 25 (global panic)
- MacroRadarService emits an EXTREME-level signal
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Trigger thresholds ────────────────────────────────────
INTRADAY_AMPLITUDE_PCT = 5.0
CUMULATIVE_3D_PCT = 10.0
VIX_PANIC_THRESHOLD = 25.0


@dataclass
class ConferenceResult:
    """Output of an extreme-market conference session."""

    trigger_reason: str
    symbols: list[str]
    convened: bool = False
    # Per-agent verdicts (agent_name → dict with signal/score/notes)
    verdicts: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Final decision after voting + veto
    action: str = "hold"
    confidence: float = 0.0
    risk_veto: bool = False
    report_text: str = ""


class ExtremeMarketConference:
    """Convenes multi-agent emergency evaluation for extreme market events.

    Args:
        signal_store: SignalStore for querying recent signals.
        global_market_fetcher: For VIX data.
        stock_service: For recent price data of tracked symbols.
    """

    def __init__(
        self,
        signal_store: Any | None = None,
        global_market_fetcher: Any | None = None,
        stock_service: Any | None = None,
    ) -> None:
        self._signal_store = signal_store
        self._global_fetcher = global_market_fetcher
        self._stock_service = stock_service

    def should_convene(self, portfolio_symbols: list[str]) -> tuple[bool, str]:
        """Check if any trigger condition is met.

        Returns:
            ``(should_convene, reason)`` tuple.
        """
        # Check 1: VIX panic
        reason = self._check_vix_panic()
        if reason:
            return True, reason

        # Check 2: Single-stock amplitude
        reason = self._check_stock_amplitude(portfolio_symbols)
        if reason:
            return True, reason

        # Check 3: 3-day cumulative return
        reason = self._check_cumulative_return(portfolio_symbols)
        if reason:
            return True, reason

        # Check 4: Extreme macro signal
        reason = self._check_extreme_macro_signal()
        if reason:
            return True, reason

        return False, ""

    def convene(
        self,
        trigger_reason: str,
        symbols: list[str],
    ) -> ConferenceResult:
        """Convene the conference (synchronous, rule-based stub).

        The actual multi-agent pipeline execution is delegated to
        ``collaborative_decision`` in ``config/pipelines.yaml``.
        This method records the trigger and returns a stub result
        that the calling Celery task can enrich with real pipeline
        output.

        Args:
            trigger_reason: Human-readable reason the conference was triggered.
            symbols: Symbols to evaluate.

        Returns:
            ConferenceResult with trigger metadata populated.
        """
        logger.warning(
            "ExtremeMarketConference convened — reason: %s, symbols: %s",
            trigger_reason,
            symbols,
        )

        return ConferenceResult(
            trigger_reason=trigger_reason,
            symbols=symbols,
            convened=True,
        )

    # ------------------------------------------------------------------
    # Trigger checks
    # ------------------------------------------------------------------

    def _check_vix_panic(self) -> str:
        """Return a reason string if VIX exceeds panic threshold."""
        if self._global_fetcher is None:
            return ""
        try:
            snapshot = self._global_fetcher.fetch_global_snapshot()
            vix = snapshot.get("vix", {}).get("price")
            if vix is not None and float(vix) > VIX_PANIC_THRESHOLD:
                return f"VIX={vix:.1f} > {VIX_PANIC_THRESHOLD} (全球恐慌)"
        except Exception as exc:
            logger.debug("VIX check failed: %s", exc)
        return ""

    def _check_stock_amplitude(self, symbols: list[str]) -> str:
        """Return a reason string if any symbol has excessive intraday range."""
        if self._stock_service is None or not symbols:
            return ""
        try:
            for symbol in symbols[:20]:  # cap to avoid slow scans
                try:
                    data = self._stock_service.get_realtime_data(symbol)
                    if data is None:
                        continue
                    high = float(data.get("high", 0) or 0)
                    low = float(data.get("low", 0) or 0)
                    prev_close = float(data.get("prev_close", 0) or 0)
                    if prev_close <= 0:
                        continue
                    amplitude = (high - low) / prev_close * 100
                    if amplitude > INTRADAY_AMPLITUDE_PCT:
                        return (
                            f"{symbol} 日内振幅 {amplitude:.1f}% "
                            f"> {INTRADAY_AMPLITUDE_PCT}%"
                        )
                except Exception:
                    continue
        except Exception as exc:
            logger.debug("Stock amplitude check failed: %s", exc)
        return ""

    def _check_cumulative_return(self, symbols: list[str]) -> str:
        """Return a reason string if any symbol has extreme 3-day return."""
        if self._stock_service is None or not symbols:
            return ""
        try:
            for symbol in symbols[:20]:
                try:
                    df = self._stock_service.get_stock_data(symbol)
                    if df is None or len(df) < 4:
                        continue
                    closes = df["close"].tail(4)
                    if closes.iloc[0] <= 0:
                        continue
                    ret_3d = (closes.iloc[-1] / closes.iloc[0] - 1) * 100
                    if abs(ret_3d) > CUMULATIVE_3D_PCT:
                        return (
                            f"{symbol} 3日累计涨跌 {ret_3d:+.1f}% "
                            f"> ±{CUMULATIVE_3D_PCT}%"
                        )
                except Exception:
                    continue
        except Exception as exc:
            logger.debug("Cumulative return check failed: %s", exc)
        return ""

    def _check_extreme_macro_signal(self) -> str:
        """Return a reason string if a recent extreme macro signal exists."""
        if self._signal_store is None:
            return ""
        try:
            recent = self._signal_store.get_signals(
                signal_type="S8_MACRO_DRIVEN",
                limit=5,
                days=1,
            )
            for sig in recent:
                risk = sig.get("risk_level", "")
                if risk in ("CRITICAL", "EXTREME"):
                    return f"宏观极端信号: {sig.get('summary_short', 'unknown')}"
        except Exception as exc:
            logger.debug("Extreme macro signal check failed: %s", exc)
        return ""
