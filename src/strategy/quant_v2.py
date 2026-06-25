"""Adapter strategy that drives the v2 quant stack through the backtest engine.

The v2 signal layer (:class:`~src.quant.signal_library.SignalLibrary` +
:class:`~src.quant.regime_detector.RegimeDetector`) produces a *single*
aggregated read of the market as-of the latest bar, whereas the backtest engine
(:class:`~src.backtest.engine.BacktestEngine`) needs a *per-bar* signal series.
The two were architecturally forked — the OODA agent loop never touched
``src/backtest/``. This adapter bridges them so the v2 stack can finally be
backtested out-of-sample (see ``ROADMAP.md`` P2.1).

For each bar ``i`` the adapter evaluates the v2 signals on the **expanding
window** ``df[:i+1]`` only — never on future bars — so the resulting equity
curve is free of look-ahead bias. Regime detection (the expensive HMM fit) is
recomputed every ``regime_stride`` bars and carried forward between, which keeps
the bar-by-bar pass tractable without leaking the future.

Simulation/research only — outputs are **not investment advice**.
"""

from __future__ import annotations

import pandas as pd

from src.quant.regime_detector import RegimeDetector
from src.quant.signal_library import SignalLibrary
from src.strategy.base import SIGNAL_BUY, SIGNAL_HOLD, SIGNAL_SELL, BaseStrategy
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Regime labels the detector emits for the three HMM states / vol buckets.
_BEAR_REGIMES = {"bear"}
_BULL_REGIMES = {"bull"}


class QuantSignalV2Strategy(BaseStrategy):
    """Wrap the v2 ``SignalLibrary`` (+ optional regime gate) as a strategy.

    Fusion logic per bar:

    1. ``SignalLibrary.evaluate`` on the expanding price/volume window yields a
       ``consensus`` (bullish / bearish / neutral) and a signed ``net_score``.
    2. The consensus maps to buy / sell / hold; ``|net_score|`` seeds strength.
    3. When ``use_regime`` is on, the current regime modulates the call: buys are
       vetoed in a bear regime, and strength is boosted when the regime confirms
       the signal (bull+buy / bear+sell) and damped when it contradicts.

    Args:
        config_path: Strategy YAML (passed to :class:`BaseStrategy`).
        min_history: Bars required before any non-hold signal may fire.
        use_regime: Whether to apply the regime gate/modulation.
        regime_stride: Recompute the regime every N bars (carried forward
            between recomputations to keep the pass O(N) HMM fits, not O(N²)).
    """

    def __init__(
        self,
        config_path: str = "strategy",
        *,
        min_history: int = 30,
        use_regime: bool = True,
        regime_stride: int = 5,
    ) -> None:
        super().__init__(config_path)
        self.min_history = max(2, int(min_history))
        self.use_regime = bool(use_regime)
        self.regime_stride = max(1, int(regime_stride))
        self._signal_lib = SignalLibrary()
        self._regime_detector = RegimeDetector() if use_regime else None

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Produce one signal row per input bar (no look-ahead)."""
        closes = df["close"].astype(float).tolist()
        volumes = (
            df["volume"].astype(float).tolist() if "volume" in df.columns else None
        )
        dates = df["date"].tolist()

        rows: list[dict] = []
        regime_label = "unknown"

        for i in range(len(df)):
            date = dates[i]

            if i + 1 < self.min_history:
                rows.append(
                    self._build_signal_row(date, SIGNAL_HOLD, 0.0, "热身期，样本不足")
                )
                continue

            window_closes = closes[: i + 1]
            window_volumes = volumes[: i + 1] if volumes is not None else None

            summary = self._signal_lib.evaluate(window_closes, window_volumes)

            if self.use_regime and i % self.regime_stride == 0:
                regime_label = self._detect_regime(window_closes)

            signal, strength, reason = self._fuse(summary, regime_label)
            rows.append(self._build_signal_row(date, signal, strength, reason))

        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _detect_regime(self, window_closes: list[float]) -> str:
        """Causally detect the current regime from the expanding window."""
        if self._regime_detector is None or len(window_closes) < 3:
            return "unknown"
        returns = pd.Series(window_closes).pct_change().dropna().tolist()
        if not returns:
            return "unknown"
        try:
            report = self._regime_detector.detect(returns)
            current = report.current_regime
            # Prefer the semantic HMM state; fall back to the label.
            return (current.hmm_state or current.regime_label or "unknown").lower()
        except Exception as exc:  # detector degrades to vol-percentile internally
            logger.debug("Regime detection skipped: %s", exc)
            return "unknown"

    def _fuse(self, summary, regime_label: str) -> tuple[int, float, str]:
        """Combine the signal consensus with the regime into one decision."""
        consensus = summary.consensus
        net_score = float(summary.net_score)
        base_strength = min(1.0, abs(net_score))

        if consensus == "bullish":
            signal = SIGNAL_BUY
        elif consensus == "bearish":
            signal = SIGNAL_SELL
        else:
            return SIGNAL_HOLD, 0.0, f"中性(net={net_score:+.2f}) regime={regime_label}"

        note = ""
        if self.use_regime:
            # Veto buying into a bear regime; modulate strength by confirmation.
            if signal == SIGNAL_BUY and regime_label in _BEAR_REGIMES:
                return (
                    SIGNAL_HOLD,
                    0.0,
                    f"看多但熊市regime抑制(net={net_score:+.2f})",
                )
            confirms = (signal == SIGNAL_BUY and regime_label in _BULL_REGIMES) or (
                signal == SIGNAL_SELL and regime_label in _BEAR_REGIMES
            )
            contradicts = (signal == SIGNAL_BUY and regime_label in _BEAR_REGIMES) or (
                signal == SIGNAL_SELL and regime_label in _BULL_REGIMES
            )
            if confirms:
                base_strength = min(1.0, base_strength * 1.1)
                note = " regime确认"
            elif contradicts:
                base_strength *= 0.8
                note = " regime背离"

        direction = "看多" if signal == SIGNAL_BUY else "看空"
        reason = (
            f"{direction}(net={net_score:+.2f}, {summary.bullish_count}多/"
            f"{summary.bearish_count}空) regime={regime_label}{note}"
        )
        return signal, base_strength, reason

    def get_params(self) -> dict:
        return {
            "min_history": self.min_history,
            "use_regime": self.use_regime,
            "regime_stride": self.regime_stride,
        }
