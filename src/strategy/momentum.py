"""Momentum strategy for A-share stock analysis.

Generates buy/sell signals based on Rate of Change (ROC), RSI direction,
and volume surges.  Configuration is loaded from ``config/strategy.yaml``
under the ``momentum`` key.
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


class MomentumStrategy(BaseStrategy):
    """ROC + RSI + volume-surge momentum strategy.

    **Buy signal**: ROC > 0 AND RSI > ``rsi_threshold`` AND volume
    exceeds ``volume_surge_threshold`` times the rolling average.

    **Sell signal**: ROC < 0 AND RSI < ``rsi_threshold``.

    Args:
        config_path: Name of the YAML config (without extension).
            Defaults to ``"strategy"``.
    """

    def __init__(self, config_path: str = "strategy") -> None:
        super().__init__(config_path)
        self.strategy_config: dict[str, Any] = self.config.get("momentum", {})
        self.roc_period: int = int(self.strategy_config.get("roc_period", 12))
        self.rsi_period: int = int(self.strategy_config.get("rsi_period", 14))
        self.rsi_threshold: float = self.strategy_config.get("rsi_threshold", 50)
        self.volume_surge_threshold: float = self.strategy_config.get(
            "volume_surge_threshold", 2.0
        )
        self.lookback: int = int(self.strategy_config.get("lookback", 20))
        self.indicators = TechnicalIndicators()
        logger.info(
            "MomentumStrategy: roc_period=%d, rsi_threshold=%.0f, "
            "volume_surge=%.1fx, lookback=%d",
            self.roc_period,
            self.rsi_threshold,
            self.volume_surge_threshold,
            self.lookback,
        )

    def get_metadata(self) -> dict[str, Any]:
        """Return momentum strategy metadata."""
        return {
            "name": "动量策略",
            "description": "基于价格变化率(ROC)、RSI方向和成交量突增的动量策略",
            "flow_steps": [
                {
                    "id": "data",
                    "label": "OHLCV数据",
                    "type": "input",
                    "description": "日线行情数据",
                },
                {
                    "id": "roc",
                    "label": f"ROC({self.roc_period})",
                    "type": "indicator",
                    "description": f"{self.roc_period}日价格变化率",
                },
                {
                    "id": "rsi",
                    "label": f"RSI({self.rsi_period})",
                    "type": "indicator",
                    "description": f"{self.rsi_period}日相对强弱指数",
                },
                {
                    "id": "volume_surge",
                    "label": "量能突增",
                    "type": "filter",
                    "description": f"成交量>{self.volume_surge_threshold}倍均量",
                },
                {
                    "id": "momentum_check",
                    "label": "动量判断",
                    "type": "decision",
                    "description": f"ROC方向 + RSI vs {self.rsi_threshold}",
                },
                {
                    "id": "signal",
                    "label": "交易信号",
                    "type": "output",
                    "description": "买入/卖出/持有",
                },
            ],
            "flow_edges": [
                {"source": "data", "target": "roc", "label": ""},
                {"source": "data", "target": "rsi", "label": ""},
                {"source": "data", "target": "volume_surge", "label": ""},
                {"source": "roc", "target": "momentum_check", "label": "方向"},
                {"source": "rsi", "target": "momentum_check", "label": "强弱"},
                {"source": "volume_surge", "target": "momentum_check", "label": "确认"},
                {"source": "momentum_check", "target": "signal", "label": ""},
            ],
            "configurable_params": [
                {
                    "key": "roc_period",
                    "label": "ROC周期",
                    "type": "int",
                    "min": 5,
                    "max": 30,
                    "step": 1,
                    "default": 12,
                    "current": self.roc_period,
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
                    "key": "rsi_threshold",
                    "label": "RSI阈值",
                    "type": "float",
                    "min": 30,
                    "max": 70,
                    "step": 1,
                    "default": 50,
                    "current": self.rsi_threshold,
                },
                {
                    "key": "volume_surge_threshold",
                    "label": "放量倍数",
                    "type": "float",
                    "min": 1.0,
                    "max": 5.0,
                    "step": 0.1,
                    "default": 2.0,
                    "current": self.volume_surge_threshold,
                },
            ],
        }

    def get_params(self) -> dict[str, Any]:
        """Return current parameter values."""
        return {
            "roc_period": self.roc_period,
            "rsi_period": self.rsi_period,
            "rsi_threshold": self.rsi_threshold,
            "volume_surge_threshold": self.volume_surge_threshold,
            "lookback": self.lookback,
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate momentum signals from OHLCV data.

        Computes Rate of Change (ROC), adds RSI via ``TechnicalIndicators``,
        and evaluates volume surges to produce buy, sell, or hold signals.

        Args:
            df: OHLCV DataFrame with ``date``, ``open``, ``high``,
                ``low``, ``close``, and ``volume`` columns.

        Returns:
            A new DataFrame with columns ``date``, ``signal``,
            ``strength``, and ``reason``.  The input *df* is never
            modified.
        """
        enriched = self.indicators.add_rsi(df.copy())
        enriched = self.indicators.add_volume_indicators(enriched)

        # Rate of Change: (close - close[n]) / close[n]
        enriched["ROC"] = enriched["close"].pct_change(periods=self.roc_period)

        # Volume moving average for surge detection
        enriched["volume_ma"] = (
            enriched["volume"].rolling(window=self.lookback, min_periods=1).mean()
        )

        signals: list[dict[str, Any]] = []

        for i in range(len(enriched)):
            date = enriched.at[i, "date"] if "date" in enriched.columns else i

            roc = enriched.at[i, "ROC"]
            rsi = enriched.at[i, "RSI"]
            volume = enriched.at[i, "volume"]
            volume_avg = enriched.at[i, "volume_ma"]

            # Skip when indicators are not yet available
            if pd.isna(roc) or pd.isna(rsi):
                signals.append(self._build_signal_row(date, SIGNAL_HOLD, 0.0, ""))
                continue

            volume_surge = (
                volume_avg > 0 and volume > self.volume_surge_threshold * volume_avg
            )

            # --- BUY: positive momentum + RSI bullish + volume surge --
            if roc > 0 and rsi > self.rsi_threshold and volume_surge:
                strength = self._compute_buy_strength(roc, rsi, volume, volume_avg)
                ratio = volume / volume_avg if volume_avg > 0 else 0
                reason = (
                    f"动量买入: ROC={roc * 100:.1f}%为正, "
                    f"RSI={rsi:.1f}>{self.rsi_threshold:.0f}, "
                    f"成交量放大{ratio:.1f}倍"
                )
                signals.append(
                    self._build_signal_row(date, SIGNAL_BUY, strength, reason)
                )
                continue

            # --- SELL: negative momentum + RSI bearish ----------------
            if roc < 0 and rsi < self.rsi_threshold:
                strength = self._compute_sell_strength(roc, rsi)
                reason = (
                    f"动量卖出: ROC={roc * 100:.1f}%为负, "
                    f"RSI={rsi:.1f}<{self.rsi_threshold:.0f}"
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
        roc: float,
        rsi: float,
        volume: float,
        volume_avg: float,
    ) -> float:
        """Compute buy-signal strength from momentum indicators.

        Combines ROC magnitude, RSI bullishness, and volume surge ratio.

        Args:
            roc: Rate of Change value (decimal).
            rsi: Current RSI value.
            volume: Current bar volume.
            volume_avg: Rolling average volume.

        Returns:
            A float in ``[0, 1]``.
        """
        # ROC component: 20% ROC maps to score 1.0
        roc_score = min(abs(roc) / 0.20, 1.0)
        # RSI component: distance above 50, normalised to [0,1]
        rsi_score = min((rsi - 50) / 50, 1.0) if rsi > 50 else 0.0
        # Volume component
        vol_ratio = volume / volume_avg if volume_avg > 0 else 0
        vol_score = min(vol_ratio / 5.0, 1.0)
        combined = 0.4 * roc_score + 0.3 * rsi_score + 0.3 * vol_score
        return round(min(max(combined, 0.0), 1.0), 4)

    @staticmethod
    def _compute_sell_strength(roc: float, rsi: float) -> float:
        """Compute sell-signal strength from momentum indicators.

        Combines ROC magnitude and RSI bearishness.

        Args:
            roc: Rate of Change value (decimal, negative).
            rsi: Current RSI value.

        Returns:
            A float in ``[0, 1]``.
        """
        roc_score = min(abs(roc) / 0.20, 1.0)
        rsi_score = min((50 - rsi) / 50, 1.0) if rsi < 50 else 0.0
        combined = 0.5 * roc_score + 0.5 * rsi_score
        return round(min(max(combined, 0.0), 1.0), 4)
