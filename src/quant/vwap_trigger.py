"""VWAP mean-reversion trigger -- fires signals when price deviates from VWAP.

Complements the passive ``vwap_deviation`` factor in
:mod:`src.quant.intraday_factors` by actively emitting actionable signals
when the Z-score of the price-VWAP deviation exceeds configurable thresholds.

Signal types:
- **mean_reversion_long**: price far below VWAP, selling exhaustion expected
- **mean_reversion_short**: price far above VWAP, buying exhaustion expected
- **trend_continuation**: moderate deviation with volume acceleration
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger("quant.vwap_trigger")

__all__ = [
    "VwapSignal",
    "VwapTriggerEngine",
]


@dataclasses.dataclass
class VwapSignal:
    """An actionable VWAP-based trading signal."""

    symbol: str
    signal_type: (
        str  # "mean_reversion_long" | "mean_reversion_short" | "trend_continuation"
    )
    deviation_pct: float  # how far from VWAP in %
    z_score: float  # deviation in standard deviations
    vwap_price: float  # current VWAP
    current_price: float
    direction: str  # "bullish" | "bearish"
    severity: float  # 0-1
    confidence: float  # 0-1, higher when volume confirms
    description: str  # Chinese description


class VwapTriggerEngine:
    """Detects actionable VWAP-based signals from minute bar data."""

    # Configuration
    REVERSION_THRESHOLD_Z = 2.0  # Z-score for mean reversion signal
    TREND_THRESHOLD_Z = 1.5  # Z-score for trend continuation (with volume)
    MIN_BARS = 12  # Need at least 1 hour of data
    ROLLING_WINDOW = 20  # Rolling window for Z-score std

    def analyze(self, bars: pd.DataFrame, symbol: str) -> list[VwapSignal]:
        """Analyze minute bars for VWAP signals.

        Args:
            bars: DataFrame with columns
                [datetime, open, high, low, close, volume, amount]
            symbol: stock code

        Returns:
            List of VwapSignal (usually 0 or 1)
        """
        if bars is None or bars.empty or len(bars) < self.MIN_BARS:
            logger.debug(
                "Insufficient bars for %s (%d), need %d",
                symbol,
                0 if bars is None else len(bars),
                self.MIN_BARS,
            )
            return []

        df = bars.copy()

        # Guard against zero-volume rows that would corrupt VWAP
        total_volume = df["volume"].sum()
        if total_volume <= 0:
            logger.debug("Zero total volume for %s, skipping VWAP analysis", symbol)
            return []

        # --- Cumulative VWAP ---
        cum_amount = df["amount"].cumsum()
        cum_volume = df["volume"].cumsum()
        # Avoid division by zero on leading zero-volume bars
        vwap_series = cum_amount / cum_volume.replace(0, np.nan)
        vwap_series = vwap_series.ffill().fillna(0.0)

        current_vwap = float(vwap_series.iloc[-1])
        if current_vwap <= 0:
            return []

        current_price = float(df["close"].iloc[-1])

        # --- Deviation series ---
        deviation_pct = (df["close"] - vwap_series) / vwap_series * 100

        # --- Z-score ---
        window = min(self.ROLLING_WINDOW, len(df))
        rolling_std = deviation_pct.rolling(
            window=window, min_periods=max(window // 2, 2)
        ).std()
        current_std = (
            float(rolling_std.iloc[-1]) if pd.notna(rolling_std.iloc[-1]) else 0.0
        )

        if current_std <= 0:
            # Flat deviation -- no meaningful Z-score
            return []

        current_dev = float(deviation_pct.iloc[-1])
        z_score = current_dev / current_std

        signals: list[VwapSignal] = []

        # --- Mean Reversion Long: price far below VWAP ---
        if z_score < -self.REVERSION_THRESHOLD_Z:
            vol_conf = self._volume_confirmation(df, direction="long")
            severity = min(1.0, abs(z_score) / 3.0)
            base_confidence = min(1.0, abs(z_score) / 4.0)
            confidence = min(1.0, base_confidence + (0.15 if vol_conf else 0.0))

            signals.append(
                VwapSignal(
                    symbol=symbol,
                    signal_type="mean_reversion_long",
                    deviation_pct=round(current_dev, 2),
                    z_score=round(z_score, 2),
                    vwap_price=round(current_vwap, 2),
                    current_price=round(current_price, 2),
                    direction="bullish",
                    severity=round(severity, 3),
                    confidence=round(confidence, 3),
                    description=(
                        f"股价偏离VWAP {abs(current_dev):.1f}%，"
                        f"超过{abs(z_score):.1f}个标准差，均值回归概率较高"
                    ),
                )
            )

        # --- Mean Reversion Short: price far above VWAP ---
        elif z_score > self.REVERSION_THRESHOLD_Z:
            vol_conf = self._volume_confirmation(df, direction="short")
            severity = min(1.0, abs(z_score) / 3.0)
            base_confidence = min(1.0, abs(z_score) / 4.0)
            confidence = min(1.0, base_confidence + (0.15 if vol_conf else 0.0))

            signals.append(
                VwapSignal(
                    symbol=symbol,
                    signal_type="mean_reversion_short",
                    deviation_pct=round(current_dev, 2),
                    z_score=round(z_score, 2),
                    vwap_price=round(current_vwap, 2),
                    current_price=round(current_price, 2),
                    direction="bearish",
                    severity=round(severity, 3),
                    confidence=round(confidence, 3),
                    description=(
                        f"股价偏离VWAP {current_dev:.1f}%，"
                        f"超过{z_score:.1f}个标准差，回落风险较大"
                    ),
                )
            )

        # --- Trend Continuation: moderate deviation + volume surge ---
        elif abs(z_score) >= 1.0 and abs(z_score) < self.REVERSION_THRESHOLD_Z:
            if self._volume_accelerating(df):
                direction = "bullish" if z_score > 0 else "bearish"
                severity = min(1.0, abs(z_score) / 3.0)
                confidence = min(1.0, abs(z_score) / 3.0)

                if z_score > 0:
                    desc = (
                        f"股价高于VWAP {current_dev:.1f}%且成交量放大，"
                        "机构资金推动趋势延续"
                    )
                else:
                    desc = (
                        f"股价低于VWAP {abs(current_dev):.1f}%且成交量放大，"
                        "空方动能延续"
                    )

                signals.append(
                    VwapSignal(
                        symbol=symbol,
                        signal_type="trend_continuation",
                        deviation_pct=round(current_dev, 2),
                        z_score=round(z_score, 2),
                        vwap_price=round(current_vwap, 2),
                        current_price=round(current_price, 2),
                        direction=direction,
                        severity=round(severity, 3),
                        confidence=round(confidence, 3),
                        description=desc,
                    )
                )

        return signals

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _volume_confirmation(df: pd.DataFrame, direction: str) -> bool:
        """Check if volume pattern supports the signal.

        For mean reversion long: volume declining = selling exhaustion = confirms.
        For mean reversion short: volume declining = buying exhaustion = confirms.

        Args:
            df: Minute bar DataFrame.
            direction: "long" or "short".

        Returns:
            True if volume pattern confirms the signal.
        """
        if len(df) < 6:
            return False

        recent = df["volume"].iloc[-6:].values.astype(float)
        x = np.arange(len(recent), dtype=float)
        x_mean = x.mean()
        denom = np.sum((x - x_mean) ** 2)

        if denom <= 0:
            return False

        slope = np.sum((x - x_mean) * (recent - recent.mean())) / denom

        # For both long and short reversion, declining volume = exhaustion
        return bool(slope < 0)

    @staticmethod
    def _volume_accelerating(df: pd.DataFrame) -> bool:
        """Check if recent volume is >1.5x the prior average.

        Institutional benchmark crossing = trend confirmation.

        Returns:
            True if last 3 bars average volume > 1.5x the preceding bars average.
        """
        if len(df) < 6:
            return False

        recent_avg = float(df["volume"].iloc[-3:].mean())
        prior_avg = float(df["volume"].iloc[:-3].mean())

        if prior_avg <= 0:
            return False

        return recent_avg > 1.5 * prior_avg
