"""Alternative bar generator for advanced signal detection.

Time bars oversample quiet periods and undersample volatile ones.
Alternative bar types respond to actual market activity:
- Volume bars: new bar every N shares traded
- Dollar/Amount bars: new bar every N RMB traded
- Tick imbalance bars: new bar when buy/sell imbalance exceeds threshold

Reference: Lopez de Prado, "Advances in Financial Machine Learning", Ch. 2
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass

from src.utils.logger import get_logger

logger = get_logger("quant.alternative_bars")

__all__ = [
    "AlternativeBarGenerator",
    "BarConfig",
]

_EMPTY_BAR_COLUMNS = [
    "datetime",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "bar_count",
]


@dataclass
class BarConfig:
    """Configuration for alternative bar generation."""

    bar_type: str  # "volume", "amount", "tick_imbalance"
    threshold: float  # Volume, amount, or imbalance threshold


class AlternativeBarGenerator:
    """Generate alternative bar types from tick or minute data."""

    def volume_bars(self, data: pd.DataFrame, threshold: int = 100_000) -> pd.DataFrame:
        """Generate volume bars -- new bar every ``threshold`` shares.

        Args:
            data: DataFrame with columns
                [datetime, open/price, high, low, close, volume, amount].
                Can be tick-level or minute-level data.
            threshold: Volume per bar (shares).

        Returns:
            DataFrame with columns
            [datetime, open, high, low, close, volume, amount, bar_count]
            where each row represents one volume bar.
        """
        return self._accumulation_bars(data, threshold, accumulate_col="volume")

    def amount_bars(
        self, data: pd.DataFrame, threshold: float = 5_000_000
    ) -> pd.DataFrame:
        """Generate dollar/amount bars -- new bar every ``threshold`` RMB traded.

        Args:
            data: DataFrame with volume and amount columns.
            threshold: Amount per bar (RMB). Default 500万.
        """
        return self._accumulation_bars(data, threshold, accumulate_col="amount")

    def tick_imbalance_bars(
        self,
        ticks: list,
        expected_imbalance: float | None = None,
    ) -> pd.DataFrame:
        """Generate tick imbalance bars.

        A tick is classified as buy (+1) or sell (-1).
        Cumulative imbalance = sum of classifications.
        New bar when |cumulative imbalance| >= threshold.

        If ``expected_imbalance`` is None, use exponential moving average
        of previous bar imbalances as adaptive threshold (per Lopez de Prado).

        Args:
            ticks: List of objects with attributes:
                   datetime, price, volume, amount, direction (+1/-1).
            expected_imbalance: Fixed threshold, or None for adaptive.
        """
        if not ticks:
            return self._empty_bars()

        # Extract tick data
        tick_data: list[dict] = []
        for t in ticks:
            tick_data.append(
                {
                    "datetime": getattr(t, "datetime", None),
                    "price": getattr(t, "price", 0.0),
                    "volume": getattr(t, "volume", 0),
                    "amount": getattr(t, "amount", 0.0),
                    "direction": getattr(t, "direction", 0),
                }
            )

        if not tick_data:
            return self._empty_bars()

        # Adaptive threshold: start with a default then update via EWMA
        ewma_alpha = 0.1
        threshold = expected_imbalance if expected_imbalance is not None else 20.0
        adaptive = expected_imbalance is None

        bars: list[dict] = []
        bar_open = tick_data[0]["price"]
        bar_high = tick_data[0]["price"]
        bar_low = tick_data[0]["price"]
        bar_start_dt = tick_data[0]["datetime"]
        bar_volume = 0
        bar_amount = 0.0
        cumulative_imbalance = 0
        bar_tick_count = 0

        for tick in tick_data:
            price = tick["price"]
            direction = tick["direction"]

            if price <= 0:
                continue

            bar_high = max(bar_high, price)
            bar_low = min(bar_low, price)
            bar_close = price
            bar_volume += tick["volume"]
            bar_amount += tick["amount"]
            bar_tick_count += 1

            # Classify tick direction
            if direction > 0:
                cumulative_imbalance += 1
            elif direction < 0:
                cumulative_imbalance -= 1

            # Check if we should close this bar
            if abs(cumulative_imbalance) >= threshold and bar_tick_count > 0:
                bars.append(
                    {
                        "datetime": bar_start_dt,
                        "open": bar_open,
                        "high": bar_high,
                        "low": bar_low,
                        "close": bar_close,
                        "volume": bar_volume,
                        "amount": bar_amount,
                        "bar_count": len(bars) + 1,
                    }
                )

                # Update adaptive threshold via EWMA
                if adaptive:
                    threshold = (
                        ewma_alpha * abs(cumulative_imbalance)
                        + (1 - ewma_alpha) * threshold
                    )
                    # Floor to avoid collapsing to zero
                    threshold = max(threshold, 2.0)

                # Reset for next bar
                cumulative_imbalance = 0
                bar_tick_count = 0
                bar_volume = 0
                bar_amount = 0.0
                # Next tick sets new bar_open
                bar_open = price
                bar_high = price
                bar_low = price
                bar_start_dt = tick["datetime"]

        # Don't emit partial bar (consistent with Lopez de Prado)

        if not bars:
            return self._empty_bars()

        return pd.DataFrame(bars, columns=_EMPTY_BAR_COLUMNS)

    def compute_factors_from_bars(self, bars: pd.DataFrame) -> dict[str, float]:
        """Compute enhanced factors from alternative bars.

        These factors capture information lost in time bars:
        - bar_frequency: bars per unit time (high = volatile)
        - bar_size_consistency: std(volume) / mean(volume) of bars
        - recent_bar_direction: bullish/bearish ratio of last N bars
        - bar_acceleration: bar frequency change (speeding up vs slowing)
        """
        if bars is None or bars.empty or len(bars) < 2:
            return {
                "bar_frequency": 0.5,
                "bar_size_consistency": 0.5,
                "recent_bar_direction": 0.5,
                "bar_acceleration": 0.5,
            }

        factors: dict[str, float] = {}

        # --- Bar frequency: bars per minute ---
        if "datetime" in bars.columns and len(bars) >= 2:
            dt_col = bars["datetime"]
            if not pd.api.types.is_datetime64_any_dtype(dt_col):
                dt_col = pd.to_datetime(dt_col, errors="coerce")

            valid_dt = dt_col.dropna()
            if len(valid_dt) >= 2:
                span_seconds = (valid_dt.iloc[-1] - valid_dt.iloc[0]).total_seconds()
                if span_seconds > 0:
                    bars_per_min = len(bars) / (span_seconds / 60.0)
                    # Normalize: 0 bars/min → 0, 2+ bars/min → 1
                    factors["bar_frequency"] = round(
                        max(0.0, min(1.0, bars_per_min / 2.0)), 4
                    )

        factors.setdefault("bar_frequency", 0.5)

        # --- Size consistency: low CV = institutional-like flow ---
        if "volume" in bars.columns:
            vol = bars["volume"].astype(float)
            mean_vol = vol.mean()
            if mean_vol > 0:
                cv = vol.std() / mean_vol
                # Low CV = consistent = higher score
                factors["bar_size_consistency"] = round(max(0.0, min(1.0, 1.0 - cv)), 4)
            else:
                factors["bar_size_consistency"] = 0.5
        else:
            factors["bar_size_consistency"] = 0.5

        # --- Recent bar direction ---
        if "close" in bars.columns and "open" in bars.columns:
            recent = bars.tail(min(10, len(bars)))
            bullish = (recent["close"] > recent["open"]).sum()
            total = len(recent)
            factors["recent_bar_direction"] = round(bullish / total, 4)
        else:
            factors["recent_bar_direction"] = 0.5

        # --- Acceleration: compare bar frequency in recent vs earlier half ---
        if len(bars) >= 4 and "datetime" in bars.columns:
            dt_col = bars["datetime"]
            if not pd.api.types.is_datetime64_any_dtype(dt_col):
                dt_col = pd.to_datetime(dt_col, errors="coerce")

            valid_dt = dt_col.dropna()
            if len(valid_dt) >= 4:
                mid = len(valid_dt) // 2
                first_half_span = (
                    valid_dt.iloc[mid] - valid_dt.iloc[0]
                ).total_seconds()
                second_half_span = (
                    valid_dt.iloc[-1] - valid_dt.iloc[mid]
                ).total_seconds()

                if first_half_span > 0 and second_half_span > 0:
                    first_rate = mid / first_half_span
                    second_rate = (len(valid_dt) - mid) / second_half_span
                    # Ratio > 1 = accelerating (more bars recently)
                    accel_ratio = second_rate / first_rate
                    # Sigmoid: ratio 1.0 → 0.5, >1 → higher, <1 → lower
                    import math

                    factors["bar_acceleration"] = round(
                        1.0 / (1.0 + math.exp(-(accel_ratio - 1.0) * 3.0)), 4
                    )

        factors.setdefault("bar_acceleration", 0.5)

        return factors

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _accumulation_bars(
        self,
        data: pd.DataFrame,
        threshold: float,
        accumulate_col: str,
    ) -> pd.DataFrame:
        """Generic accumulation bar builder (shared by volume and amount bars).

        Iterates through source rows, accumulating ``accumulate_col`` until
        the cumulative value reaches ``threshold``, then emits a bar.
        """
        if data is None or data.empty:
            return self._empty_bars()

        if threshold <= 0:
            logger.warning("Bar threshold must be positive, got %s", threshold)
            return self._empty_bars()

        df = data.copy()

        # Normalize column names: accept 'price' as 'close' for tick data
        if "close" not in df.columns and "price" in df.columns:
            df["close"] = df["price"]
        if "open" not in df.columns:
            df["open"] = df["close"]
        if "high" not in df.columns:
            df["high"] = df["close"]
        if "low" not in df.columns:
            df["low"] = df["close"]
        if "amount" not in df.columns:
            df["amount"] = 0.0
        if "volume" not in df.columns:
            df["volume"] = 0

        required = ["datetime", "open", "high", "low", "close", accumulate_col]
        for col in required:
            if col not in df.columns:
                logger.warning("Missing column %s for bar generation", col)
                return self._empty_bars()

        # Convert to numpy for faster iteration
        dt_vals = df["datetime"].values
        open_vals = df["open"].values.astype(float)
        high_vals = df["high"].values.astype(float)
        low_vals = df["low"].values.astype(float)
        close_vals = df["close"].values.astype(float)
        vol_vals = df["volume"].values.astype(float)
        amt_vals = df["amount"].values.astype(float)
        accum_vals = df[accumulate_col].values.astype(float)

        bars: list[dict] = []
        bar_start_idx = 0
        cumulative = 0.0

        for i in range(len(df)):
            cumulative += accum_vals[i]

            if cumulative >= threshold:
                # Emit bar from bar_start_idx to i (inclusive)
                bar_open = open_vals[bar_start_idx]
                bar_high = float(np.max(high_vals[bar_start_idx : i + 1]))
                bar_low = float(np.min(low_vals[bar_start_idx : i + 1]))
                bar_close = close_vals[i]
                bar_vol = float(np.sum(vol_vals[bar_start_idx : i + 1]))
                bar_amt = float(np.sum(amt_vals[bar_start_idx : i + 1]))

                bars.append(
                    {
                        "datetime": dt_vals[bar_start_idx],
                        "open": bar_open,
                        "high": bar_high,
                        "low": bar_low,
                        "close": bar_close,
                        "volume": bar_vol,
                        "amount": bar_amt,
                        "bar_count": len(bars) + 1,
                    }
                )

                # Handle overflow: if cumulative > threshold, the remainder
                # carries into the next bar
                overflow = cumulative - threshold
                cumulative = overflow
                bar_start_idx = i + 1

        # Don't emit partial bar at the end (consistent with academic practice)

        if not bars:
            return self._empty_bars()

        return pd.DataFrame(bars, columns=_EMPTY_BAR_COLUMNS)

    @staticmethod
    def _empty_bars() -> pd.DataFrame:
        """Return empty DataFrame with correct bar columns."""
        return pd.DataFrame(columns=_EMPTY_BAR_COLUMNS)
