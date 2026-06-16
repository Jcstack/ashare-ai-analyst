"""Bayesian conditional probability engine for technical indicators.

For each indicator (RSI, MACD histogram, KDJ-J, Bollinger Band position,
volume ratio) the engine bins the current value, then computes the
historical conditional probability P(up | indicator ∈ bin) using a
lookback window (default 250 trading days) and a forward window
(default 5 trading days).

No LLM calls – pure statistical computation for sub-500ms response.

Per PRD v2.3 FR-BI001.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Indicator analogies (extends explanations.py without modifying its data)
# ---------------------------------------------------------------------------

INDICATOR_ANALOGIES: dict[str, str] = {
    "rsi": (
        "RSI 就像温度计——数值越高表示市场情绪越热，"
        "超过 80 就像'发烧'，低于 20 则像'体温过低'。"
    ),
    "macd_hist": (
        "MACD 柱状图就像潮汐——正值代表涨潮（多头力量强），"
        "负值代表退潮（空头占优），柱子高度反映潮水的强度。"
    ),
    "kdj_j": (
        "KDJ 的 J 线就像弹簧——压得越低反弹越猛（超卖），"
        "拉得越高回调越快（超买），100 以上和 0 以下属于极端拉伸。"
    ),
    "bb_position": (
        "布林带位置就像高速公路——中轨是车道中线，"
        "靠近上轨说明你在超车道快速行驶，靠近下轨说明在慢车道。"
    ),
    "volume_ratio": (
        "量比就像人流量——1.0 是正常水平，超过 2.0 相当于'客流暴增'，"
        "低于 0.5 则像'门可罗雀'，异常客流往往预示着大事发生。"
    ),
}

# ---------------------------------------------------------------------------
# Bin label translations
# ---------------------------------------------------------------------------

_RSI_BIN_LABELS: dict[str, str] = {
    "0-20": "极度超卖",
    "20-30": "超卖",
    "30-40": "偏冷",
    "40-50": "偏弱",
    "50-60": "偏强",
    "60-70": "偏热",
    "70-80": "超买",
    "80-100": "极度超买",
}

_KDJ_BIN_LABELS: dict[str, str] = {
    "≤0": "极度超卖",
    "0-20": "超卖",
    "20-50": "中性偏弱",
    "50-80": "中性偏强",
    "80-100": "超买",
    "≥100": "极度超买",
}

_BB_BIN_LABELS: dict[str, str] = {
    "0.0-0.2": "下轨附近",
    "0.2-0.4": "中下区域",
    "0.4-0.6": "中轨附近",
    "0.6-0.8": "中上区域",
    "0.8-1.0": "上轨附近",
}

_VOLUME_BIN_LABELS: dict[str, str] = {
    "0.0-0.5": "极度萎缩",
    "0.5-0.8": "缩量",
    "0.8-1.0": "正常偏低",
    "1.0-1.5": "正常偏高",
    "1.5-2.0": "温和放量",
    "2.0-3.0": "明显放量",
    "3.0-inf": "巨量",
}


class BayesianIndicatorAnalyzer:
    """Compute conditional probabilities for technical indicator bins.

    Parameters
    ----------
    lookback_days : int
        Number of trading days to look back for statistics (default 250).
    forward_days : int
        Number of trading days to look forward for return classification
        (default 5).
    min_samples : int
        Minimum number of observations in a bin for results to be
        considered statistically sufficient (default 10).
    up_threshold : float
        Percentage threshold above which a forward return is classified
        as *up* (default 0.5, meaning +0.5%).
    """

    # Fixed bin edges for each indicator
    INDICATOR_BINS: dict[str, list[float] | str] = {
        "rsi": [0, 20, 30, 40, 50, 60, 70, 80, 100],
        "macd_hist": "quantile_5",
        "kdj_j": "kdj_special",  # needs clip + custom bins
        "bb_position": [0, 0.2, 0.4, 0.6, 0.8, 1.0],
        "volume_ratio": [0, 0.5, 0.8, 1.0, 1.5, 2.0, 3.0, float("inf")],
    }

    def __init__(
        self,
        lookback_days: int = 250,
        forward_days: int = 5,
        min_samples: int = 10,
        up_threshold: float = 0.5,
    ) -> None:
        self.lookback_days = lookback_days
        self.forward_days = forward_days
        self.min_samples = min_samples
        self.up_threshold = up_threshold / 100.0  # convert pct to fraction

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def analyze(self, df: pd.DataFrame) -> dict[str, Any]:
        """Run Bayesian analysis on a DataFrame with OHLCV + indicators.

        Parameters
        ----------
        df : pd.DataFrame
            Must contain columns: ``close``, ``RSI``, ``MACD_hist``,
            ``KDJ_J``, ``BB_upper``, ``BB_lower``, ``volume``.
            Typically the output of ``TechnicalIndicators.add_all()``.

        Returns
        -------
        dict
            ``{"indicators": [...], "composite": {...}}`` structure
            matching the FR-BI003 API response schema.
        """
        df = self._prepare(df)

        indicator_results: list[dict[str, Any]] = []

        for indicator_key, bin_spec in self.INDICATOR_BINS.items():
            result = self._analyze_single(df, indicator_key, bin_spec)
            if result is not None:
                indicator_results.append(result)

        composite = self._compute_composite(indicator_results)

        return {
            "indicators": indicator_results,
            "composite": composite,
        }

    # ------------------------------------------------------------------
    # Per-indicator analysis
    # ------------------------------------------------------------------

    def _analyze_single(
        self,
        df: pd.DataFrame,
        key: str,
        bin_spec: list[float] | str,
    ) -> dict[str, Any] | None:
        """Analyze a single indicator."""
        col = self._resolve_column(df, key)
        if col is None:
            return None

        series = df[col].dropna()
        if len(series) < self.min_samples:
            return self._insufficient_result(
                key, series.iloc[-1] if len(series) else 0.0
            )

        # Use the lookback window
        series_window = (
            series.iloc[-self.lookback_days :]
            if len(series) > self.lookback_days
            else series
        )
        close_window = (
            df["close"].iloc[-self.lookback_days :]
            if len(df) > self.lookback_days
            else df["close"]
        )

        current_value = float(series.iloc[-1])
        bins = self._resolve_bins(series_window, bin_spec)
        if bins is None:
            return self._insufficient_result(key, current_value)

        # Bin the series
        binned = pd.cut(
            series_window, bins=bins, include_lowest=True, duplicates="drop"
        )

        # Compute forward returns
        forward_return = close_window.shift(-self.forward_days) / close_window - 1.0

        # Classify
        up_mask = forward_return > self.up_threshold
        down_mask = forward_return < -self.up_threshold
        flat_mask = ~up_mask & ~down_mask

        # Find current bin
        current_bin = None
        try:
            current_bin = pd.cut(
                pd.Series([current_value]),
                bins=bins,
                include_lowest=True,
                duplicates="drop",
            ).iloc[0]
        except Exception:
            pass

        if current_bin is None or pd.isna(current_bin):
            return self._insufficient_result(key, current_value)

        # Filter to current bin
        bin_mask = binned == current_bin
        # Also remove rows where forward return is NaN (last N rows)
        valid_mask = bin_mask & forward_return.notna()

        sample_count = int(valid_mask.sum())
        if sample_count < self.min_samples:
            return self._insufficient_result(key, current_value, sample_count)

        p_up = float(up_mask[valid_mask].sum()) / sample_count
        p_down = float(down_mask[valid_mask].sum()) / sample_count
        p_flat = float(flat_mask[valid_mask].sum()) / sample_count

        # Normalize to ensure sum == 1.0
        total = p_up + p_flat + p_down
        if total > 0:
            p_up /= total
            p_flat /= total
            p_down /= total

        bin_label = self._format_bin_label(key, current_bin)
        interpretation = self._generate_interpretation(
            key, bin_label, p_up, p_down, p_flat, sample_count
        )
        analogy = INDICATOR_ANALOGIES.get(key, "")

        return {
            "indicator": key,
            "current_value": round(current_value, 2),
            "bin_label": bin_label,
            "probabilities": {
                "up": round(p_up, 2),
                "flat": round(p_flat, 2),
                "down": round(p_down, 2),
            },
            "sample_count": sample_count,
            "interpretation": interpretation,
            "analogy": analogy,
            "data_sufficient": True,
        }

    # ------------------------------------------------------------------
    # Composite signal
    # ------------------------------------------------------------------

    def _compute_composite(self, indicators: list[dict[str, Any]]) -> dict[str, Any]:
        """Aggregate individual indicator signals into a composite."""
        bullish = 0
        bearish = 0
        neutral = 0

        for ind in indicators:
            if not ind.get("data_sufficient", False):
                continue
            probs = ind.get("probabilities", {})
            p_up = probs.get("up", 0)
            p_down = probs.get("down", 0)
            if p_up > p_down + 0.05:
                bullish += 1
            elif p_down > p_up + 0.05:
                bearish += 1
            else:
                neutral += 1

        if bullish > bearish and bullish > neutral:
            signal = "偏多"
        elif bearish > bullish and bearish > neutral:
            signal = "偏空"
        else:
            signal = "中性"

        total = bullish + bearish + neutral
        summary_parts = []
        if total > 0:
            summary_parts.append(
                f"{total} 项指标中 {bullish} 项偏多、{bearish} 项偏空、{neutral} 项中性。"
            )
        if signal == "偏多":
            summary_parts.append("整体概率倾向看多。")
        elif signal == "偏空":
            summary_parts.append("整体概率倾向看空。")
        else:
            summary_parts.append("整体方向不明确，多空力量均衡。")

        return {
            "signal": signal,
            "bullish_count": bullish,
            "bearish_count": bearish,
            "neutral_count": neutral,
            "summary": "".join(summary_parts),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure required derived columns exist."""
        df = df.copy()

        # BB position: (close - lower) / (upper - lower)
        if "BB_upper" in df.columns and "BB_lower" in df.columns:
            bb_range = df["BB_upper"] - df["BB_lower"]
            df["bb_position"] = np.where(
                bb_range > 0,
                (df["close"] - df["BB_lower"]) / bb_range,
                0.5,
            )
            df["bb_position"] = df["bb_position"].clip(0, 1)

        # Volume ratio: today's volume / 20-day average volume
        if "volume" in df.columns:
            vol_ma20 = df["volume"].rolling(window=20, min_periods=1).mean()
            df["volume_ratio"] = np.where(vol_ma20 > 0, df["volume"] / vol_ma20, 1.0)

        return df

    def _resolve_column(self, df: pd.DataFrame, key: str) -> str | None:
        """Map indicator key to DataFrame column name."""
        mapping = {
            "rsi": "RSI",
            "macd_hist": "MACD_hist",
            "kdj_j": "KDJ_J",
            "bb_position": "bb_position",
            "volume_ratio": "volume_ratio",
        }
        col = mapping.get(key)
        if col and col in df.columns:
            return col
        return None

    def _resolve_bins(
        self, series: pd.Series, spec: list[float] | str
    ) -> list[float] | None:
        """Convert bin specification to concrete bin edges."""
        if isinstance(spec, list):
            return spec
        if spec == "quantile_5":
            try:
                edges = list(series.quantile([0, 0.2, 0.4, 0.6, 0.8, 1.0]).values)
                # Ensure unique edges
                edges = sorted(set(edges))
                if len(edges) < 3:
                    return None
                return edges
            except Exception:
                return None
        if spec == "kdj_special":
            # KDJ J can go below 0 and above 100
            return [-float("inf"), 0, 20, 50, 80, 100, float("inf")]
        return None

    def _format_bin_label(self, key: str, bin_interval: Any) -> str:
        """Create a human-readable bin label."""
        left = bin_interval.left
        right = bin_interval.right

        # Format the range string
        if left == -float("inf"):
            range_str = f"≤{right:.0f}" if right == int(right) else f"≤{right}"
        elif right == float("inf"):
            range_str = f"≥{left:.0f}" if left == int(left) else f"≥{left}"
        else:
            if left == int(left) and right == int(right):
                range_str = f"{int(left)}-{int(right)}"
            else:
                range_str = f"{left:.1f}-{right:.1f}"

        # Add Chinese label
        label_maps = {
            "rsi": _RSI_BIN_LABELS,
            "kdj_j": _KDJ_BIN_LABELS,
            "bb_position": _BB_BIN_LABELS,
            "volume_ratio": _VOLUME_BIN_LABELS,
        }
        labels = label_maps.get(key, {})
        chinese = labels.get(range_str, "")
        if chinese:
            return f"{range_str} ({chinese})"
        return range_str

    def _generate_interpretation(
        self,
        key: str,
        bin_label: str,
        p_up: float,
        p_down: float,
        p_flat: float,
        sample_count: int,
    ) -> str:
        """Generate a Chinese interpretation string."""
        indicator_names = {
            "rsi": "RSI",
            "macd_hist": "MACD 柱状",
            "kdj_j": "KDJ J 值",
            "bb_position": "布林带位置",
            "volume_ratio": "量比",
        }
        name = indicator_names.get(key, key)

        direction = ""
        if p_up > p_down + 0.1:
            direction = "上涨概率明显高于下跌"
        elif p_down > p_up + 0.1:
            direction = "下跌概率明显高于上涨"
        elif abs(p_up - p_down) <= 0.1:
            direction = "方向不明确"
        elif p_up > p_down:
            direction = "略高于下跌概率"
        else:
            direction = "略高于上涨概率"

        return (
            f"{name} 处于 {bin_label} 区间，历史上该区间 "
            f"{self.forward_days} 日后上涨概率 {p_up:.0%}，"
            f"下跌概率 {p_down:.0%}，{direction}。"
            f"（基于 {sample_count} 个历史样本）"
        )

    def _insufficient_result(
        self, key: str, current_value: float, sample_count: int = 0
    ) -> dict[str, Any]:
        """Return a placeholder result when data is insufficient."""
        return {
            "indicator": key,
            "current_value": round(current_value, 2),
            "bin_label": "数据不足",
            "probabilities": {"up": 0, "flat": 0, "down": 0},
            "sample_count": sample_count,
            "interpretation": "历史数据不足，无法计算可靠的条件概率。建议使用更长周期的数据。",
            "analogy": INDICATOR_ANALOGIES.get(key, ""),
            "data_sufficient": False,
        }
