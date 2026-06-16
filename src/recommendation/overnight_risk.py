"""Overnight risk quantification for T+1 A-share market (I-090 Phase 2).

Calculates historical overnight gap statistics and post-rally drawdown
probabilities to quantify the risk of buying stocks that have already
surged during the current session.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class OvernightRiskProfile:
    """Risk profile for a stock's overnight behavior."""

    symbol: str
    # Overnight gap stats (open[t+1] / close[t] - 1)
    avg_gap_pct: float  # Average overnight gap %
    std_gap_pct: float  # Std deviation of overnight gap
    max_negative_gap_pct: float  # Worst overnight gap (most negative)
    gap_down_ratio: float  # Fraction of days with negative gap

    # Post-rally drawdown (after big intraday gains)
    post_rally_drawdown_prob: float  # P(next day close < today close | today gain > threshold)
    post_rally_avg_return: float  # Average next-day return after rally
    rally_sample_size: int  # Number of rally days in sample

    # Risk score (0=safe, 1=dangerous)
    risk_score: float

    def to_context_str(self) -> str:
        """Format as context string for LLM prompt injection."""
        parts = [
            f"隔夜风险分析 ({self.symbol}):",
            f"  平均隔夜跳空: {self.avg_gap_pct:+.2f}% (标准差: {self.std_gap_pct:.2f}%)",
            f"  最大负跳空: {self.max_negative_gap_pct:.2f}%",
            f"  隔夜跳空为负概率: {self.gap_down_ratio:.0%}",
        ]
        if self.rally_sample_size > 0:
            parts.extend([
                f"  大涨后次日回调概率: {self.post_rally_drawdown_prob:.0%} "
                f"(样本={self.rally_sample_size}天)",
                f"  大涨后次日平均收益: {self.post_rally_avg_return:+.2f}%",
            ])
        parts.append(f"  综合隔夜风险评分: {self.risk_score:.2f}/1.00")
        return "\n".join(parts)


class OvernightRiskCalculator:
    """Calculate overnight risk metrics from historical OHLCV data."""

    def __init__(self, fetcher: Any | None = None) -> None:
        self._fetcher = fetcher

    def calculate(
        self,
        symbol: str,
        days: int = 60,
        rally_threshold: float = 5.0,
    ) -> OvernightRiskProfile | None:
        """Calculate overnight risk profile for a stock.

        Args:
            symbol: 6-digit stock code.
            days: Lookback period for historical data.
            rally_threshold: Intraday gain % to define a "rally day".

        Returns:
            OvernightRiskProfile or None if insufficient data.
        """
        df = self._fetch_ohlcv(symbol, days)
        if df is None or len(df) < 10:
            return None

        try:
            return self._compute_profile(symbol, df, rally_threshold)
        except Exception as exc:
            logger.warning("Failed to compute overnight risk for %s: %s", symbol, exc)
            return None

    def calculate_batch(
        self,
        symbols: list[str],
        days: int = 60,
        rally_threshold: float = 5.0,
    ) -> dict[str, OvernightRiskProfile]:
        """Calculate overnight risk for multiple symbols."""
        results: dict[str, OvernightRiskProfile] = {}
        for symbol in symbols:
            profile = self.calculate(symbol, days, rally_threshold)
            if profile:
                results[symbol] = profile
        return results

    @staticmethod
    def _compute_profile(
        symbol: str,
        df: pd.DataFrame,
        rally_threshold: float,
    ) -> OvernightRiskProfile:
        """Core computation from OHLCV DataFrame."""
        # Ensure sorted by date ascending
        if "date" in df.columns:
            df = df.sort_values("date").reset_index(drop=True)

        close = df["close"].values
        open_prices = df["open"].values

        # --- Overnight gap: open[t+1] / close[t] - 1 ---
        gaps = []
        for i in range(len(close) - 1):
            if close[i] > 0:
                gap = (open_prices[i + 1] / close[i] - 1) * 100
                gaps.append(gap)

        if not gaps:
            return OvernightRiskProfile(
                symbol=symbol,
                avg_gap_pct=0, std_gap_pct=0, max_negative_gap_pct=0,
                gap_down_ratio=0, post_rally_drawdown_prob=0,
                post_rally_avg_return=0, rally_sample_size=0, risk_score=0.5,
            )

        avg_gap = sum(gaps) / len(gaps)
        std_gap = (sum((g - avg_gap) ** 2 for g in gaps) / len(gaps)) ** 0.5
        max_neg_gap = min(gaps) if gaps else 0
        gap_down_ratio = sum(1 for g in gaps if g < 0) / len(gaps)

        # --- Post-rally analysis ---
        # Calculate intraday change for each day
        intraday_changes = []
        for i in range(len(df)):
            if "change_pct" in df.columns:
                intraday_changes.append(float(df["change_pct"].iloc[i]))
            elif open_prices[i] > 0:
                intraday_changes.append((close[i] / open_prices[i] - 1) * 100)
            else:
                intraday_changes.append(0)

        # Find rally days and check next-day returns
        rally_next_returns = []
        for i in range(len(intraday_changes) - 1):
            if intraday_changes[i] >= rally_threshold:
                # Next-day return: close[t+1] / close[t] - 1
                if close[i] > 0:
                    next_return = (close[i + 1] / close[i] - 1) * 100
                    rally_next_returns.append(next_return)

        if rally_next_returns:
            drawdown_prob = sum(1 for r in rally_next_returns if r < 0) / len(rally_next_returns)
            avg_post_rally = sum(rally_next_returns) / len(rally_next_returns)
        else:
            drawdown_prob = 0.5  # No data, assume neutral
            avg_post_rally = 0

        # --- Composite risk score ---
        # Higher = more dangerous to buy and hold overnight
        risk_score = _compute_risk_score(
            gap_down_ratio=gap_down_ratio,
            std_gap=std_gap,
            drawdown_prob=drawdown_prob,
            avg_post_rally=avg_post_rally,
            rally_sample_size=len(rally_next_returns),
        )

        return OvernightRiskProfile(
            symbol=symbol,
            avg_gap_pct=round(avg_gap, 4),
            std_gap_pct=round(std_gap, 4),
            max_negative_gap_pct=round(max_neg_gap, 4),
            gap_down_ratio=round(gap_down_ratio, 4),
            post_rally_drawdown_prob=round(drawdown_prob, 4),
            post_rally_avg_return=round(avg_post_rally, 4),
            rally_sample_size=len(rally_next_returns),
            risk_score=round(risk_score, 4),
        )

    def _fetch_ohlcv(self, symbol: str, days: int) -> pd.DataFrame | None:
        """Fetch historical OHLCV data via DataFetcher."""
        if self._fetcher is None:
            try:
                from src.data.fetcher import StockDataFetcher
                self._fetcher = StockDataFetcher()
            except Exception as exc:
                logger.warning("Cannot create StockDataFetcher: %s", exc)
                return None

        try:
            from datetime import datetime, timedelta
            end = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=days + 30)).strftime("%Y%m%d")
            df = self._fetcher.fetch_daily_ohlcv(symbol, start_date=start, end_date=end)
            if df is not None and not df.empty:
                # Take only last N trading days
                return df.tail(days)
            return None
        except Exception as exc:
            logger.debug("OHLCV fetch failed for %s: %s", symbol, exc)
            return None


def _compute_risk_score(
    *,
    gap_down_ratio: float,
    std_gap: float,
    drawdown_prob: float,
    avg_post_rally: float,
    rally_sample_size: int,
) -> float:
    """Compute composite overnight risk score (0-1).

    Weights:
    - gap_down_ratio (30%): How often does the stock gap down?
    - std_gap (20%): How volatile are overnight gaps?
    - drawdown_prob (30%): How likely is a drawdown after a rally?
    - avg_post_rally (20%): Average return after rally (negative = risky)
    """
    # Normalize each component to [0, 1]
    gap_risk = min(1.0, gap_down_ratio)  # Already 0-1
    vol_risk = min(1.0, std_gap / 3.0)  # 3% std = max risk
    drawdown_risk = min(1.0, drawdown_prob) if rally_sample_size >= 3 else 0.5
    # Negative post-rally return = high risk
    return_risk = min(1.0, max(0, 0.5 - avg_post_rally / 10)) if rally_sample_size >= 3 else 0.5

    return (
        gap_risk * 0.30
        + vol_risk * 0.20
        + drawdown_risk * 0.30
        + return_risk * 0.20
    )
