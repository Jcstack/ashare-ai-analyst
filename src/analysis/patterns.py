"""Candlestick pattern recognition and support/resistance detection.

All pattern detection is implemented with simple OHLC arithmetic -- no
external TA-Lib binary dependency is required.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


class PatternRecognizer:
    """Detect common candlestick patterns and structural price levels.

    The recognizer works directly on a pandas DataFrame that contains at
    least the standard OHLCV columns: ``open``, ``high``, ``low``,
    ``close``, ``volume``.
    """

    # ------------------------------------------------------------------
    # Candlestick patterns
    # ------------------------------------------------------------------

    def detect_candlestick_patterns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Detect classic single- and multi-bar candlestick patterns.

        Patterns detected:

        * **hammer** (锤子线) -- small real body at the upper end of the
          trading range with a long lower shadow.
        * **engulfing** (吞没形态) -- the current bar's body completely
          engulfs the prior bar's body.  Bullish engulfing returns ``1``,
          bearish engulfing returns ``-1``.
        * **doji** (十字星) -- open and close are virtually equal.
        * **morning_star** (早晨之星) -- three-bar bullish reversal.
        * **evening_star** (黄昏之星) -- three-bar bearish reversal.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame with ``open``, ``high``, ``low``, ``close`` columns.

        Returns
        -------
        pd.DataFrame
            Copy of *df* with boolean / signal-strength columns added for
            each pattern (``pattern_hammer``, ``pattern_engulfing``, etc.).
        """
        df = df.copy()
        df["pattern_hammer"] = self._detect_hammer(df)
        df["pattern_engulfing"] = self._detect_engulfing(df)
        df["pattern_doji"] = self._detect_doji(df)
        df["pattern_morning_star"] = self._detect_morning_star(df)
        df["pattern_evening_star"] = self._detect_evening_star(df)
        return df

    # -- individual pattern helpers ------------------------------------

    @staticmethod
    def _detect_hammer(df: pd.DataFrame) -> pd.Series:
        """Return a boolean Series that is True on hammer candles.

        A hammer is characterised by:
        - A small real body (< 30 % of the full range).
        - A lower shadow at least twice the size of the real body.
        - Little to no upper shadow (< 10 % of the full range).
        """
        body = (df["close"] - df["open"]).abs()
        full_range = df["high"] - df["low"]
        # Avoid division by zero on doji-like bars
        safe_range = full_range.replace(0, np.nan)

        upper_shadow = df["high"] - df[["open", "close"]].max(axis=1)
        lower_shadow = df[["open", "close"]].min(axis=1) - df["low"]

        small_body = body / safe_range < 0.30
        long_lower = lower_shadow >= 2 * body
        tiny_upper = upper_shadow / safe_range < 0.10

        return (small_body & long_lower & tiny_upper).fillna(False)

    @staticmethod
    def _detect_engulfing(df: pd.DataFrame) -> pd.Series:
        """Return a Series with 1 (bullish), -1 (bearish), or 0 (none).

        Bullish engulfing: prior bar is bearish, current bar's body fully
        covers the prior body, and current bar closes above prior open.
        Bearish engulfing: mirror image.
        """
        prev_open = df["open"].shift(1)
        prev_close = df["close"].shift(1)

        curr_body_high = df[["open", "close"]].max(axis=1)
        curr_body_low = df[["open", "close"]].min(axis=1)
        prev_body_high = pd.concat([prev_open, prev_close], axis=1).max(axis=1)
        prev_body_low = pd.concat([prev_open, prev_close], axis=1).min(axis=1)

        bullish = (
            (prev_close < prev_open)  # prior bar bearish
            & (df["close"] > df["open"])  # current bar bullish
            & (curr_body_high > prev_body_high)
            & (curr_body_low < prev_body_low)
        )
        bearish = (
            (prev_close > prev_open)  # prior bar bullish
            & (df["close"] < df["open"])  # current bar bearish
            & (curr_body_high > prev_body_high)
            & (curr_body_low < prev_body_low)
        )

        signal = pd.Series(0, index=df.index, dtype=int)
        signal[bullish] = 1
        signal[bearish] = -1
        return signal

    @staticmethod
    def _detect_doji(df: pd.DataFrame, threshold: float = 0.05) -> pd.Series:
        """Return True where the candle is a doji.

        A doji has a real body smaller than *threshold* times the full range.
        """
        body = (df["close"] - df["open"]).abs()
        full_range = df["high"] - df["low"]
        safe_range = full_range.replace(0, np.nan)
        return ((body / safe_range) < threshold).fillna(False)

    @staticmethod
    def _detect_morning_star(df: pd.DataFrame) -> pd.Series:
        """Detect the three-bar bullish morning-star pattern.

        Bar 1: long bearish candle.
        Bar 2: small-body candle (gap down preferred).
        Bar 3: long bullish candle that closes above bar-1 midpoint.
        """
        body = (df["close"] - df["open"]).abs()
        avg_body = body.rolling(window=20, min_periods=1).mean()

        bar1_bearish = df["close"].shift(2) < df["open"].shift(2)
        bar1_long = body.shift(2) > avg_body.shift(2)

        bar2_small = body.shift(1) < 0.3 * avg_body.shift(1)

        bar3_bullish = df["close"] > df["open"]
        bar3_long = body > avg_body
        midpoint_bar1 = (df["open"].shift(2) + df["close"].shift(2)) / 2
        bar3_above_mid = df["close"] > midpoint_bar1

        signal = (
            bar1_bearish
            & bar1_long
            & bar2_small
            & bar3_bullish
            & bar3_long
            & bar3_above_mid
        ).fillna(False)
        return signal

    @staticmethod
    def _detect_evening_star(df: pd.DataFrame) -> pd.Series:
        """Detect the three-bar bearish evening-star pattern.

        Bar 1: long bullish candle.
        Bar 2: small-body candle (gap up preferred).
        Bar 3: long bearish candle that closes below bar-1 midpoint.
        """
        body = (df["close"] - df["open"]).abs()
        avg_body = body.rolling(window=20, min_periods=1).mean()

        bar1_bullish = df["close"].shift(2) > df["open"].shift(2)
        bar1_long = body.shift(2) > avg_body.shift(2)

        bar2_small = body.shift(1) < 0.3 * avg_body.shift(1)

        bar3_bearish = df["close"] < df["open"]
        bar3_long = body > avg_body
        midpoint_bar1 = (df["open"].shift(2) + df["close"].shift(2)) / 2
        bar3_below_mid = df["close"] < midpoint_bar1

        signal = (
            bar1_bullish
            & bar1_long
            & bar2_small
            & bar3_bearish
            & bar3_long
            & bar3_below_mid
        ).fillna(False)
        return signal

    # ------------------------------------------------------------------
    # Support / Resistance
    # ------------------------------------------------------------------

    def find_support_resistance(
        self,
        df: pd.DataFrame,
        lookback: int = 60,
        min_touches: int = 2,
        tolerance: float = 0.015,
    ) -> list[dict[str, Any]]:
        """Identify horizontal support and resistance price levels.

        The algorithm scans for local pivot highs and lows within the
        most recent *lookback* bars, clusters them by proximity, and
        retains levels that have been "touched" at least *min_touches*
        times.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame with ``high``, ``low``, ``close`` columns.
        lookback : int
            Number of recent bars to consider.
        min_touches : int
            Minimum number of pivot points that must be near a level for
            it to qualify.
        tolerance : float
            Fractional price tolerance used when clustering pivots
            (e.g. 0.015 means 1.5 %).

        Returns
        -------
        list[dict[str, Any]]
            A list of dicts, each containing:
            - ``level`` (float): the price level,
            - ``type`` (str): ``"support"`` or ``"resistance"``,
            - ``touches`` (int): how many pivot points clustered there.
        """
        recent = df.tail(lookback).copy()
        if len(recent) < 5:
            return []

        pivots: list[tuple[float, str]] = []

        highs = recent["high"].values
        lows = recent["low"].values

        # Simple 2-bar pivot detection
        for i in range(2, len(recent) - 2):
            if (
                highs[i] >= highs[i - 1]
                and highs[i] >= highs[i - 2]
                and highs[i] >= highs[i + 1]
                and highs[i] >= highs[i + 2]
            ):
                pivots.append((float(highs[i]), "resistance"))
            if (
                lows[i] <= lows[i - 1]
                and lows[i] <= lows[i - 2]
                and lows[i] <= lows[i + 1]
                and lows[i] <= lows[i + 2]
            ):
                pivots.append((float(lows[i]), "support"))

        if not pivots:
            return []

        # Cluster pivots that are within tolerance of each other
        pivots.sort(key=lambda x: x[0])
        clusters: list[list[tuple[float, str]]] = []
        current_cluster: list[tuple[float, str]] = [pivots[0]]

        for price, ptype in pivots[1:]:
            ref_price = current_cluster[0][0]
            if abs(price - ref_price) / ref_price <= tolerance:
                current_cluster.append((price, ptype))
            else:
                clusters.append(current_cluster)
                current_cluster = [(price, ptype)]
        clusters.append(current_cluster)

        levels: list[dict[str, Any]] = []
        for cluster in clusters:
            if len(cluster) >= min_touches:
                avg_price = float(np.mean([p for p, _ in cluster]))
                # Determine dominant type
                type_counts: dict[str, int] = {}
                for _, ptype in cluster:
                    type_counts[ptype] = type_counts.get(ptype, 0) + 1
                dominant_type = max(type_counts, key=type_counts.get)  # type: ignore[arg-type]
                levels.append(
                    {
                        "level": round(avg_price, 2),
                        "type": dominant_type,
                        "touches": len(cluster),
                    }
                )

        return levels

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Combine detected patterns into a unified signal column.

        The signal column (``signal``) uses:
        * ``1``  -- buy signal
        * ``-1`` -- sell signal
        * ``0``  -- neutral / hold

        Bullish patterns (hammer, bullish engulfing, morning star) add to
        a running score; bearish patterns (bearish engulfing, evening
        star) subtract.  A doji is treated as neutral.  The final sign
        of the accumulated score determines the signal.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame with OHLCV columns.  Pattern columns will be
            computed internally if not already present.

        Returns
        -------
        pd.DataFrame
            Copy of *df* with a ``signal`` column appended.
        """
        df = self.detect_candlestick_patterns(df)

        score = pd.Series(0.0, index=df.index)

        # Bullish contributions
        score += df["pattern_hammer"].astype(float)  # +1 when True
        score += df["pattern_engulfing"].clip(lower=0).astype(float)  # +1 bullish
        score += df["pattern_morning_star"].astype(float)

        # Bearish contributions
        score += df["pattern_engulfing"].clip(upper=0).astype(float)  # -1 bearish
        score -= df["pattern_evening_star"].astype(float)

        df["signal"] = np.sign(score).astype(int)
        return df
