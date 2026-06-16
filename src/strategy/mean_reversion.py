"""Mean-reversion strategy for A-share stock analysis.

Generates buy/sell signals when price deviates significantly from the
Bollinger Band mean, confirmed by RSI extremes and optional volume
checks.  Configuration is loaded from ``config/strategy.yaml`` under the
``mean_reversion`` key.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.analysis.indicators import TechnicalIndicators
from src.strategy.base import (
    SIGNAL_BUY,
    SIGNAL_HOLD,
    SIGNAL_SELL,
    BaseStrategy,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class MeanReversionStrategy(BaseStrategy):
    """Bollinger Band + RSI mean-reversion strategy.

    **Buy signal**: close < BB_lower AND RSI < oversold threshold,
    optionally with above-average volume confirmation.

    **Sell signal**: close > BB_upper AND RSI > overbought threshold.

    Args:
        config_path: Name of the YAML config (without extension).
            Defaults to ``"strategy"``.
    """

    def __init__(self, config_path: str = "strategy") -> None:
        super().__init__(config_path)
        self.strategy_config: dict[str, Any] = self.config.get("mean_reversion", {})
        self.bb_period: int = int(self.strategy_config.get("bb_period", 20))
        self.bb_std: float = self.strategy_config.get("bb_std", 2.0)
        self.rsi_period: int = int(self.strategy_config.get("rsi_period", 14))
        self.rsi_oversold: float = self.strategy_config.get("rsi_oversold", 30)
        self.rsi_overbought: float = self.strategy_config.get("rsi_overbought", 70)
        self.volume_confirm: bool = self.strategy_config.get("volume_confirm", True)
        self.indicators = TechnicalIndicators()
        logger.info(
            "MeanReversionStrategy: bb_period=%d, bb_std=%.1f, "
            "rsi_oversold=%.0f, rsi_overbought=%.0f, volume_confirm=%s",
            self.bb_period,
            self.bb_std,
            self.rsi_oversold,
            self.rsi_overbought,
            self.volume_confirm,
        )

    def get_metadata(self) -> dict[str, Any]:
        """Return mean-reversion strategy metadata."""
        return {
            "name": "均值回归策略",
            "description": "基于布林带和RSI的均值回归策略，价格偏离均值时逆向操作",
            "flow_steps": [
                {
                    "id": "data",
                    "label": "OHLCV数据",
                    "type": "input",
                    "description": "日线行情数据",
                },
                {
                    "id": "bb",
                    "label": f"布林带({self.bb_period},{self.bb_std})",
                    "type": "indicator",
                    "description": f"{self.bb_period}日布林带，{self.bb_std}倍标准差",
                },
                {
                    "id": "rsi",
                    "label": f"RSI({self.rsi_period})",
                    "type": "indicator",
                    "description": f"{self.rsi_period}日相对强弱指数",
                },
                {
                    "id": "volume_check",
                    "label": "成交量确认",
                    "type": "filter",
                    "description": "成交量高于均量确认",
                },
                {
                    "id": "oversold",
                    "label": "超卖判断",
                    "type": "decision",
                    "description": f"价格<下轨 且 RSI<{self.rsi_oversold}",
                },
                {
                    "id": "overbought",
                    "label": "超买判断",
                    "type": "decision",
                    "description": f"价格>上轨 且 RSI>{self.rsi_overbought}",
                },
                {
                    "id": "signal",
                    "label": "交易信号",
                    "type": "output",
                    "description": "买入/卖出/持有",
                },
            ],
            "flow_edges": [
                {"source": "data", "target": "bb", "label": ""},
                {"source": "data", "target": "rsi", "label": ""},
                {"source": "data", "target": "volume_check", "label": ""},
                {"source": "bb", "target": "oversold", "label": "下轨"},
                {"source": "bb", "target": "overbought", "label": "上轨"},
                {"source": "rsi", "target": "oversold", "label": "超卖"},
                {"source": "rsi", "target": "overbought", "label": "超买"},
                {"source": "volume_check", "target": "oversold", "label": "确认"},
                {"source": "oversold", "target": "signal", "label": "买入"},
                {"source": "overbought", "target": "signal", "label": "卖出"},
            ],
            "configurable_params": [
                {
                    "key": "bb_period",
                    "label": "布林带周期",
                    "type": "int",
                    "min": 10,
                    "max": 50,
                    "step": 1,
                    "default": 20,
                    "current": self.bb_period,
                },
                {
                    "key": "bb_std",
                    "label": "标准差倍数",
                    "type": "float",
                    "min": 1.0,
                    "max": 4.0,
                    "step": 0.1,
                    "default": 2.0,
                    "current": self.bb_std,
                },
                {
                    "key": "rsi_period",
                    "label": "RSI周期",
                    "type": "int",
                    "min": 5,
                    "max": 30,
                    "step": 1,
                    "default": 14,
                    "current": self.rsi_period,
                },
                {
                    "key": "rsi_oversold",
                    "label": "超卖阈值",
                    "type": "float",
                    "min": 10,
                    "max": 40,
                    "step": 1,
                    "default": 30,
                    "current": self.rsi_oversold,
                },
                {
                    "key": "rsi_overbought",
                    "label": "超买阈值",
                    "type": "float",
                    "min": 60,
                    "max": 90,
                    "step": 1,
                    "default": 70,
                    "current": self.rsi_overbought,
                },
            ],
        }

    def get_params(self) -> dict[str, Any]:
        """Return current parameter values."""
        return {
            "bb_period": self.bb_period,
            "bb_std": self.bb_std,
            "rsi_period": self.rsi_period,
            "rsi_oversold": self.rsi_oversold,
            "rsi_overbought": self.rsi_overbought,
            "volume_confirm": self.volume_confirm,
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate mean-reversion signals from OHLCV data.

        The method adds Bollinger Bands, RSI, and volume indicators
        to a copy of the input, then evaluates each bar for entry/exit
        conditions.

        Args:
            df: OHLCV DataFrame with ``date``, ``open``, ``high``,
                ``low``, ``close``, and ``volume`` columns.

        Returns:
            A new DataFrame with columns ``date``, ``signal``,
            ``strength``, and ``reason``.  The input *df* is never
            modified.
        """
        enriched = self.indicators.add_bollinger(df.copy())
        enriched = self.indicators.add_rsi(enriched)
        enriched = self.indicators.add_volume_indicators(enriched)

        # Volume moving average for confirmation
        enriched["volume_ma"] = (
            enriched["volume"].rolling(window=self.bb_period, min_periods=1).mean()
        )

        signals: list[dict[str, Any]] = []

        for i in range(len(enriched)):
            date = enriched.at[i, "date"] if "date" in enriched.columns else i

            bb_upper = enriched.at[i, "BB_upper"]
            bb_lower = enriched.at[i, "BB_lower"]
            bb_middle = enriched.at[i, "BB_middle"]
            rsi = enriched.at[i, "RSI"]
            close = enriched.at[i, "close"]
            volume = enriched.at[i, "volume"]
            volume_avg = enriched.at[i, "volume_ma"]

            # Skip when indicators are not yet computed
            if pd.isna(bb_upper) or pd.isna(bb_lower) or pd.isna(rsi):
                signals.append(self._build_signal_row(date, SIGNAL_HOLD, 0.0, ""))
                continue

            # --- BUY: price below lower band + RSI oversold -----------
            if close < bb_lower and rsi < self.rsi_oversold:
                volume_ok = (not self.volume_confirm) or (
                    volume_avg > 0 and volume > volume_avg
                )
                if volume_ok:
                    strength = self._compute_buy_strength(
                        close, bb_lower, bb_middle, rsi
                    )
                    band_pct = (bb_lower - close) / close * 100 if close > 0 else 0
                    reason = (
                        f"均值回归买入: 收盘价低于布林下轨"
                        f"({band_pct:.1f}%), RSI={rsi:.1f}超卖"
                    )
                    if self.volume_confirm:
                        ratio = volume / volume_avg if volume_avg > 0 else 0
                        reason += f", 成交量确认({ratio:.1f}倍均量)"
                    signals.append(
                        self._build_signal_row(date, SIGNAL_BUY, strength, reason)
                    )
                    continue

            # --- SELL: price above upper band + RSI overbought --------
            if close > bb_upper and rsi > self.rsi_overbought:
                strength = self._compute_sell_strength(close, bb_upper, bb_middle, rsi)
                band_pct = (close - bb_upper) / close * 100 if close > 0 else 0
                reason = (
                    f"均值回归卖出: 收盘价高于布林上轨"
                    f"({band_pct:.1f}%), RSI={rsi:.1f}超买"
                )
                signals.append(
                    self._build_signal_row(date, SIGNAL_SELL, strength, reason)
                )
                continue

            # --- HOLD -------------------------------------------------
            signals.append(self._build_signal_row(date, SIGNAL_HOLD, 0.0, ""))

        return pd.DataFrame(signals)

    @staticmethod
    def _compute_buy_strength(
        close: float,
        bb_lower: float,
        bb_middle: float,
        rsi: float,
    ) -> float:
        """Compute buy-signal strength based on BB deviation and RSI.

        Combines how far below the lower band the price is with how
        extreme the RSI reading is.

        Args:
            close: Current close price.
            bb_lower: Lower Bollinger Band value.
            bb_middle: Middle Bollinger Band value.
            rsi: Current RSI value.

        Returns:
            A float in ``[0, 1]``.
        """
        band_width = bb_middle - bb_lower if bb_middle != bb_lower else 1.0
        band_score = (
            min((bb_lower - close) / band_width, 1.0) if close < bb_lower else 0.0
        )
        rsi_score = min((30 - rsi) / 30, 1.0) if rsi < 30 else 0.0
        combined = 0.6 * band_score + 0.4 * rsi_score
        return round(min(max(combined, 0.0), 1.0), 4)

    @staticmethod
    def _compute_sell_strength(
        close: float,
        bb_upper: float,
        bb_middle: float,
        rsi: float,
    ) -> float:
        """Compute sell-signal strength based on BB deviation and RSI.

        Combines how far above the upper band the price is with how
        extreme the RSI reading is.

        Args:
            close: Current close price.
            bb_upper: Upper Bollinger Band value.
            bb_middle: Middle Bollinger Band value.
            rsi: Current RSI value.

        Returns:
            A float in ``[0, 1]``.
        """
        band_width = bb_upper - bb_middle if bb_upper != bb_middle else 1.0
        band_score = (
            min((close - bb_upper) / band_width, 1.0) if close > bb_upper else 0.0
        )
        rsi_score = min((rsi - 70) / 30, 1.0) if rsi > 70 else 0.0
        combined = 0.6 * band_score + 0.4 * rsi_score
        return round(min(max(combined, 0.0), 1.0), 4)
