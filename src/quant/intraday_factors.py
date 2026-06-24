"""Intraday factor engine — computes real-time factors from minute bars.

Complements daily Qlib factors with sub-daily signals that capture
intraday dynamics invisible to end-of-day analysis.

Factor categories:
- Price structure: VWAP deviation, high reversal, amplitude
- Momentum: 5min, 30min, late session, opening drive
- Volume dynamics: volume-price divergence, volume concentration
- Micro-structure: bar strength

All factors normalized to [0, 1] where 0.5 = neutral.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import time as dt_time

from src.utils.logger import get_logger

logger = get_logger("quant.intraday_factors")

__all__ = [
    "IntradayFactorEngine",
]


class IntradayFactorEngine:
    """Compute intraday factors from 5-minute OHLCV bars."""

    def compute(
        self, minute_bars: pd.DataFrame, quote: dict | None = None
    ) -> dict[str, float]:
        """Compute all intraday factors for a stock.

        Args:
            minute_bars: DataFrame with columns
                [datetime, open, high, low, close, volume, amount].
                Must be today's bars, sorted by datetime ascending.
            quote: Optional current real-time quote dict with keys:
                   price, open, high, low, prev_close, volume

        Returns:
            dict of factors (all normalized 0-1 where possible).
        """
        if minute_bars is None or minute_bars.empty:
            logger.debug("Empty minute_bars, returning neutral factors")
            return self._neutral_factors()

        # Ensure datetime column is parsed
        df = minute_bars.copy()
        if not pd.api.types.is_datetime64_any_dtype(df["datetime"]):
            df["datetime"] = pd.to_datetime(df["datetime"])

        # Current price: prefer real-time quote, fallback to last bar close
        current_price = (
            quote["price"] if quote and quote.get("price") else df["close"].iloc[-1]
        )
        prev_close = (
            quote["prev_close"]
            if quote and quote.get("prev_close")
            else df["open"].iloc[0]
        )
        intraday_high = (
            max(df["high"].max(), quote["high"])
            if quote and quote.get("high")
            else df["high"].max()
        )
        intraday_low = (
            min(df["low"].min(), quote["low"])
            if quote and quote.get("low")
            else df["low"].min()
        )

        factors: dict[str, float] = {}

        factors["vwap_deviation"] = self._vwap_deviation(df, current_price)
        factors["high_reversal_pct"] = self._high_reversal_pct(
            intraday_high, current_price
        )
        factors["intraday_momentum_5m"] = self._intraday_momentum_5m(df)
        factors["intraday_momentum_30m"] = self._intraday_momentum_30m(df)
        factors["volume_price_divergence"] = self._volume_price_divergence(df)
        factors["late_session_momentum"] = self._late_session_momentum(
            df, current_price
        )
        factors["volume_concentration"] = self._volume_concentration(df)
        factors["open_drive"] = self._open_drive(df)
        factors["bar_strength"] = self._bar_strength(df)
        factors["amplitude"] = self._amplitude(intraday_high, intraday_low, prev_close)

        return factors

    def compute_batch(
        self,
        minute_data: dict[str, pd.DataFrame],
        quotes: dict[str, dict] | None = None,
    ) -> dict[str, dict[str, float]]:
        """Compute factors for multiple symbols.

        Args:
            minute_data: {symbol: minute_bars_df}
            quotes: {symbol: quote_dict}

        Returns:
            {symbol: {factor_name: factor_value}}
        """
        quotes = quotes or {}
        results: dict[str, dict[str, float]] = {}

        for symbol, bars in minute_data.items():
            try:
                results[symbol] = self.compute(bars, quotes.get(symbol))
            except Exception as exc:
                logger.warning(
                    "Intraday factor computation failed for %s: %s",
                    symbol,
                    exc,
                )
                results[symbol] = self._neutral_factors()

        return results

    # ------------------------------------------------------------------
    # Factor computations
    # ------------------------------------------------------------------

    @staticmethod
    def _vwap_deviation(df: pd.DataFrame, current_price: float) -> float:
        """Current price vs VWAP ratio, normalized to [0, 1].

        VWAP = sum(amount) / sum(volume).
        Above VWAP (>0.5) = bullish, below (<0.5) = bearish.
        """
        total_volume = df["volume"].sum()
        if total_volume <= 0:
            return 0.5

        total_amount = df["amount"].sum()
        vwap = total_amount / total_volume

        if vwap <= 0:
            return 0.5

        deviation = (current_price - vwap) / vwap
        # Clamp to [-0.05, 0.05], then normalize to [0, 1]
        clamped = max(-0.05, min(0.05, deviation))
        return round(clamped / 0.1 + 0.5, 4)

    @staticmethod
    def _high_reversal_pct(intraday_high: float, current_price: float) -> float:
        """Distance from intraday high — 冲高回落 indicator.

        0.0 = reversal >= 5% from high (weak).
        1.0 = at high (strong).
        """
        if intraday_high <= 0:
            return 0.5

        reversal = (intraday_high - current_price) / intraday_high
        # Normalize: 0% reversal → 1.0, 5%+ reversal → 0.0
        normalized = max(0.0, min(1.0, 1.0 - reversal / 0.05))
        return round(normalized, 4)

    @staticmethod
    def _intraday_momentum_5m(df: pd.DataFrame) -> float:
        """Last 5-minute bar momentum, normalized around 0.5."""
        if len(df) < 2:
            return 0.5

        last_close = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2]

        if prev_close <= 0:
            return 0.5

        momentum = (last_close - prev_close) / prev_close
        # Clamp to [-0.03, 0.03], normalize to [0, 1]
        clamped = max(-0.03, min(0.03, momentum))
        return round(clamped / 0.06 + 0.5, 4)

    @staticmethod
    def _intraday_momentum_30m(df: pd.DataFrame) -> float:
        """Last 30-minute trend (6 bars of 5min), normalized around 0.5."""
        if len(df) < 7:
            # Not enough bars — use whatever we have
            if len(df) < 2:
                return 0.5
            ref_close = df["close"].iloc[0]
        else:
            ref_close = df["close"].iloc[-7]

        last_close = df["close"].iloc[-1]

        if ref_close <= 0:
            return 0.5

        momentum = (last_close - ref_close) / ref_close
        # Clamp to [-0.05, 0.05], normalize to [0, 1]
        clamped = max(-0.05, min(0.05, momentum))
        return round(clamped / 0.1 + 0.5, 4)

    @staticmethod
    def _volume_price_divergence(df: pd.DataFrame) -> float:
        """量价背离 detection via linear regression slope comparison.

        Price rising + volume falling → bearish divergence (< 0.5).
        Price falling + volume rising → potential reversal (> 0.5).
        Aligned trends → neutral (0.5).
        """
        if len(df) < 6:
            return 0.5

        tail = df.iloc[-6:]
        x = np.arange(len(tail), dtype=float)

        prices = tail["close"].values.astype(float)
        volumes = tail["volume"].values.astype(float)

        # Linear regression slopes via least-squares
        x_mean = x.mean()
        price_slope = np.sum((x - x_mean) * (prices - prices.mean())) / max(
            np.sum((x - x_mean) ** 2), 1e-10
        )
        vol_slope = np.sum((x - x_mean) * (volumes - volumes.mean())) / max(
            np.sum((x - x_mean) ** 2), 1e-10
        )

        # Normalize slopes to sign-only comparison
        price_dir = 1 if price_slope > 0 else (-1 if price_slope < 0 else 0)
        vol_dir = 1 if vol_slope > 0 else (-1 if vol_slope < 0 else 0)

        if price_dir == 0 or vol_dir == 0:
            return 0.5

        if price_dir > 0 and vol_dir < 0:
            # Price up, volume down → bearish divergence
            return 0.3
        if price_dir < 0 and vol_dir > 0:
            # Price down, volume up → potential reversal (bullish)
            return 0.7
        if price_dir > 0 and vol_dir > 0:
            # Both up → healthy momentum
            return 0.6
        # Both down → weakening
        return 0.4

    @staticmethod
    def _late_session_momentum(df: pd.DataFrame, current_price: float) -> float:
        """Momentum since 14:00, neutral before that time."""
        afternoon_bars = df[df["datetime"].dt.time >= dt_time(14, 0)]

        if afternoon_bars.empty:
            return 0.5  # Not yet 14:00 or no data

        price_at_14 = afternoon_bars["close"].iloc[0]
        if price_at_14 <= 0:
            return 0.5

        momentum = (current_price - price_at_14) / price_at_14
        # Clamp to [-0.03, 0.03], normalize to [0, 1]
        clamped = max(-0.03, min(0.03, momentum))
        return round(clamped / 0.06 + 0.5, 4)

    @staticmethod
    def _volume_concentration(df: pd.DataFrame) -> float:
        """Morning vs afternoon volume distribution.

        High morning concentration with afternoon fade = distribution (< 0.5).
        Even or increasing afternoon volume = accumulation (> 0.5).
        """
        morning = df[df["datetime"].dt.time < dt_time(11, 30)]
        afternoon = df[df["datetime"].dt.time >= dt_time(13, 0)]

        if morning.empty or afternoon.empty:
            return 0.5

        morning_vol = morning["volume"].sum()
        afternoon_vol = afternoon["volume"].sum()

        total = morning_vol + afternoon_vol
        if total <= 0:
            return 0.5

        # Ratio of afternoon volume to total
        # 0.5 = even split → neutral
        # > 0.5 = afternoon heavier → accumulation (bullish)
        # < 0.5 = morning heavier → distribution (bearish)
        ratio = afternoon_vol / total
        return round(max(0.0, min(1.0, ratio)), 4)

    @staticmethod
    def _open_drive(df: pd.DataFrame) -> float:
        """Opening 30-minute momentum (09:30-10:00).

        Captures gap-and-go vs gap-and-fade.
        """
        open_price = df["open"].iloc[0]
        if open_price <= 0:
            return 0.5

        # Find bars up to 10:00
        morning_bars = df[df["datetime"].dt.time <= dt_time(10, 0)]
        if morning_bars.empty:
            return 0.5

        price_at_10 = morning_bars["close"].iloc[-1]
        drive = (price_at_10 - open_price) / open_price

        # Clamp to [-0.05, 0.05], normalize to [0, 1]
        clamped = max(-0.05, min(0.05, drive))
        return round(clamped / 0.1 + 0.5, 4)

    @staticmethod
    def _bar_strength(df: pd.DataFrame) -> float:
        """Ratio of bullish bars (close > open) to total bars."""
        if df.empty:
            return 0.5

        bullish = (df["close"] > df["open"]).sum()
        total = len(df)
        return round(bullish / total, 4)

    @staticmethod
    def _amplitude(
        intraday_high: float, intraday_low: float, prev_close: float
    ) -> float:
        """Intraday amplitude (振幅) = (high - low) / prev_close.

        Normalized: low amplitude (<2%) → 1.0 (calm), high (>8%) → 0.0 (volatile).
        Inverted because high amplitude with small net change = indecision.
        """
        if prev_close <= 0:
            return 0.5

        amp = (intraday_high - intraday_low) / prev_close
        # Normalize: 0% → 1.0, 8%+ → 0.0
        normalized = max(0.0, min(1.0, 1.0 - amp / 0.08))
        return round(normalized, 4)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _neutral_factors() -> dict[str, float]:
        """Return all factors at neutral (0.5) for missing data."""
        return {
            "vwap_deviation": 0.5,
            "high_reversal_pct": 0.5,
            "intraday_momentum_5m": 0.5,
            "intraday_momentum_30m": 0.5,
            "volume_price_divergence": 0.5,
            "late_session_momentum": 0.5,
            "volume_concentration": 0.5,
            "open_drive": 0.5,
            "bar_strength": 0.5,
            "amplitude": 0.5,
        }
