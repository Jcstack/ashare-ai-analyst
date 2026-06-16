"""Rule-based alert engine for stock anomaly detection.

Detects unusual patterns like volume spikes, limit proximity, MA crossovers,
RSI extremes, and Bollinger breakouts using configurable thresholds.

Per PRD v2.0 FR-AD002.
"""

import time
import uuid
from typing import Any

import pandas as pd

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("analysis.alerts")


class AlertEngine:
    """Rule-based alert engine with configurable thresholds.

    Checks multiple technical conditions and generates alerts
    with severity levels.

    Args:
        config_name: Config file name for thresholds.
    """

    def __init__(self, config_name: str = "agent") -> None:
        config = load_config(config_name)
        anomaly_cfg = config.get("anomaly", {})
        self._volume_spike_threshold: float = anomaly_cfg.get(
            "volume_spike_threshold", 2.0
        )
        self._price_limit_proximity: float = anomaly_cfg.get(
            "price_limit_proximity", 0.02
        )
        self._rsi_overbought: float = anomaly_cfg.get("rsi_overbought", 80)
        self._rsi_oversold: float = anomaly_cfg.get("rsi_oversold", 20)
        self._ma_cross_periods: list[int] = anomaly_cfg.get("ma_cross_periods", [5, 20])
        self._bb_period: int = anomaly_cfg.get("bollinger_period", 20)
        self._bb_std: float = anomaly_cfg.get("bollinger_std", 2.0)

    def check_alerts(
        self,
        symbol: str,
        name: str,
        quote: dict[str, Any] | None = None,
        indicators: dict[str, Any] | None = None,
        ohlcv_df: pd.DataFrame | None = None,
        board: str = "main",
    ) -> list[dict[str, Any]]:
        """Run all alert checks for a stock.

        Args:
            symbol: 6-digit stock code.
            name: Stock name.
            quote: Real-time quote data.
            indicators: Technical indicator values.
            ohlcv_df: Historical OHLCV DataFrame.
            board: Board type (main/chinext/star).

        Returns:
            List of alert dicts with type, severity, title, description.
        """
        alerts: list[dict[str, Any]] = []

        if quote:
            alerts.extend(self._check_price_limit(symbol, name, quote, board))
        if indicators:
            alerts.extend(self._check_rsi_extreme(symbol, name, indicators))
            alerts.extend(self._check_ma_crossover(symbol, name, indicators))
            alerts.extend(
                self._check_bollinger_breakout(symbol, name, indicators, quote)
            )
        if ohlcv_df is not None and not ohlcv_df.empty:
            alerts.extend(self._check_volume_spike(symbol, name, quote, ohlcv_df))

        return alerts

    def _check_volume_spike(
        self,
        symbol: str,
        name: str,
        quote: dict[str, Any] | None,
        ohlcv_df: pd.DataFrame,
    ) -> list[dict[str, Any]]:
        """Check if current volume is abnormally high."""
        alerts = []
        if "volume" not in ohlcv_df.columns or len(ohlcv_df) < 20:
            return alerts

        avg_vol_20 = ohlcv_df["volume"].tail(20).mean()
        current_vol = quote.get("volume") if quote else None
        if current_vol and avg_vol_20 and avg_vol_20 > 0:
            ratio = float(current_vol) / float(avg_vol_20)
            if ratio >= self._volume_spike_threshold:
                alerts.append(
                    self._make_alert(
                        symbol=symbol,
                        name=name,
                        alert_type="volume_spike",
                        severity="warning" if ratio < 3.0 else "critical",
                        title=f"成交量异常放大 ({ratio:.1f}倍)",
                        description=f"当前成交量是20日均量的{ratio:.1f}倍，超过{self._volume_spike_threshold}倍阈值",
                        value=ratio,
                        threshold=self._volume_spike_threshold,
                    )
                )
        return alerts

    def _check_price_limit(
        self,
        symbol: str,
        name: str,
        quote: dict[str, Any],
        board: str,
    ) -> list[dict[str, Any]]:
        """Check if price is near daily limit."""
        alerts = []
        price = quote.get("price")
        prev_close = quote.get("prev_close")
        if not price or not prev_close or prev_close == 0:
            return alerts

        limit_pct = 0.20 if board in ("chinext", "star") else 0.10
        limit_up = prev_close * (1 + limit_pct)
        limit_down = prev_close * (1 - limit_pct)

        up_distance = (limit_up - price) / limit_up if limit_up > 0 else 1
        down_distance = (price - limit_down) / price if price > 0 else 1

        if up_distance <= self._price_limit_proximity:
            alerts.append(
                self._make_alert(
                    symbol=symbol,
                    name=name,
                    alert_type="near_limit_up",
                    severity="critical",
                    title=f"接近涨停 (距离{up_distance * 100:.1f}%)",
                    description=f"当前价{price:.2f}，涨停价{limit_up:.2f}",
                    value=up_distance,
                    threshold=self._price_limit_proximity,
                )
            )
        elif down_distance <= self._price_limit_proximity:
            alerts.append(
                self._make_alert(
                    symbol=symbol,
                    name=name,
                    alert_type="near_limit_down",
                    severity="critical",
                    title=f"接近跌停 (距离{down_distance * 100:.1f}%)",
                    description=f"当前价{price:.2f}，跌停价{limit_down:.2f}",
                    value=down_distance,
                    threshold=self._price_limit_proximity,
                )
            )
        return alerts

    def _check_rsi_extreme(
        self,
        symbol: str,
        name: str,
        indicators: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Check for RSI overbought/oversold conditions."""
        alerts = []
        rsi = indicators.get("rsi") or indicators.get("rsi_14")
        if rsi is None:
            return alerts

        rsi_val = float(rsi) if not isinstance(rsi, dict) else None
        if rsi_val is None:
            return alerts

        if rsi_val >= self._rsi_overbought:
            alerts.append(
                self._make_alert(
                    symbol=symbol,
                    name=name,
                    alert_type="rsi_overbought",
                    severity="warning",
                    title=f"RSI超买 ({rsi_val:.1f})",
                    description=f"RSI={rsi_val:.1f}，超过{self._rsi_overbought}超买阈值",
                    value=rsi_val,
                    threshold=self._rsi_overbought,
                )
            )
        elif rsi_val <= self._rsi_oversold:
            alerts.append(
                self._make_alert(
                    symbol=symbol,
                    name=name,
                    alert_type="rsi_oversold",
                    severity="warning",
                    title=f"RSI超卖 ({rsi_val:.1f})",
                    description=f"RSI={rsi_val:.1f}，低于{self._rsi_oversold}超卖阈值",
                    value=rsi_val,
                    threshold=self._rsi_oversold,
                )
            )
        return alerts

    def _check_ma_crossover(
        self,
        symbol: str,
        name: str,
        indicators: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Check for golden/death cross between MAs."""
        alerts = []
        short_period, long_period = self._ma_cross_periods
        ma_short = indicators.get(f"sma_{short_period}") or indicators.get(
            f"ma{short_period}"
        )
        ma_long = indicators.get(f"sma_{long_period}") or indicators.get(
            f"ma{long_period}"
        )

        if ma_short is None or ma_long is None:
            return alerts

        ma_s = float(ma_short) if not isinstance(ma_short, dict) else None
        ma_l = float(ma_long) if not isinstance(ma_long, dict) else None
        if ma_s is None or ma_l is None:
            return alerts

        diff_pct = (ma_s - ma_l) / ma_l * 100 if ma_l != 0 else 0

        if 0 < diff_pct < 1.0:
            alerts.append(
                self._make_alert(
                    symbol=symbol,
                    name=name,
                    alert_type="golden_cross",
                    severity="info",
                    title=f"MA{short_period}上穿MA{long_period} (金叉)",
                    description=f"MA{short_period}={ma_s:.2f} 上穿 MA{long_period}={ma_l:.2f}",
                    value=diff_pct,
                    threshold=0.0,
                )
            )
        elif -1.0 < diff_pct < 0:
            alerts.append(
                self._make_alert(
                    symbol=symbol,
                    name=name,
                    alert_type="death_cross",
                    severity="warning",
                    title=f"MA{short_period}下穿MA{long_period} (死叉)",
                    description=f"MA{short_period}={ma_s:.2f} 下穿 MA{long_period}={ma_l:.2f}",
                    value=diff_pct,
                    threshold=0.0,
                )
            )
        return alerts

    def _check_bollinger_breakout(
        self,
        symbol: str,
        name: str,
        indicators: dict[str, Any],
        quote: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Check for Bollinger Band breakout."""
        alerts = []
        bb_upper = indicators.get("bb_upper") or indicators.get("bollinger_upper")
        bb_lower = indicators.get("bb_lower") or indicators.get("bollinger_lower")
        price = quote.get("price") if quote else None

        if bb_upper is None or bb_lower is None or price is None:
            return alerts

        bb_u = float(bb_upper) if not isinstance(bb_upper, dict) else None
        bb_l = float(bb_lower) if not isinstance(bb_lower, dict) else None
        if bb_u is None or bb_l is None:
            return alerts

        if price > bb_u:
            alerts.append(
                self._make_alert(
                    symbol=symbol,
                    name=name,
                    alert_type="bb_breakout_upper",
                    severity="warning",
                    title="突破布林带上轨",
                    description=f"当前价{price:.2f}突破布林带上轨{bb_u:.2f}",
                    value=price,
                    threshold=bb_u,
                )
            )
        elif price < bb_l:
            alerts.append(
                self._make_alert(
                    symbol=symbol,
                    name=name,
                    alert_type="bb_breakout_lower",
                    severity="warning",
                    title="跌破布林带下轨",
                    description=f"当前价{price:.2f}跌破布林带下轨{bb_l:.2f}",
                    value=price,
                    threshold=bb_l,
                )
            )
        return alerts

    @staticmethod
    def _make_alert(
        symbol: str,
        name: str,
        alert_type: str,
        severity: str,
        title: str,
        description: str,
        value: float | None = None,
        threshold: float | None = None,
    ) -> dict[str, Any]:
        """Create a standardized alert dict."""
        return {
            "id": str(uuid.uuid4())[:8],
            "symbol": symbol,
            "name": name,
            "alert_type": alert_type,
            "severity": severity,
            "title": title,
            "description": description,
            "value": value,
            "threshold": threshold,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
