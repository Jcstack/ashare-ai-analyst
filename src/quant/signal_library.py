"""Declarative signal library for technical trading signals.

Defines signals via YAML config and evaluates them against market data.
Signals produce buy/sell/neutral outputs with confidence scores.

Part of v15.0 Quant Core layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("quant.signal_library")


@dataclass
class SignalDefinition:
    """Definition of a trading signal loaded from config.

    Attributes:
        name: Signal identifier (e.g. "ma_cross").
        description: Human-readable description.
        signal_type: Category (momentum, mean_reversion, volatility, volume).
        params: Signal-specific parameters from config.
    """

    name: str
    description: str = ""
    signal_type: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class SignalResult:
    """Result of evaluating a single signal.

    Attributes:
        signal_name: Which signal produced this result.
        signal_type: Signal category.
        direction: "bullish", "bearish", or "neutral".
        strength: Confidence/strength score in [0, 1].
        value: Raw indicator value that triggered the signal.
        description: Human-readable explanation.
    """

    signal_name: str = ""
    signal_type: str = ""
    direction: str = "neutral"
    strength: float = 0.0
    value: float = 0.0
    description: str = ""


@dataclass
class SignalSummary:
    """Aggregated signal evaluation results.

    Attributes:
        signals: Individual signal results.
        bullish_count: Number of bullish signals.
        bearish_count: Number of bearish signals.
        neutral_count: Number of neutral signals.
        net_score: Aggregated score (-1 to +1, positive = bullish).
        consensus: Overall direction based on majority.
        summary: Human-readable summary.
    """

    signals: list[SignalResult] = field(default_factory=list)
    bullish_count: int = 0
    bearish_count: int = 0
    neutral_count: int = 0
    net_score: float = 0.0
    consensus: str = "neutral"
    summary: str = ""


class SignalLibrary:
    """Evaluates trading signals from YAML-defined rules.

    Usage::

        library = SignalLibrary()
        summary = library.evaluate(closes=close_series, volumes=vol_series)
        print(summary.consensus, summary.net_score)
    """

    def __init__(self) -> None:
        cfg = load_config("quant").get("signal_library", {})
        self.lookback = cfg.get("default_lookback_days", 60)
        self.definitions: dict[str, SignalDefinition] = {}

        for name, signal_cfg in cfg.get("signals", {}).items():
            self.definitions[name] = SignalDefinition(
                name=name,
                description=signal_cfg.get("description", ""),
                signal_type=signal_cfg.get("signal_type", ""),
                params={
                    k: v
                    for k, v in signal_cfg.items()
                    if k not in ("description", "signal_type")
                },
            )

        # Common abbreviation aliases (LLM often uses these)
        self._aliases: dict[str, str] = {
            "MA": "ma_cross",
            "MACD": "macd_divergence",
            "RSI": "rsi_extreme",
            "KDJ": "rsi_extreme",  # closest equivalent
            "BOLL": "bollinger_squeeze",
            "VOL": "volume_breakout",
        }

    def evaluate(
        self,
        closes: list[float] | pd.Series,
        volumes: list[float] | pd.Series | None = None,
        signal_names: list[str] | None = None,
    ) -> SignalSummary:
        """Evaluate signals against price/volume data.

        Args:
            closes: Daily closing prices.
            volumes: Daily volumes (optional, needed for volume signals).
            signal_names: Specific signals to evaluate (None = all).

        Returns:
            SignalSummary with individual and aggregated results.
        """
        close_s = closes if isinstance(closes, pd.Series) else pd.Series(closes)
        vol_s = None
        if volumes is not None:
            vol_s = volumes if isinstance(volumes, pd.Series) else pd.Series(volumes)

        if len(close_s) < 2:
            return SignalSummary(summary="Insufficient price data")

        names = signal_names or list(self.definitions.keys())
        results: list[SignalResult] = []

        for name in names:
            # Resolve common abbreviations (MA → ma_cross, etc.)
            resolved = self._aliases.get(name, name)
            defn = self.definitions.get(resolved)
            if defn is None:
                logger.warning("Unknown signal: %s", name)
                continue

            result = self._evaluate_signal(defn, close_s, vol_s)
            if result is not None:
                results.append(result)

        return _aggregate_signals(results)

    def list_signals(self) -> list[SignalDefinition]:
        """Return all registered signal definitions."""
        return list(self.definitions.values())

    def _evaluate_signal(
        self,
        defn: SignalDefinition,
        closes: pd.Series,
        volumes: pd.Series | None,
    ) -> SignalResult | None:
        """Dispatch signal evaluation to the appropriate handler."""
        handlers = {
            "ma_cross": _eval_ma_cross,
            "rsi_extreme": _eval_rsi_extreme,
            "bollinger_squeeze": _eval_bollinger_squeeze,
            "volume_breakout": _eval_volume_breakout,
            "macd_divergence": _eval_macd_divergence,
            "sentiment_shift": _eval_sentiment_shift,
            "policy_shock": _eval_policy_shock,
            "correlation_break": _eval_correlation_break,
            "regime_change": _eval_regime_change,
        }
        handler = handlers.get(defn.name)
        if handler is None:
            logger.debug("No handler for signal: %s", defn.name)
            return None
        return handler(defn, closes, volumes)


# ---------------------------------------------------------------------------
# Signal Evaluators
# ---------------------------------------------------------------------------


def _eval_ma_cross(
    defn: SignalDefinition,
    closes: pd.Series,
    _volumes: pd.Series | None,
) -> SignalResult:
    """Moving average crossover signal."""
    fast = defn.params.get("fast_period", 5)
    slow = defn.params.get("slow_period", 20)

    if len(closes) < slow + 1:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            description="Insufficient data",
        )

    ma_fast = closes.rolling(fast).mean()
    ma_slow = closes.rolling(slow).mean()

    current_fast = ma_fast.iloc[-1]
    current_slow = ma_slow.iloc[-1]
    prev_fast = ma_fast.iloc[-2]
    prev_slow = ma_slow.iloc[-2]

    if np.isnan(current_fast) or np.isnan(current_slow):
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            description="Insufficient data",
        )

    # Golden cross: fast crosses above slow
    if prev_fast <= prev_slow and current_fast > current_slow:
        spread = (current_fast - current_slow) / current_slow
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction="bullish",
            strength=min(1.0, abs(spread) * 20),
            value=float(current_fast - current_slow),
            description=f"MA{fast} crossed above MA{slow} (golden cross)",
        )
    # Death cross: fast crosses below slow
    elif prev_fast >= prev_slow and current_fast < current_slow:
        spread = (current_slow - current_fast) / current_slow
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction="bearish",
            strength=min(1.0, abs(spread) * 20),
            value=float(current_fast - current_slow),
            description=f"MA{fast} crossed below MA{slow} (death cross)",
        )
    else:
        spread = (
            (current_fast - current_slow) / current_slow if current_slow != 0 else 0
        )
        direction = (
            "bullish"
            if current_fast > current_slow
            else "bearish"
            if current_fast < current_slow
            else "neutral"
        )
        base_strength = min(1.0, abs(spread) * 10)

        # Persistence boost: count how many recent bars maintain the same ordering
        persistence_lookback = defn.params.get("persistence_lookback", 10)
        persistence_max_boost = defn.params.get("persistence_max_boost", 0.5)
        lookback = min(persistence_lookback, len(ma_fast) - 1)
        consistent_bars = 0
        for i in range(1, lookback + 1):
            f_val = ma_fast.iloc[-i]
            s_val = ma_slow.iloc[-i]
            if np.isnan(f_val) or np.isnan(s_val):
                break
            if direction == "bullish" and f_val > s_val:
                consistent_bars += 1
            elif direction == "bearish" and f_val < s_val:
                consistent_bars += 1
            else:
                break
        if lookback > 0:
            persistence_boost = min(
                persistence_max_boost,
                consistent_bars / persistence_lookback * persistence_max_boost,
            )
        else:
            persistence_boost = 0.0
        strength = min(1.0, base_strength + persistence_boost)

        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction=direction,
            strength=strength,
            value=float(spread),
            description=f"MA{fast} {'above' if current_fast > current_slow else 'below'} MA{slow} ({consistent_bars} bars)",
        )


def _eval_rsi_extreme(
    defn: SignalDefinition,
    closes: pd.Series,
    _volumes: pd.Series | None,
) -> SignalResult:
    """RSI overbought/oversold signal."""
    period = defn.params.get("period", 14)
    overbought = defn.params.get("overbought", 70)
    oversold = defn.params.get("oversold", 30)

    if len(closes) < period + 1:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            description="Insufficient data",
        )

    rsi = _compute_rsi(closes, period)
    if np.isnan(rsi):
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            description="RSI computation failed",
        )

    if rsi >= overbought:
        strength = min(1.0, (rsi - overbought) / (100 - overbought))
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction="bearish",
            strength=strength,
            value=float(rsi),
            description=f"RSI({period})={rsi:.1f} — overbought (>{overbought})",
        )
    elif rsi <= oversold:
        strength = min(1.0, (oversold - rsi) / oversold)
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction="bullish",
            strength=strength,
            value=float(rsi),
            description=f"RSI({period})={rsi:.1f} — oversold (<{oversold})",
        )
    else:
        # Mid-range direction: compare current RSI to lookback bars ago
        mid_lookback = defn.params.get("mid_range_lookback", 5)
        mid_max_strength = defn.params.get("mid_range_max_strength", 0.6)
        direction = "neutral"
        strength = 0.0

        if len(closes) >= period + mid_lookback + 1:
            prev_rsi = _compute_rsi(closes.iloc[:-mid_lookback], period)
            if not np.isnan(prev_rsi):
                rsi_falling = rsi < prev_rsi
                rsi_rising = rsi > prev_rsi
                if rsi < 50 and rsi_falling:
                    direction = "bearish"
                    strength = min(mid_max_strength, (50 - rsi) / 40)
                elif rsi > 50 and rsi_rising:
                    direction = "bullish"
                    strength = min(mid_max_strength, (rsi - 50) / 40)
                elif rsi < 50 and rsi_rising:
                    # Below 50 but recovering — weak bearish at most
                    direction = "bearish"
                    strength = min(mid_max_strength * 0.3, (50 - rsi) / 80)
                elif rsi > 50 and rsi_falling:
                    # Above 50 but declining — weak bullish at most
                    direction = "bullish"
                    strength = min(mid_max_strength * 0.3, (rsi - 50) / 80)

        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction=direction,
            strength=strength,
            value=float(rsi),
            description=f"RSI({period})={rsi:.1f} — mid-range {'↓' if direction == 'bearish' else '↑' if direction == 'bullish' else '—'}",
        )


def _eval_bollinger_squeeze(
    defn: SignalDefinition,
    closes: pd.Series,
    _volumes: pd.Series | None,
) -> SignalResult:
    """Bollinger Band squeeze breakout signal."""
    period = defn.params.get("period", 20)
    std_dev = defn.params.get("std_dev", 2.0)
    squeeze_threshold = defn.params.get("squeeze_threshold", 0.05)

    if len(closes) < period:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            description="Insufficient data",
        )

    ma = closes.rolling(period).mean()
    std = closes.rolling(period).std()
    upper = ma + std_dev * std
    lower = ma - std_dev * std

    current_price = closes.iloc[-1]
    current_upper = upper.iloc[-1]
    current_lower = lower.iloc[-1]
    current_ma = ma.iloc[-1]

    if np.isnan(current_upper) or np.isnan(current_lower) or current_ma == 0:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            description="Insufficient data",
        )

    bandwidth = (current_upper - current_lower) / current_ma
    is_squeeze = bandwidth < squeeze_threshold

    if is_squeeze:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction="neutral",
            strength=0.8,
            value=float(bandwidth),
            description=f"Bollinger squeeze detected (BW={bandwidth:.3f} < {squeeze_threshold}), breakout imminent",
        )
    elif current_price > current_upper:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction="bullish",
            strength=min(1.0, (current_price - current_upper) / current_upper * 20),
            value=float(bandwidth),
            description="Price broke above upper Bollinger Band",
        )
    elif current_price < current_lower:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction="bearish",
            strength=min(1.0, (current_lower - current_price) / current_lower * 20),
            value=float(bandwidth),
            description="Price broke below lower Bollinger Band",
        )
    else:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction="neutral",
            strength=0.0,
            value=float(bandwidth),
            description=f"Price within Bollinger Bands (BW={bandwidth:.3f})",
        )


def _eval_volume_breakout(
    defn: SignalDefinition,
    closes: pd.Series,
    volumes: pd.Series | None,
) -> SignalResult:
    """Volume surge above average signal."""
    period = defn.params.get("period", 20)
    multiplier = defn.params.get("multiplier", 2.0)

    if volumes is None or len(volumes) < period:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            description="No volume data",
        )

    avg_vol = volumes.rolling(period).mean().iloc[-1]
    current_vol = volumes.iloc[-1]

    if np.isnan(avg_vol) or avg_vol == 0:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            description="Insufficient volume data",
        )

    vol_ratio = current_vol / avg_vol

    if vol_ratio >= multiplier:
        # Volume breakout — direction depends on price movement
        price_change = (
            (closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2]
            if len(closes) >= 2 and closes.iloc[-2] != 0
            else 0
        )
        direction = (
            "bullish"
            if price_change > 0
            else "bearish"
            if price_change < 0
            else "neutral"
        )
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction=direction,
            strength=min(1.0, (vol_ratio - 1) / multiplier),
            value=float(vol_ratio),
            description=f"Volume surge {vol_ratio:.1f}x average ({'>'}={multiplier}x threshold)",
        )
    else:
        # Distribution / accumulation day detection at lower threshold
        dist_threshold = defn.params.get("distribution_vol_threshold", 1.3)
        dist_decline = defn.params.get("distribution_price_decline", -0.005)
        if vol_ratio >= dist_threshold and len(closes) >= 2 and closes.iloc[-2] != 0:
            price_change = (closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2]
            if price_change <= dist_decline:
                return SignalResult(
                    signal_name=defn.name,
                    signal_type=defn.signal_type,
                    direction="bearish",
                    strength=min(1.0, (vol_ratio - 1) / multiplier * 0.7),
                    value=float(vol_ratio),
                    description=f"Distribution day: vol {vol_ratio:.1f}x avg, price {price_change:+.1%}",
                )
            elif price_change >= -dist_decline:
                return SignalResult(
                    signal_name=defn.name,
                    signal_type=defn.signal_type,
                    direction="bullish",
                    strength=min(1.0, (vol_ratio - 1) / multiplier * 0.7),
                    value=float(vol_ratio),
                    description=f"Accumulation day: vol {vol_ratio:.1f}x avg, price {price_change:+.1%}",
                )

        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction="neutral",
            strength=0.0,
            value=float(vol_ratio),
            description=f"Volume normal ({vol_ratio:.1f}x average)",
        )


def _eval_macd_divergence(
    defn: SignalDefinition,
    closes: pd.Series,
    _volumes: pd.Series | None,
) -> SignalResult:
    """MACD histogram divergence signal."""
    fast = defn.params.get("fast", 12)
    slow = defn.params.get("slow", 26)
    signal_period = defn.params.get("signal", 9)

    if len(closes) < slow + signal_period:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            description="Insufficient data",
        )

    ema_fast = closes.ewm(span=fast, adjust=False).mean()
    ema_slow = closes.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line

    current_hist = histogram.iloc[-1]
    prev_hist = histogram.iloc[-2]

    if np.isnan(current_hist) or np.isnan(prev_hist):
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            description="MACD computation failed",
        )

    # Histogram crossover
    if prev_hist <= 0 and current_hist > 0:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction="bullish",
            strength=min(1.0, abs(current_hist) * 100),
            value=float(current_hist),
            description="MACD histogram turned positive (bullish momentum)",
        )
    elif prev_hist >= 0 and current_hist < 0:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction="bearish",
            strength=min(1.0, abs(current_hist) * 100),
            value=float(current_hist),
            description="MACD histogram turned negative (bearish momentum)",
        )
    else:
        direction = (
            "bullish"
            if current_hist > 0
            else "bearish"
            if current_hist < 0
            else "neutral"
        )
        base_strength = min(1.0, abs(current_hist) * 50)

        # Histogram trend: check last 3 bars for expanding/shrinking momentum
        if len(histogram) >= 3:
            h3 = [abs(float(histogram.iloc[-i])) for i in range(1, 4)]
            # h3[0] = current, h3[1] = prev, h3[2] = prev-prev
            if h3[0] < h3[1] < h3[2]:
                # Shrinking — momentum exhaustion
                base_strength *= 0.5
            elif h3[0] > h3[1] > h3[2]:
                # Expanding — momentum building
                base_strength = min(1.0, base_strength * 1.3)

        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction=direction,
            strength=base_strength,
            value=float(current_hist),
            description=f"MACD histogram {'positive' if current_hist > 0 else 'negative'} ({current_hist:.4f})",
        )


def _eval_sentiment_shift(
    defn: SignalDefinition,
    closes: pd.Series,
    _volumes: pd.Series | None,
) -> SignalResult:
    """Detect sentiment shift via divergence between recent and prior price momentum.

    Uses price momentum as a proxy for sentiment. When the short-term momentum
    diverges significantly from the longer-term average, it indicates a sentiment
    shift in the market.
    """
    short_window = defn.params.get("short_window", 5)
    long_window = defn.params.get("long_window", 20)
    threshold = defn.params.get("threshold", 0.02)

    min_required = long_window + 1
    if len(closes) < min_required:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            description="Insufficient data",
        )

    # Compute returns as sentiment proxy
    returns = closes.pct_change().dropna()
    if len(returns) < long_window:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            description="Insufficient data for sentiment computation",
        )

    recent_avg = returns.iloc[-short_window:].mean()
    prior_avg = returns.iloc[-long_window:-short_window].mean()
    sentiment_delta = recent_avg - prior_avg

    if np.isnan(sentiment_delta):
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            description="Sentiment computation failed",
        )

    if sentiment_delta > threshold:
        strength = min(1.0, sentiment_delta / (threshold * 3))
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction="bullish",
            strength=strength,
            value=float(sentiment_delta),
            description=f"Positive sentiment shift detected (delta={sentiment_delta:.4f} > {threshold})",
        )
    elif sentiment_delta < -threshold:
        strength = min(1.0, abs(sentiment_delta) / (threshold * 3))
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction="bearish",
            strength=strength,
            value=float(sentiment_delta),
            description=f"Negative sentiment shift detected (delta={sentiment_delta:.4f} < -{threshold})",
        )
    else:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction="neutral",
            strength=0.0,
            value=float(sentiment_delta),
            description=f"No significant sentiment shift (delta={sentiment_delta:.4f})",
        )


def _eval_policy_shock(
    defn: SignalDefinition,
    closes: pd.Series,
    volumes: pd.Series | None,
) -> SignalResult:
    """Detect unusual policy-driven moves.

    Identifies days where the price move exceeds a multiple of the normal daily
    range, especially on low-volume days which suggest news/policy catalysts
    rather than organic trading activity.
    """
    lookback = defn.params.get("lookback", 20)
    move_multiplier = defn.params.get("move_multiplier", 2.0)
    volume_low_pct = defn.params.get("volume_low_percentile", 0.4)

    if len(closes) < lookback + 1:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            description="Insufficient data",
        )

    daily_returns = closes.pct_change().dropna()
    if len(daily_returns) < lookback:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            description="Insufficient data for policy shock detection",
        )

    avg_range = daily_returns.iloc[-lookback:].abs().mean()
    current_move = daily_returns.iloc[-1]

    if np.isnan(avg_range) or avg_range == 0:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            description="Average range computation failed",
        )

    move_ratio = abs(current_move) / avg_range

    # Check if volume is low relative to average (policy/news driven)
    is_low_volume = False
    if volumes is not None and len(volumes) >= lookback:
        avg_vol = volumes.iloc[-lookback:].mean()
        current_vol = volumes.iloc[-1]
        if avg_vol > 0 and not np.isnan(avg_vol):
            is_low_volume = current_vol < avg_vol * volume_low_pct

    if move_ratio >= move_multiplier:
        direction = "bullish" if current_move > 0 else "bearish"
        vol_note = (
            " on low volume (possible news/policy catalyst)" if is_low_volume else ""
        )
        strength = min(1.0, (move_ratio - move_multiplier) / move_multiplier + 0.5)
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction=direction,
            strength=strength,
            value=float(move_ratio),
            description=f"Policy shock: price moved {move_ratio:.1f}x normal range{vol_note}",
        )
    else:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction="neutral",
            strength=0.0,
            value=float(move_ratio),
            description=f"Normal price movement ({move_ratio:.1f}x average range)",
        )


def _eval_correlation_break(
    defn: SignalDefinition,
    closes: pd.Series,
    _volumes: pd.Series | None,
) -> SignalResult:
    """Detect when a stock's behaviour diverges from its rolling trend.

    Uses rolling correlation between the stock's returns and a smoothed
    benchmark (its own longer-term moving average returns) to detect when
    short-term price action decouples from the established trend.
    """
    correlation_window = defn.params.get("correlation_window", 20)
    benchmark_window = defn.params.get("benchmark_window", 60)
    deviation_threshold = defn.params.get("deviation_threshold", -0.3)

    min_required = benchmark_window + correlation_window
    if len(closes) < min_required:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            description="Insufficient data",
        )

    returns = closes.pct_change().dropna()
    # Use smoothed returns as a "sector/trend" proxy
    smoothed = returns.rolling(benchmark_window).mean()

    # Rolling correlation between raw returns and the smoothed trend
    rolling_corr = returns.rolling(correlation_window).corr(smoothed)
    current_corr = rolling_corr.iloc[-1]

    if np.isnan(current_corr):
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            description="Correlation computation failed",
        )

    if current_corr < deviation_threshold:
        strength = min(1.0, abs(current_corr - deviation_threshold))
        # Determine direction from recent price action
        recent_return = returns.iloc[-5:].sum()
        direction = (
            "bearish"
            if recent_return < 0
            else "bullish"
            if recent_return > 0
            else "neutral"
        )
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction=direction,
            strength=strength,
            value=float(current_corr),
            description=f"Correlation breakdown detected (corr={current_corr:.3f} < {deviation_threshold})",
        )
    else:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction="neutral",
            strength=0.0,
            value=float(current_corr),
            description=f"Trend correlation normal (corr={current_corr:.3f})",
        )


def _eval_regime_change(
    defn: SignalDefinition,
    closes: pd.Series,
    _volumes: pd.Series | None,
) -> SignalResult:
    """Detect volatility regime changes using rolling volatility and Bollinger Band width.

    Compares recent volatility to its own historical average. A significant
    expansion or contraction signals a regime shift.
    """
    vol_window = defn.params.get("volatility_window", 20)
    lookback = defn.params.get("lookback", 60)
    expansion_threshold = defn.params.get("expansion_threshold", 1.5)
    contraction_threshold = defn.params.get("contraction_threshold", 0.5)
    bb_period = defn.params.get("bb_period", 20)
    bb_std_dev = defn.params.get("bb_std_dev", 2.0)

    min_required = lookback + vol_window
    if len(closes) < min_required:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            description="Insufficient data",
        )

    returns = closes.pct_change().dropna()
    rolling_vol = returns.rolling(vol_window).std()
    avg_vol = rolling_vol.iloc[-lookback:].mean()
    current_vol = rolling_vol.iloc[-1]

    # Bollinger Band width as confirmation
    ma = closes.rolling(bb_period).mean()
    std = closes.rolling(bb_period).std()
    current_ma = ma.iloc[-1]
    current_std = std.iloc[-1]

    if np.isnan(current_vol) or np.isnan(avg_vol) or avg_vol == 0:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            description="Volatility computation failed",
        )

    vol_ratio = current_vol / avg_vol

    # Compute Bollinger bandwidth
    bb_width = float("nan")
    if not np.isnan(current_ma) and current_ma != 0 and not np.isnan(current_std):
        bb_width = (bb_std_dev * 2 * current_std) / current_ma

    if vol_ratio >= expansion_threshold:
        # Volatility expansion regime
        strength = min(
            1.0, (vol_ratio - expansion_threshold) / expansion_threshold + 0.5
        )
        bw_note = f", BB width={bb_width:.4f}" if not np.isnan(bb_width) else ""
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction="bearish",
            strength=strength,
            value=float(vol_ratio),
            description=f"Volatility expansion regime (vol {vol_ratio:.2f}x average{bw_note})",
        )
    elif vol_ratio <= contraction_threshold:
        # Volatility contraction — breakout imminent
        strength = min(
            1.0, (contraction_threshold - vol_ratio) / contraction_threshold + 0.5
        )
        bw_note = f", BB width={bb_width:.4f}" if not np.isnan(bb_width) else ""
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction="neutral",
            strength=strength,
            value=float(vol_ratio),
            description=f"Volatility contraction regime (vol {vol_ratio:.2f}x average{bw_note}), breakout imminent",
        )
    else:
        return SignalResult(
            signal_name=defn.name,
            signal_type=defn.signal_type,
            direction="neutral",
            strength=0.0,
            value=float(vol_ratio),
            description=f"Stable volatility regime (vol {vol_ratio:.2f}x average)",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_rsi(closes: pd.Series, period: int) -> float:
    """Compute RSI for the most recent value."""
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.rolling(period).mean().iloc[-1]
    avg_loss = loss.rolling(period).mean().iloc[-1]

    if np.isnan(avg_gain) or np.isnan(avg_loss):
        return float("nan")
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - 100 / (1 + rs))


def _aggregate_signals(results: list[SignalResult]) -> SignalSummary:
    """Aggregate individual signal results into a summary."""
    if not results:
        return SignalSummary(summary="No signals evaluated")

    bullish = sum(1 for r in results if r.direction == "bullish")
    bearish = sum(1 for r in results if r.direction == "bearish")
    neutral = sum(1 for r in results if r.direction == "neutral")

    # Net score: weighted by strength; neutral signals with zero strength
    # no longer dilute the denominator (fixes systematic bullish bias)
    neutral_weight_factor = 0.5
    consensus_threshold = 0.15
    score = 0.0
    total_weight = 0.0
    for r in results:
        if r.direction == "bullish":
            score += r.strength
            total_weight += 1
        elif r.direction == "bearish":
            score -= r.strength
            total_weight += 1
        else:
            # Zero-strength neutrals don't count; non-zero at reduced weight
            if r.strength > 0:
                total_weight += r.strength * neutral_weight_factor

    net_score = score / total_weight if total_weight > 0 else 0.0
    net_score = max(-1.0, min(1.0, net_score))

    # Consensus by net_score threshold instead of simple majority voting
    if net_score > consensus_threshold:
        consensus = "bullish"
    elif net_score < -consensus_threshold:
        consensus = "bearish"
    else:
        consensus = "neutral"

    summary = f"{len(results)} signals: {bullish} bullish, {bearish} bearish, {neutral} neutral | net={net_score:+.2f} | consensus={consensus}"

    return SignalSummary(
        signals=results,
        bullish_count=bullish,
        bearish_count=bearish,
        neutral_count=neutral,
        net_score=net_score,
        consensus=consensus,
        summary=summary,
    )
