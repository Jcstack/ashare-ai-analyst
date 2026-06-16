"""Trend-following strategy for A-share stock analysis.

Generates buy/sell signals based on moving-average crossovers, confirmed
by MACD histogram direction and above-average volume.  Configuration is
loaded from ``config/strategy.yaml`` under the ``trend_following`` key.
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


class TrendFollowingStrategy(BaseStrategy):
    """Moving-average crossover strategy with MACD and volume filters.

    **Buy signal**: fast MA crosses above slow MA, optionally confirmed
    by MACD histogram > 0 and volume above a configurable threshold of
    the rolling average.

    **Sell signal**: fast MA crosses below slow MA and MACD histogram < 0.

    Args:
        config_path: Name of the YAML config (without extension).
            Defaults to ``"strategy"``.
    """

    def __init__(self, config_path: str = "strategy") -> None:
        super().__init__(config_path)
        self.strategy_config: dict[str, Any] = self.config.get("trend_following", {})
        self.fast_ma: int = int(self.strategy_config.get("fast_ma", 5))
        self.slow_ma: int = int(self.strategy_config.get("slow_ma", 20))
        self.macd_confirm: bool = self.strategy_config.get("macd_confirm", True)
        self.volume_filter: bool = self.strategy_config.get("volume_filter", True)
        self.volume_ma_period: int = int(
            self.strategy_config.get("volume_ma_period", 20)
        )
        self.volume_threshold: float = self.strategy_config.get("volume_threshold", 1.5)
        self.indicators = TechnicalIndicators()
        logger.info(
            "TrendFollowingStrategy: fast_ma=%d, slow_ma=%d, "
            "macd_confirm=%s, volume_filter=%s",
            self.fast_ma,
            self.slow_ma,
            self.macd_confirm,
            self.volume_filter,
        )

    def get_metadata(self) -> dict[str, Any]:
        """Return trend-following strategy metadata."""
        return {
            "name": "趋势跟踪策略",
            "description": "基于均线交叉的趋势跟踪策略，通过MACD和成交量确认信号",
            "flow_steps": [
                {
                    "id": "data",
                    "label": "OHLCV数据",
                    "type": "input",
                    "description": "日线行情数据",
                },
                {
                    "id": "fast_ma",
                    "label": f"快线MA{self.fast_ma}",
                    "type": "indicator",
                    "description": f"{self.fast_ma}日移动均线",
                },
                {
                    "id": "slow_ma",
                    "label": f"慢线MA{self.slow_ma}",
                    "type": "indicator",
                    "description": f"{self.slow_ma}日移动均线",
                },
                {
                    "id": "macd",
                    "label": "MACD确认",
                    "type": "filter",
                    "description": "MACD柱状图方向确认",
                },
                {
                    "id": "volume",
                    "label": "成交量过滤",
                    "type": "filter",
                    "description": f"成交量>{self.volume_threshold}倍均量",
                },
                {
                    "id": "cross",
                    "label": "交叉判断",
                    "type": "decision",
                    "description": "金叉买入/死叉卖出",
                },
                {
                    "id": "signal",
                    "label": "交易信号",
                    "type": "output",
                    "description": "买入/卖出/持有",
                },
            ],
            "flow_edges": [
                {"source": "data", "target": "fast_ma", "label": ""},
                {"source": "data", "target": "slow_ma", "label": ""},
                {"source": "data", "target": "macd", "label": ""},
                {"source": "data", "target": "volume", "label": ""},
                {"source": "fast_ma", "target": "cross", "label": ""},
                {"source": "slow_ma", "target": "cross", "label": ""},
                {"source": "macd", "target": "cross", "label": "确认"},
                {"source": "volume", "target": "cross", "label": "确认"},
                {"source": "cross", "target": "signal", "label": ""},
            ],
            "configurable_params": [
                {
                    "key": "fast_ma",
                    "label": "快线周期",
                    "type": "int",
                    "min": 2,
                    "max": 30,
                    "step": 1,
                    "default": 5,
                    "current": self.fast_ma,
                },
                {
                    "key": "slow_ma",
                    "label": "慢线周期",
                    "type": "int",
                    "min": 10,
                    "max": 120,
                    "step": 5,
                    "default": 20,
                    "current": self.slow_ma,
                },
                {
                    "key": "volume_threshold",
                    "label": "放量倍数",
                    "type": "float",
                    "min": 1.0,
                    "max": 5.0,
                    "step": 0.1,
                    "default": 1.5,
                    "current": self.volume_threshold,
                },
            ],
        }

    def get_params(self) -> dict[str, Any]:
        """Return current parameter values."""
        return {
            "fast_ma": self.fast_ma,
            "slow_ma": self.slow_ma,
            "volume_threshold": self.volume_threshold,
            "macd_confirm": self.macd_confirm,
            "volume_filter": self.volume_filter,
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate trend-following signals from OHLCV data.

        The method adds required technical indicators, then scans for
        golden-cross (buy) and death-cross (sell) events between the
        fast and slow moving averages.

        Args:
            df: OHLCV DataFrame with ``date``, ``open``, ``high``,
                ``low``, ``close``, and ``volume`` columns.

        Returns:
            A new DataFrame with columns ``date``, ``signal``,
            ``strength``, and ``reason``.  The input *df* is never
            modified.
        """
        # Compute indicators on a copy
        enriched = self.indicators.add_moving_averages(df.copy())
        enriched = self.indicators.add_macd(enriched)
        enriched = self.indicators.add_volume_indicators(enriched)

        fast_col = f"MA_{self.fast_ma}"
        slow_col = f"MA_{self.slow_ma}"

        # Volume moving average for filter
        enriched["volume_ma"] = (
            enriched["volume"]
            .rolling(window=self.volume_ma_period, min_periods=1)
            .mean()
        )

        signals: list[dict[str, Any]] = []

        for i in range(1, len(enriched)):
            date = enriched.at[i, "date"] if "date" in enriched.columns else i

            # Skip rows where indicators are not yet available
            if pd.isna(enriched.at[i, fast_col]) or pd.isna(enriched.at[i, slow_col]):
                signals.append(self._build_signal_row(date, SIGNAL_HOLD, 0.0, ""))
                continue

            prev_fast = enriched.at[i - 1, fast_col]
            prev_slow = enriched.at[i - 1, slow_col]
            curr_fast = enriched.at[i, fast_col]
            curr_slow = enriched.at[i, slow_col]

            if pd.isna(prev_fast) or pd.isna(prev_slow):
                signals.append(self._build_signal_row(date, SIGNAL_HOLD, 0.0, ""))
                continue

            # Detect crossovers
            golden_cross = prev_fast <= prev_slow and curr_fast > curr_slow
            death_cross = prev_fast >= prev_slow and curr_fast < curr_slow

            macd_hist = enriched.at[i, "MACD_hist"]
            volume = enriched.at[i, "volume"]
            volume_avg = enriched.at[i, "volume_ma"]

            # --- BUY signal -------------------------------------------
            if golden_cross:
                macd_ok = (not self.macd_confirm) or (
                    not pd.isna(macd_hist) and macd_hist > 0
                )
                volume_ok = (not self.volume_filter) or (
                    volume_avg > 0 and volume > self.volume_threshold * volume_avg
                )

                if macd_ok and volume_ok:
                    strength = self._compute_strength(
                        curr_fast, curr_slow, enriched.at[i, "close"]
                    )
                    reason = f"金叉信号: MA{self.fast_ma}上穿MA{self.slow_ma}"
                    if self.macd_confirm:
                        reason += ", MACD柱状图为正"
                    if self.volume_filter:
                        ratio = volume / volume_avg if volume_avg > 0 else 0
                        reason += f", 成交量放大{ratio:.1f}倍"
                    signals.append(
                        self._build_signal_row(date, SIGNAL_BUY, strength, reason)
                    )
                    continue

            # --- SELL signal ------------------------------------------
            if death_cross:
                macd_sell = pd.isna(macd_hist) or macd_hist < 0
                if macd_sell:
                    strength = self._compute_strength(
                        curr_fast, curr_slow, enriched.at[i, "close"]
                    )
                    reason = f"死叉信号: MA{self.fast_ma}下穿MA{self.slow_ma}"
                    if not pd.isna(macd_hist):
                        reason += ", MACD柱状图为负"
                    signals.append(
                        self._build_signal_row(date, SIGNAL_SELL, strength, reason)
                    )
                    continue

            # --- HOLD -------------------------------------------------
            signals.append(self._build_signal_row(date, SIGNAL_HOLD, 0.0, ""))

        # The first row has no previous bar to compare against
        first_date = enriched.at[0, "date"] if "date" in enriched.columns else 0
        signals.insert(0, self._build_signal_row(first_date, SIGNAL_HOLD, 0.0, ""))

        return pd.DataFrame(signals)

    @staticmethod
    def _compute_strength(fast_ma: float, slow_ma: float, close: float) -> float:
        """Compute signal strength from the MA spread.

        Strength is the absolute distance between the two MAs normalised
        by the close price, capped at 1.0.

        Args:
            fast_ma: Current fast moving average value.
            slow_ma: Current slow moving average value.
            close: Current close price.

        Returns:
            A float in ``[0, 1]`` representing signal strength.
        """
        if close == 0:
            return 0.0
        raw = abs(fast_ma - slow_ma) / close
        # Normalise: 5% spread maps to strength 1.0
        normalised = min(raw / 0.05, 1.0)
        return round(normalised, 4)
