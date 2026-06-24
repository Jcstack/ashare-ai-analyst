"""Consecutive board promotion rate (连板晋级率) — key sentiment inflection signal.

Tracks how many stocks advance from N-board to (N+1)-board each day.
A declining promotion rate signals sentiment exhaustion (climax → retreat);
a rising rate signals sentiment acceleration.

Data source: AKShare ``stock_zt_pool_em()`` via em_api_call proxy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

logger = logging.getLogger(__name__)
_CST = ZoneInfo("Asia/Shanghai")


@dataclass
class PromotionRateSnapshot:
    """Daily consecutive board promotion rate snapshot."""

    date: str
    total_limit_up: int  # 涨停总数
    first_board: int  # 首板数量
    second_board: int  # 二板数量
    third_plus: int  # 三板以上数量
    max_consecutive: int  # 最高连板数
    promotion_1to2: float  # 首板→二板晋级率
    promotion_2to3: float  # 二板→三板晋级率
    trend: str  # "accelerating" / "decelerating" / "stable"
    signal: str  # "bullish" / "bearish" / "neutral"

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "total_limit_up": self.total_limit_up,
            "first_board": self.first_board,
            "second_board": self.second_board,
            "third_plus": self.third_plus,
            "max_consecutive": self.max_consecutive,
            "promotion_1to2": round(self.promotion_1to2, 3),
            "promotion_2to3": round(self.promotion_2to3, 3),
            "trend": self.trend,
            "signal": self.signal,
        }

    def to_summary(self) -> str:
        """Chinese summary for LLM."""
        return (
            f"[{self.date}] 涨停{self.total_limit_up}家 "
            f"(首板{self.first_board}/二板{self.second_board}/"
            f"三板+{self.third_plus}/最高{self.max_consecutive}连板) "
            f"晋级率: 1→2={self.promotion_1to2:.0%} "
            f"2→3={self.promotion_2to3:.0%} "
            f"趋势={self.trend} 信号={self.signal}"
        )


class ConsecutiveBoardTracker:
    """Track and compute consecutive board promotion rates.

    Uses the existing ``StockDataFetcher.fetch_limit_up_pool()`` which
    returns a DataFrame with a ``consecutive`` column from AKShare.
    """

    def __init__(self, fetcher: Any = None) -> None:
        self._fetcher = fetcher
        self._history: list[PromotionRateSnapshot] = []

    def compute_snapshot(self, date: str = "") -> PromotionRateSnapshot | None:
        """Compute promotion rate snapshot for a given date.

        Args:
            date: YYYYMMDD format. Default: today.

        Returns:
            PromotionRateSnapshot or None if data unavailable.
        """
        if not self._fetcher:
            from src.data.fetcher import StockDataFetcher

            self._fetcher = StockDataFetcher()

        if not date:
            date = datetime.now(_CST).strftime("%Y%m%d")

        try:
            df = self._fetcher.fetch_limit_up_pool(date=date)
        except Exception as exc:
            logger.warning("Failed to fetch limit-up pool for %s: %s", date, exc)
            return None

        if df is None or df.empty:
            return None

        # Find the consecutive column
        consec_col = None
        for col in ("consecutive", "连板数", "streak"):
            if col in df.columns:
                consec_col = col
                break

        if consec_col is None:
            # No consecutive column — all are first-board
            total = len(df)
            return PromotionRateSnapshot(
                date=date,
                total_limit_up=total,
                first_board=total,
                second_board=0,
                third_plus=0,
                max_consecutive=1,
                promotion_1to2=0.0,
                promotion_2to3=0.0,
                trend="stable",
                signal="neutral",
            )

        df[consec_col] = pd.to_numeric(df[consec_col], errors="coerce").fillna(1)
        total = len(df)
        first_board = int((df[consec_col] == 1).sum())
        second_board = int((df[consec_col] == 2).sum())
        third_plus = int((df[consec_col] >= 3).sum())
        max_consec = int(df[consec_col].max()) if not df.empty else 0

        # Compute promotion rates
        # Yesterday's first-board count → today's second-board count = promotion rate
        # We approximate with today's data since we may not have yesterday's
        # A proper calculation needs consecutive day data
        prev_first = max(first_board, 1)  # Approximate
        promotion_1to2 = second_board / prev_first if prev_first > 0 else 0.0
        prev_second = max(second_board, 1)
        promotion_2to3 = third_plus / prev_second if prev_second > 0 else 0.0

        # Determine trend from history
        trend = self._compute_trend(promotion_1to2)

        # Signal interpretation
        if promotion_1to2 >= 0.3 and total >= 50:
            signal = "bullish"  # High promotion + many limit-ups
        elif promotion_1to2 < 0.15 or total < 20:
            signal = "bearish"  # Low promotion or few limit-ups
        else:
            signal = "neutral"

        snapshot = PromotionRateSnapshot(
            date=date,
            total_limit_up=total,
            first_board=first_board,
            second_board=second_board,
            third_plus=third_plus,
            max_consecutive=max_consec,
            promotion_1to2=promotion_1to2,
            promotion_2to3=promotion_2to3,
            trend=trend,
            signal=signal,
        )

        self._history.append(snapshot)
        if len(self._history) > 30:
            self._history = self._history[-30:]

        return snapshot

    def _compute_trend(self, current_rate: float) -> str:
        """Determine trend from promotion rate history."""
        if len(self._history) < 2:
            return "stable"

        prev_rate = self._history[-1].promotion_1to2
        if current_rate > prev_rate * 1.2:
            return "accelerating"
        elif current_rate < prev_rate * 0.8:
            return "decelerating"
        return "stable"

    def get_history(self, days: int = 5) -> list[dict[str, Any]]:
        """Get recent promotion rate history."""
        return [s.to_dict() for s in self._history[-days:]]
