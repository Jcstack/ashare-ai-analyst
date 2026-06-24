"""Multi-timeframe momentum confirmation engine.

Validates trading signals by checking alignment across 5-min, 15-min, 30-min,
and daily timeframes. Signals confirmed by multiple timeframes have significantly
higher win rates.

Key insight: 15-minute is the natural boundary between mean-reversion and
momentum regimes (arxiv 2501.16772).
"""

from __future__ import annotations

import dataclasses

import pandas as pd

from src.utils.logger import get_logger

logger = get_logger("quant.multi_timeframe")

__all__ = [
    "MultiTimeframeEngine",
    "MtfConfirmation",
    "TimeframeSignal",
]

_PERIODS = ("5m", "15m", "30m", "daily")


@dataclasses.dataclass
class TimeframeSignal:
    """Momentum signal for a single timeframe."""

    period: str  # "5m" | "15m" | "30m" | "daily"
    direction: str  # "bullish" | "bearish" | "neutral"
    strength: float  # 0-1
    momentum: float  # raw momentum value (%)


@dataclasses.dataclass
class MtfConfirmation:
    """Cross-timeframe confirmation result."""

    symbol: str
    alignment_score: float  # 0-1, 1.0 = all timeframes agree
    confirmed_direction: str  # "bullish" | "bearish" | "conflicted"
    timeframes: list[TimeframeSignal]
    confidence_boost: float  # -0.15 to +0.15
    regime: str  # "trending" | "mean_reverting" | "transitioning"
    description: str  # Chinese description


class MultiTimeframeEngine:
    """Cross-timeframe momentum confirmation."""

    # Weights for each timeframe (higher = more influential)
    WEIGHTS: dict[str, float] = {
        "5m": 0.15,
        "15m": 0.25,
        "30m": 0.30,
        "daily": 0.30,
    }

    def analyze(
        self,
        bars_5m: pd.DataFrame,
        symbol: str,
        daily_change_pct: float | None = None,
    ) -> MtfConfirmation:
        """Analyze multi-timeframe alignment.

        Args:
            bars_5m: 5-minute OHLCV bars (today's data) with columns
                [datetime, open, high, low, close, volume, amount].
            symbol: stock code.
            daily_change_pct: optional daily-level change % for daily timeframe.

        Returns:
            MtfConfirmation with alignment details.
        """
        if bars_5m is None or bars_5m.empty or len(bars_5m) < 2:
            logger.debug("Insufficient 5m data for %s, returning neutral", symbol)
            return self._neutral_result(symbol)

        df = bars_5m.copy()
        if not pd.api.types.is_datetime64_any_dtype(df["datetime"]):
            df["datetime"] = pd.to_datetime(df["datetime"])

        # Build signals per timeframe
        signals: list[TimeframeSignal] = []

        # 5m: momentum from last 3 bars (15 min lookback)
        signals.append(self._signal_from_bars(df, "5m", lookback=3))

        # 15m: resample then last 2 bars
        bars_15m = self._resample(df, 15)
        signals.append(self._signal_from_bars(bars_15m, "15m", lookback=2))

        # 30m: resample then last 2 bars
        bars_30m = self._resample(df, 30)
        signals.append(self._signal_from_bars(bars_30m, "30m", lookback=2))

        # Daily: use provided pct or compute from open→close
        daily_mom = daily_change_pct
        if daily_mom is None:
            first_open = df["open"].iloc[0]
            last_close = df["close"].iloc[-1]
            if first_open > 0:
                daily_mom = (last_close - first_open) / first_open * 100.0
            else:
                daily_mom = 0.0
        signals.append(self._classify(daily_mom, "daily"))

        # Compute alignment
        alignment = self._compute_alignment(signals)
        direction = self._confirmed_direction(signals)
        boost = self._confidence_boost(signals)
        regime = self._detect_regime(signals)
        desc = self._build_description(signals, alignment, regime)

        return MtfConfirmation(
            symbol=symbol,
            alignment_score=round(alignment, 4),
            confirmed_direction=direction,
            timeframes=signals,
            confidence_boost=boost,
            regime=regime,
            description=desc,
        )

    # ------------------------------------------------------------------
    # Resampling
    # ------------------------------------------------------------------

    @staticmethod
    def _resample(bars_5m: pd.DataFrame, period_minutes: int) -> pd.DataFrame:
        """Resample 5-minute bars to a coarser timeframe.

        Groups bars into non-overlapping windows of *period_minutes* and
        aggregates: first open, max high, min low, last close, sum volume/amount.
        """
        if bars_5m.empty:
            return bars_5m

        df = bars_5m.copy()
        df = df.set_index("datetime")

        rule = f"{period_minutes}min"
        agg = df.resample(rule, origin="start_day").agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
                "amount": "sum",
            }
        )
        agg = agg.dropna(subset=["open", "close"])
        agg = agg.reset_index().rename(columns={"index": "datetime"})
        # The resample may name the index column "datetime" already
        if "datetime" not in agg.columns:
            agg = agg.rename(columns={agg.columns[0]: "datetime"})
        return agg

    # ------------------------------------------------------------------
    # Signal construction
    # ------------------------------------------------------------------

    def _signal_from_bars(
        self, df: pd.DataFrame, period: str, lookback: int
    ) -> TimeframeSignal:
        """Compute momentum from last *lookback* bars and classify."""
        if df.empty or len(df) < 2:
            return TimeframeSignal(
                period=period, direction="neutral", strength=0.0, momentum=0.0
            )

        actual_lookback = min(lookback, len(df) - 1)
        ref_close = df["close"].iloc[-(actual_lookback + 1)]
        last_close = df["close"].iloc[-1]

        if ref_close <= 0:
            return TimeframeSignal(
                period=period, direction="neutral", strength=0.0, momentum=0.0
            )

        momentum_pct = (last_close - ref_close) / ref_close * 100.0
        return self._classify(momentum_pct, period)

    @staticmethod
    def _classify(momentum_pct: float, period: str) -> TimeframeSignal:
        """Classify momentum into direction + strength."""
        if momentum_pct > 0.3:
            direction = "bullish"
        elif momentum_pct < -0.3:
            direction = "bearish"
        else:
            direction = "neutral"

        strength = min(1.0, abs(momentum_pct) / 2.0)

        return TimeframeSignal(
            period=period,
            direction=direction,
            strength=round(strength, 4),
            momentum=round(momentum_pct, 4),
        )

    # ------------------------------------------------------------------
    # Alignment & confidence
    # ------------------------------------------------------------------

    def _compute_alignment(self, signals: list[TimeframeSignal]) -> float:
        """Weighted pairwise alignment score in [0, 1]."""
        periods = [s.period for s in signals]
        dir_map = {s.period: s.direction for s in signals}
        weight_map = self.WEIGHTS

        total_weight = 0.0
        weighted_sum = 0.0

        for i in range(len(periods)):
            for j in range(i + 1, len(periods)):
                pi, pj = periods[i], periods[j]
                pair_weight = weight_map.get(pi, 0.0) + weight_map.get(pj, 0.0)
                di, dj = dir_map[pi], dir_map[pj]

                if di == dj and di != "neutral":
                    score = 1.0
                elif di == "neutral" or dj == "neutral":
                    score = 0.5
                elif di == dj:  # both neutral
                    score = 0.5
                else:
                    score = 0.0

                weighted_sum += score * pair_weight
                total_weight += pair_weight

        if total_weight <= 0:
            return 0.5

        return weighted_sum / total_weight

    @staticmethod
    def _confirmed_direction(signals: list[TimeframeSignal]) -> str:
        """Determine the overall confirmed direction."""
        bullish = sum(1 for s in signals if s.direction == "bullish")
        bearish = sum(1 for s in signals if s.direction == "bearish")

        if bullish >= 2 and bearish == 0:
            return "bullish"
        if bearish >= 2 and bullish == 0:
            return "bearish"
        if bullish > bearish and bullish >= 2:
            return "bullish"
        if bearish > bullish and bearish >= 2:
            return "bearish"
        return "conflicted"

    @staticmethod
    def _confidence_boost(signals: list[TimeframeSignal]) -> float:
        """Compute confidence adjustment based on alignment pattern."""
        dirs = [s.direction for s in signals]
        bullish = dirs.count("bullish")
        bearish = dirs.count("bearish")
        neutral = dirs.count("neutral")

        # All 4 agree on a direction
        if bullish == 4 or bearish == 4:
            return 0.15

        # 3 of 4 agree (the 4th is neutral or same)
        if bullish == 3 and bearish == 0:
            return 0.10
        if bearish == 3 and bullish == 0:
            return 0.10

        # 2 agree, rest neutral
        if (bullish == 2 and bearish == 0) or (bearish == 2 and bullish == 0):
            if neutral >= 2:
                return 0.05
            return 0.05

        # Short-term vs long-term divergence
        short_dirs = {s.direction for s in signals if s.period in ("5m", "15m")}
        long_dirs = {s.direction for s in signals if s.period in ("30m", "daily")}

        short_non_neutral = short_dirs - {"neutral"}
        long_non_neutral = long_dirs - {"neutral"}

        if (
            short_non_neutral
            and long_non_neutral
            and short_non_neutral != long_non_neutral
        ):
            # Opposing directions across timeframes
            if bullish >= 2 and bearish >= 2:
                return -0.15
            return -0.10

        return 0.0

    @staticmethod
    def _detect_regime(signals: list[TimeframeSignal]) -> str:
        """Detect market regime from signal pattern."""
        sig_5m = next((s for s in signals if s.period == "5m"), None)
        sig_30m = next((s for s in signals if s.period == "30m"), None)

        if sig_5m is None or sig_30m is None:
            return "transitioning"

        # Trending: 5m and 30m same direction, strength > 0.5
        if (
            sig_5m.direction == sig_30m.direction
            and sig_5m.direction != "neutral"
            and sig_5m.strength > 0.5
            and sig_30m.strength > 0.5
        ):
            return "trending"

        # Mean reverting: 5m opposite to 30m
        if (
            sig_5m.direction != "neutral"
            and sig_30m.direction != "neutral"
            and sig_5m.direction != sig_30m.direction
        ):
            return "mean_reverting"

        return "transitioning"

    # ------------------------------------------------------------------
    # Description
    # ------------------------------------------------------------------

    _ARROW_MAP = {"bullish": "\u2191", "bearish": "\u2193", "neutral": "\u2192"}

    def _build_description(
        self,
        signals: list[TimeframeSignal],
        alignment: float,
        regime: str,
    ) -> str:
        """Build a Chinese-language description of the confirmation result."""
        arrows = "/".join(
            f"{s.period}{self._ARROW_MAP.get(s.direction, '?')}" for s in signals
        )

        dirs = [s.direction for s in signals]
        bullish = dirs.count("bullish")
        bearish = dirs.count("bearish")

        if bullish == 4:
            return f"四周期共振看多({arrows})，趋势确认度{alignment:.0%}"
        if bearish == 4:
            return f"四周期共振看空({arrows})，趋势确认度{alignment:.0%}"

        if bullish >= 3 and bearish == 0:
            return f"多周期偏多({arrows})，确认度{alignment:.0%}"
        if bearish >= 3 and bullish == 0:
            return f"多周期偏空({arrows})，确认度{alignment:.0%}"

        if regime == "mean_reverting":
            return f"短期反弹但中期承压({arrows})，均值回归风险"

        if regime == "trending":
            return f"趋势运行中({arrows})，确认度{alignment:.0%}"

        return f"多空分歧({arrows})，方向待确认"

    # ------------------------------------------------------------------
    # Neutral fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _neutral_result(symbol: str) -> MtfConfirmation:
        """Return a neutral result for insufficient data."""
        neutral_signals = [
            TimeframeSignal(period=p, direction="neutral", strength=0.0, momentum=0.0)
            for p in _PERIODS
        ]
        return MtfConfirmation(
            symbol=symbol,
            alignment_score=0.5,
            confirmed_direction="conflicted",
            timeframes=neutral_signals,
            confidence_boost=0.0,
            regime="transitioning",
            description="数据不足，无法进行多周期确认",
        )
