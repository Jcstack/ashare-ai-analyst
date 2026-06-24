"""Intraday pattern detection for A-share trading.

Detects patterns critical for 游资/超短线 decision-making:
- 冲高回落 (high reversal)
- 低开高走 (gap-down rally)
- 尾盘拉升/跳水 (late rally/dump)
- 量价背离 (volume-price divergence)
- VWAP 压制/支撑 (VWAP rejection)
- 缩量 (volume dry-up)
- 开盘冲击 (opening drive)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time as dt_time

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger("agent_loop.intraday_patterns")

__all__ = [
    "IntradayPatternDetector",
    "IntradayPattern",
]


@dataclass
class IntradayPattern:
    """A detected intraday pattern."""

    pattern_type: str  # e.g., "high_reversal", "gap_down_rally"
    symbol: str
    severity: float  # 0-1, how pronounced the pattern is
    direction: str  # "bullish" or "bearish"
    description: str  # Chinese description for plain-language output
    timestamp: str  # When detected (ISO format)
    factors: dict = field(default_factory=dict)  # Supporting data


class IntradayPatternDetector:
    """Detect actionable intraday patterns from minute-level data."""

    def detect_all(
        self,
        symbol: str,
        minute_bars: pd.DataFrame,
        quote: dict,
        prev_close: float | None = None,
    ) -> list[IntradayPattern]:
        """Run all pattern detectors and return matches.

        Args:
            symbol: Stock code
            minute_bars: Today's 5min OHLCV bars with columns
                [datetime, open, high, low, close, volume, amount]
            quote: Current real-time quote with keys:
                   price, open, high, low, prev_close, volume
            prev_close: Previous day's close price (overrides quote if given)

        Returns:
            List of detected patterns, sorted by severity descending.
        """
        if minute_bars is None or minute_bars.empty or len(minute_bars) < 6:
            logger.debug(
                "Insufficient bars for %s (%d), skipping pattern detection",
                symbol,
                0 if minute_bars is None else len(minute_bars),
            )
            return []

        # Ensure datetime column is parsed
        df = minute_bars.copy()
        if not pd.api.types.is_datetime64_any_dtype(df["datetime"]):
            df["datetime"] = pd.to_datetime(df["datetime"])

        # Resolve prev_close
        if prev_close is None:
            prev_close = quote.get("prev_close") if quote else None
        if prev_close is None or prev_close <= 0:
            prev_close = df["open"].iloc[0]

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        current_price = (
            quote["price"] if quote and quote.get("price") else df["close"].iloc[-1]
        )
        open_price = (
            quote["open"] if quote and quote.get("open") else df["open"].iloc[0]
        )
        intraday_high = (
            max(df["high"].max(), quote.get("high", 0)) if quote else df["high"].max()
        )
        intraday_low = (
            min(df["low"].min(), quote.get("low", float("inf")))
            if quote
            else df["low"].min()
        )

        detectors = [
            self._detect_high_reversal,
            self._detect_gap_down_rally,
            self._detect_late_rally,
            self._detect_late_dump,
            self._detect_volume_price_divergence,
            self._detect_vwap_rejection,
            self._detect_volume_dry_up,
            self._detect_opening_drive,
        ]

        patterns: list[IntradayPattern] = []
        ctx = _DetectionContext(
            symbol=symbol,
            df=df,
            current_price=current_price,
            open_price=open_price,
            prev_close=prev_close,
            intraday_high=intraday_high,
            intraday_low=intraday_low,
            now_str=now_str,
        )

        for detector in detectors:
            try:
                result = detector(ctx)
                if result is not None:
                    patterns.append(result)
            except Exception as exc:
                logger.warning(
                    "Pattern detector %s failed for %s: %s",
                    detector.__name__,
                    symbol,
                    exc,
                )

        patterns.sort(key=lambda p: p.severity, reverse=True)
        return patterns

    def detect_batch(
        self,
        symbols_data: dict[str, tuple[pd.DataFrame, dict]],
        prev_closes: dict[str, float] | None = None,
    ) -> dict[str, list[IntradayPattern]]:
        """Detect patterns for multiple symbols.

        Args:
            symbols_data: {symbol: (minute_bars, quote)}
            prev_closes: {symbol: prev_close}

        Returns:
            {symbol: [IntradayPattern, ...]}
        """
        prev_closes = prev_closes or {}
        results: dict[str, list[IntradayPattern]] = {}

        for symbol, (bars, quote) in symbols_data.items():
            try:
                results[symbol] = self.detect_all(
                    symbol, bars, quote, prev_closes.get(symbol)
                )
            except Exception as exc:
                logger.warning("Batch pattern detection failed for %s: %s", symbol, exc)
                results[symbol] = []

        return results

    # ------------------------------------------------------------------
    # Pattern detectors
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_high_reversal(ctx: _DetectionContext) -> IntradayPattern | None:
        """冲高回落 — gapped up 3%+ from open, then fell 3%+ from high."""
        high = ctx.intraday_high
        price = ctx.current_price
        open_price = ctx.open_price

        if open_price <= 0 or high <= 0:
            return None

        # Check if high was at least 3% above open
        if high < open_price * 1.03:
            return None

        # Check if current price has fallen 3%+ from high
        reversal_pct = (high - price) / high * 100
        if reversal_pct < 3.0:
            return None

        severity = min(1.0, reversal_pct / 8.0)

        return IntradayPattern(
            pattern_type="high_reversal",
            symbol=ctx.symbol,
            severity=round(severity, 3),
            direction="bearish",
            description=(
                f"冲高回落 {reversal_pct:.1f}%，最高{high:.2f}→现价{price:.2f}"
            ),
            timestamp=ctx.now_str,
            factors={
                "intraday_high": high,
                "current_price": price,
                "reversal_pct": round(reversal_pct, 2),
            },
        )

    @staticmethod
    def _detect_gap_down_rally(ctx: _DetectionContext) -> IntradayPattern | None:
        """低开高走 — gapped down 2%+ from prev_close, then rallied 2%+ from open."""
        open_price = ctx.open_price
        price = ctx.current_price
        prev_close = ctx.prev_close

        if prev_close <= 0 or open_price <= 0:
            return None

        gap_pct = (open_price - prev_close) / prev_close * 100
        if gap_pct > -2.0:
            return None  # Not a meaningful gap-down

        rally_pct = (price - open_price) / open_price * 100
        if rally_pct < 2.0:
            return None  # Hasn't rallied enough

        severity = min(1.0, rally_pct / 6.0)

        return IntradayPattern(
            pattern_type="gap_down_rally",
            symbol=ctx.symbol,
            severity=round(severity, 3),
            direction="bullish",
            description=(f"低开高走，低开{abs(gap_pct):.1f}%后回升{rally_pct:.1f}%"),
            timestamp=ctx.now_str,
            factors={
                "gap_pct": round(gap_pct, 2),
                "rally_pct": round(rally_pct, 2),
                "open_price": open_price,
                "current_price": price,
            },
        )

    @staticmethod
    def _detect_late_rally(ctx: _DetectionContext) -> IntradayPattern | None:
        """尾盘拉升 — price gain > 1.5% since 14:00 with increasing volume."""
        df = ctx.df
        afternoon_bars = df[df["datetime"].dt.time >= dt_time(14, 0)]

        if len(afternoon_bars) < 2:
            return None

        price_at_14 = afternoon_bars["close"].iloc[0]
        if price_at_14 <= 0:
            return None

        rally_pct = (ctx.current_price - price_at_14) / price_at_14 * 100
        if rally_pct < 1.5:
            return None

        # Check volume trend in afternoon bars
        volumes = afternoon_bars["volume"].values.astype(float)
        x = np.arange(len(volumes), dtype=float)
        x_mean = x.mean()
        denom = np.sum((x - x_mean) ** 2)
        vol_slope = (
            np.sum((x - x_mean) * (volumes - volumes.mean())) / denom
            if denom > 0
            else 0.0
        )
        volume_increasing = vol_slope > 0

        if not volume_increasing:
            return None  # Rally without volume support — skip

        severity = min(1.0, rally_pct / 5.0)

        # Check if stock already up big → distribution warning
        daily_gain_pct = (
            (ctx.current_price - ctx.prev_close) / ctx.prev_close * 100
            if ctx.prev_close > 0
            else 0.0
        )

        if daily_gain_pct > 5.0:
            description = (
                f"尾盘拉升 {rally_pct:.1f}%，全天涨幅已达{daily_gain_pct:.1f}%，"
                "注意尾盘拉高出货可能"
            )
        else:
            description = f"尾盘拉升 {rally_pct:.1f}%，14:00后放量走强"

        return IntradayPattern(
            pattern_type="late_rally",
            symbol=ctx.symbol,
            severity=round(severity, 3),
            direction="bullish",
            description=description,
            timestamp=ctx.now_str,
            factors={
                "rally_pct": round(rally_pct, 2),
                "daily_gain_pct": round(daily_gain_pct, 2),
                "volume_increasing": volume_increasing,
            },
        )

    @staticmethod
    def _detect_late_dump(ctx: _DetectionContext) -> IntradayPattern | None:
        """尾盘跳水 — price drop > 1.5% since 14:00."""
        df = ctx.df
        afternoon_bars = df[df["datetime"].dt.time >= dt_time(14, 0)]

        if len(afternoon_bars) < 2:
            return None

        price_at_14 = afternoon_bars["close"].iloc[0]
        if price_at_14 <= 0:
            return None

        drop_pct = (price_at_14 - ctx.current_price) / price_at_14 * 100
        if drop_pct < 1.5:
            return None

        severity = min(1.0, drop_pct / 5.0)

        return IntradayPattern(
            pattern_type="late_dump",
            symbol=ctx.symbol,
            severity=round(severity, 3),
            direction="bearish",
            description=f"尾盘跳水 {drop_pct:.1f}%，14:00后持续走弱",
            timestamp=ctx.now_str,
            factors={
                "drop_pct": round(drop_pct, 2),
                "price_at_14": price_at_14,
                "current_price": ctx.current_price,
            },
        )

    @staticmethod
    def _detect_volume_price_divergence(
        ctx: _DetectionContext,
    ) -> IntradayPattern | None:
        """量价背离 — price and volume trends diverge over last 6 bars."""
        df = ctx.df
        if len(df) < 6:
            return None

        tail = df.iloc[-6:]
        prices = tail["close"].values.astype(float)
        volumes = tail["volume"].values.astype(float)
        x = np.arange(len(tail), dtype=float)

        x_mean = x.mean()
        denom = np.sum((x - x_mean) ** 2)
        if denom <= 0:
            return None

        price_slope = np.sum((x - x_mean) * (prices - prices.mean())) / denom
        vol_slope = np.sum((x - x_mean) * (volumes - volumes.mean())) / denom

        # Require meaningful slopes (not flat)
        price_range = prices.max() - prices.min()
        if prices.mean() > 0 and price_range / prices.mean() < 0.002:
            return None  # Price essentially flat — no divergence

        # Top divergence: price rising, volume falling
        if price_slope > 0 and vol_slope < 0:
            severity = min(1.0, abs(vol_slope) / max(abs(volumes.mean()), 1.0) * 10)
            return IntradayPattern(
                pattern_type="volume_price_divergence",
                symbol=ctx.symbol,
                severity=round(max(0.3, severity), 3),
                direction="bearish",
                description="量价背离，价格上涨但成交量萎缩，上攻动力不足",
                timestamp=ctx.now_str,
                factors={
                    "price_slope": round(float(price_slope), 6),
                    "volume_slope": round(float(vol_slope), 2),
                    "divergence_type": "top",
                },
            )

        # Bottom divergence: price falling, volume falling (exhaustion)
        if price_slope < 0 and vol_slope < 0:
            severity = min(1.0, abs(vol_slope) / max(abs(volumes.mean()), 1.0) * 8)
            if severity < 0.3:
                return None
            return IntradayPattern(
                pattern_type="volume_price_divergence",
                symbol=ctx.symbol,
                severity=round(severity, 3),
                direction="bullish",
                description="缩量下跌，卖压衰竭，可能接近短期底部",
                timestamp=ctx.now_str,
                factors={
                    "price_slope": round(float(price_slope), 6),
                    "volume_slope": round(float(vol_slope), 2),
                    "divergence_type": "bottom_exhaustion",
                },
            )

        return None

    @staticmethod
    def _detect_vwap_rejection(ctx: _DetectionContext) -> IntradayPattern | None:
        """VWAP 压制/支撑 — price tested VWAP 2+ times in last 30min and got rejected."""
        df = ctx.df
        if len(df) < 6:
            return None

        # Compute VWAP
        total_volume = df["volume"].sum()
        if total_volume <= 0:
            return None
        total_amount = df["amount"].sum()
        vwap = total_amount / total_volume

        if vwap <= 0:
            return None

        # Look at last 6 bars (30 min of 5-min bars)
        recent = df.iloc[-6:]
        vwap_threshold = vwap * 0.002  # 0.2% tolerance

        touches_from_below = 0
        touches_from_above = 0

        for _, bar in recent.iterrows():
            bar_high = bar["high"]
            bar_low = bar["low"]
            bar_close = bar["close"]

            # Touch from below: high reached VWAP but close stayed below
            if bar_high >= vwap - vwap_threshold and bar_close < vwap:
                touches_from_below += 1

            # Touch from above: low reached VWAP but close stayed above
            if bar_low <= vwap + vwap_threshold and bar_close > vwap:
                touches_from_above += 1

        if touches_from_below >= 2:
            severity = min(1.0, touches_from_below / 4.0)
            return IntradayPattern(
                pattern_type="vwap_rejection",
                symbol=ctx.symbol,
                severity=round(severity, 3),
                direction="bearish",
                description=(
                    f"VWAP({vwap:.2f})压制，30分钟内{touches_from_below}次冲击未能突破"
                ),
                timestamp=ctx.now_str,
                factors={
                    "vwap": round(vwap, 2),
                    "touches": touches_from_below,
                    "rejection_side": "below",
                },
            )

        if touches_from_above >= 2:
            severity = min(1.0, touches_from_above / 4.0)
            return IntradayPattern(
                pattern_type="vwap_rejection",
                symbol=ctx.symbol,
                severity=round(severity, 3),
                direction="bullish",
                description=(
                    f"VWAP({vwap:.2f})支撑有效，"
                    f"30分钟内{touches_from_above}次回踩获支撑"
                ),
                timestamp=ctx.now_str,
                factors={
                    "vwap": round(vwap, 2),
                    "touches": touches_from_above,
                    "rejection_side": "above",
                },
            )

        return None

    @staticmethod
    def _detect_volume_dry_up(ctx: _DetectionContext) -> IntradayPattern | None:
        """缩量 — last 30min volume < 50% of morning average."""
        df = ctx.df

        morning = df[
            (df["datetime"].dt.time >= dt_time(9, 30))
            & (df["datetime"].dt.time < dt_time(11, 30))
        ]
        if len(morning) < 6:
            return None

        # Average 30-min volume in the morning (per 6-bar window)
        morning_avg_30m = morning["volume"].sum() / max(len(morning) / 6.0, 1.0)

        # Last 6 bars volume
        recent = df.iloc[-6:]
        recent_vol = recent["volume"].sum()

        if morning_avg_30m <= 0:
            return None

        ratio = recent_vol / morning_avg_30m
        if ratio >= 0.5:
            return None  # Volume not significantly dried up

        severity = min(1.0, (0.5 - ratio) / 0.4)

        # Determine direction based on price position
        price = ctx.current_price
        high = ctx.intraday_high
        low = ctx.intraday_low
        price_range = high - low if high > low else 1.0
        price_position = (price - low) / price_range  # 0 = at low, 1 = at high

        if price_position > 0.7:
            direction = "bearish"
            description = (
                f"高位缩量，近30分钟成交量仅为早盘的{ratio * 100:.0f}%，"
                "上攻乏力警惕回落"
            )
        elif price_position < 0.3:
            direction = "bullish"
            description = (
                f"低位缩量，近30分钟成交量仅为早盘的{ratio * 100:.0f}%，"
                "卖压减弱可能企稳"
            )
        else:
            direction = "bearish"
            description = (
                f"成交缩量，近30分钟成交量仅为早盘的{ratio * 100:.0f}%，观望情绪浓厚"
            )

        return IntradayPattern(
            pattern_type="volume_dry_up",
            symbol=ctx.symbol,
            severity=round(severity, 3),
            direction=direction,
            description=description,
            timestamp=ctx.now_str,
            factors={
                "volume_ratio": round(ratio, 3),
                "price_position": round(price_position, 3),
            },
        )

    @staticmethod
    def _detect_opening_drive(ctx: _DetectionContext) -> IntradayPattern | None:
        """开盘冲击 — first 30min shows >3% move from open."""
        df = ctx.df
        open_price = ctx.open_price

        if open_price <= 0:
            return None

        # Bars in 09:30-10:00
        opening_bars = df[df["datetime"].dt.time <= dt_time(10, 0)]
        if len(opening_bars) < 2:
            return None

        price_at_10 = opening_bars["close"].iloc[-1]
        drive_pct = (price_at_10 - open_price) / open_price * 100

        if abs(drive_pct) < 3.0:
            return None

        # Check volume trend in opening bars
        volumes = opening_bars["volume"].values.astype(float)
        x = np.arange(len(volumes), dtype=float)
        x_mean = x.mean()
        denom = np.sum((x - x_mean) ** 2)
        vol_slope = (
            np.sum((x - x_mean) * (volumes - volumes.mean())) / denom
            if denom > 0
            else 0.0
        )
        volume_declining = vol_slope < 0

        severity = min(1.0, abs(drive_pct) / 6.0)

        if drive_pct > 0:
            if volume_declining:
                direction = "bearish"
                description = f"开盘30分钟冲高{drive_pct:.1f}%但量能递减，警惕冲高回落"
            else:
                direction = "bullish"
                description = f"开盘30分钟放量上攻{drive_pct:.1f}%，多头动能强劲"
        else:
            direction = "bearish"
            description = f"开盘30分钟下杀{abs(drive_pct):.1f}%，空头主导"

        return IntradayPattern(
            pattern_type="opening_drive",
            symbol=ctx.symbol,
            severity=round(severity, 3),
            direction=direction,
            description=description,
            timestamp=ctx.now_str,
            factors={
                "drive_pct": round(drive_pct, 2),
                "volume_declining": volume_declining,
            },
        )


# ---------------------------------------------------------------------------
# Internal context dataclass
# ---------------------------------------------------------------------------


@dataclass
class _DetectionContext:
    """Shared context passed to all pattern detectors."""

    symbol: str
    df: pd.DataFrame
    current_price: float
    open_price: float
    prev_close: float
    intraday_high: float
    intraday_low: float
    now_str: str
