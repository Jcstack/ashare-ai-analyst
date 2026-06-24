"""Simplified VPIN -- Volume-Synchronized Probability of Informed Trading.

Approximates tick-level VPIN using 5-min bar data.  Classifies each bar's volume
as buyer- or seller-initiated based on close vs open direction, then computes
the buy/sell imbalance across fixed-volume buckets.

Reference: Easley, Lopez de Prado & O'Hara (2012)
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger("quant.vpin")

__all__ = [
    "VpinCalculator",
    "VpinResult",
]


@dataclasses.dataclass
class VpinResult:
    """Result of a VPIN calculation for a single symbol."""

    symbol: str
    vpin: float  # 0-1, probability of informed trading
    toxicity_level: str  # "low" | "moderate" | "elevated" | "high"
    consecutive_high_bars: int  # consecutive volume bars with imbalance > 0.7
    alert: bool  # True if consecutive_high_bars >= ALERT_CONSECUTIVE
    trend: str  # "rising" | "falling" | "stable"
    description: str  # Chinese plain-language description


def _toxicity_label(vpin: float) -> str:
    """Map VPIN value to a human-readable toxicity level."""
    if vpin < 0.4:
        return "low"
    if vpin < 0.6:
        return "moderate"
    if vpin < 0.7:
        return "elevated"
    return "high"


_TOXICITY_CN = {
    "low": "低",
    "moderate": "中等",
    "elevated": "偏高",
    "high": "高",
}


class VpinCalculator:
    """Compute VPIN from 5-minute OHLCV bars."""

    # Number of volume buckets to use for VPIN calculation
    N_BUCKETS: int = 50
    # Alert threshold
    HIGH_VPIN: float = 0.7
    # Consecutive high bars needed for alert
    ALERT_CONSECUTIVE: int = 8

    def calculate(self, bars: pd.DataFrame, symbol: str) -> VpinResult | None:
        """Calculate VPIN from minute bars.

        Args:
            bars: DataFrame with columns
                [datetime, open, high, low, close, volume, amount].
            symbol: stock code.

        Returns:
            VpinResult or None if insufficient data.
        """
        if bars is None or len(bars) < 10:
            return None

        df = bars.copy()
        for col in ("open", "high", "low", "close", "volume"):
            if col not in df.columns:
                logger.warning("Missing column %s for VPIN", col)
                return None

        # ------------------------------------------------------------------
        # Step 1: Bulk Volume Classification (BVC)
        # ------------------------------------------------------------------
        buy_vol, sell_vol = self._classify_volume(df)

        # ------------------------------------------------------------------
        # Step 2: Volume bucketing
        # ------------------------------------------------------------------
        total_volume = df["volume"].astype(float).sum()
        if total_volume <= 0:
            return None

        n_buckets = self.N_BUCKETS
        # Adaptive: need at least 2 * n_buckets bars, otherwise shrink
        if len(df) < 2 * n_buckets:
            n_buckets = max(5, len(df) // 2)

        bucket_size = total_volume / n_buckets

        buckets = self._build_buckets(buy_vol, sell_vol, bucket_size)

        if len(buckets) < 5:
            return None

        # ------------------------------------------------------------------
        # Step 3: VPIN = mean imbalance over buckets
        # ------------------------------------------------------------------
        imbalances = np.array(
            [abs(b - s) / (b + s) if (b + s) > 0 else 0.0 for b, s in buckets]
        )
        vpin = float(np.mean(imbalances))

        # ------------------------------------------------------------------
        # Step 4: Trend detection (last 10 vs previous 10 buckets)
        # ------------------------------------------------------------------
        trend = self._detect_trend(imbalances)

        # ------------------------------------------------------------------
        # Step 5: Alert logic — consecutive high-imbalance buckets
        # ------------------------------------------------------------------
        consecutive = self._count_consecutive_high(imbalances)

        toxicity = _toxicity_label(vpin)
        alert = consecutive >= self.ALERT_CONSECUTIVE

        description = self._build_description(vpin, toxicity, alert, consecutive, trend)

        return VpinResult(
            symbol=symbol,
            vpin=round(vpin, 4),
            toxicity_level=toxicity,
            consecutive_high_bars=consecutive,
            alert=alert,
            trend=trend,
            description=description,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_volume(
        df: pd.DataFrame,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Bulk Volume Classification for each bar.

        Returns:
            (buy_volume_array, sell_volume_array) aligned to df rows.
        """
        opens = df["open"].values.astype(float)
        highs = df["high"].values.astype(float)
        lows = df["low"].values.astype(float)
        closes = df["close"].values.astype(float)
        volumes = df["volume"].values.astype(float)

        spread = highs - lows
        direction = closes - opens

        buy_vol = np.zeros(len(df), dtype=float)
        sell_vol = np.zeros(len(df), dtype=float)

        for i in range(len(df)):
            v = volumes[i]
            if v <= 0:
                continue

            if spread[i] <= 0:
                # Flat bar (high == low) — split 50/50
                buy_vol[i] = v * 0.5
                sell_vol[i] = v * 0.5
            elif direction[i] == 0:
                # Doji — split 50/50
                buy_vol[i] = v * 0.5
                sell_vol[i] = v * 0.5
            else:
                ratio = abs(direction[i]) / spread[i]
                if direction[i] > 0:
                    buy_vol[i] = v * ratio
                    sell_vol[i] = v - buy_vol[i]
                else:
                    sell_vol[i] = v * ratio
                    buy_vol[i] = v - sell_vol[i]

        return buy_vol, sell_vol

    @staticmethod
    def _build_buckets(
        buy_vol: np.ndarray,
        sell_vol: np.ndarray,
        bucket_size: float,
    ) -> list[tuple[float, float]]:
        """Accumulate classified volume into fixed-size volume buckets.

        A single bar can span multiple buckets when its volume exceeds
        the remaining capacity of the current bucket.
        """
        buckets: list[tuple[float, float]] = []
        bucket_buy = 0.0
        bucket_sell = 0.0
        bucket_remaining = bucket_size

        for i in range(len(buy_vol)):
            bar_buy = buy_vol[i]
            bar_sell = sell_vol[i]
            bar_total = bar_buy + bar_sell

            while bar_total > 0:
                if bar_total >= bucket_remaining:
                    # This bar fills (or overfills) the current bucket
                    if bar_buy + bar_sell > 0:
                        buy_frac = bar_buy / (bar_buy + bar_sell)
                    else:
                        buy_frac = 0.5
                    fill_buy = bucket_remaining * buy_frac
                    fill_sell = bucket_remaining * (1.0 - buy_frac)

                    bucket_buy += fill_buy
                    bucket_sell += fill_sell
                    buckets.append((bucket_buy, bucket_sell))

                    bar_buy -= fill_buy
                    bar_sell -= fill_sell
                    bar_total = bar_buy + bar_sell

                    # Reset for next bucket
                    bucket_buy = 0.0
                    bucket_sell = 0.0
                    bucket_remaining = bucket_size
                else:
                    # Bar fits entirely in current bucket
                    bucket_buy += bar_buy
                    bucket_sell += bar_sell
                    bucket_remaining -= bar_total
                    bar_total = 0.0

        # Don't emit partial bucket (consistent with academic practice)
        return buckets

    def _detect_trend(self, imbalances: np.ndarray) -> str:
        """Compare recent half vs earlier half of bucket imbalances."""
        mid = len(imbalances) // 2
        if mid < 2:
            return "stable"

        recent = float(np.mean(imbalances[mid:]))
        earlier = float(np.mean(imbalances[:mid]))

        diff = recent - earlier
        if diff >= 0.05:
            return "rising"
        if diff <= -0.05:
            return "falling"
        return "stable"

    def _count_consecutive_high(self, imbalances: np.ndarray) -> int:
        """Count consecutive high-imbalance buckets from the tail."""
        count = 0
        for val in reversed(imbalances):
            if val > self.HIGH_VPIN:
                count += 1
            else:
                break
        return count

    @staticmethod
    def _build_description(
        vpin: float,
        toxicity: str,
        alert: bool,
        consecutive: int,
        trend: str,
    ) -> str:
        """Build Chinese plain-language description."""
        cn_tox = _TOXICITY_CN.get(toxicity, toxicity)
        desc = f"知情交易概率{vpin:.0%}，{cn_tox}水平"

        trend_cn = {"rising": "且在上升", "falling": "且在下降", "stable": ""}
        desc += trend_cn.get(trend, "")

        if alert:
            desc += f"。连续{consecutive}个量能区间异常，建议警惕主力动向"

        return desc
