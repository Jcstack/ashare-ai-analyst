"""Cross-sector correlation monitor — detects correlation breaks between sectors.

Monitors rolling correlations between sector indices/ETFs. When normally-correlated
sectors diverge, it signals structural regime changes or rotation opportunities.

Inspired by: Renaissance Technologies cross-asset regime detection,
             Hidden Markov Model approaches to correlation stationarity.
"""

from __future__ import annotations

import dataclasses
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Pre-defined sector pairs that are normally correlated
CORRELATED_PAIRS: list[tuple[str, str]] = [
    ("半导体", "消费电子"),
    ("光伏", "锂电池"),
    ("白酒", "食品饮料"),
    ("银行", "保险"),
    ("地产", "建材"),
    ("医药", "医疗器械"),
    ("汽车", "汽车零部件"),
    ("钢铁", "煤炭"),
]


@dataclasses.dataclass
class CorrelationBreak:
    sector_a: str
    sector_b: str
    current_correlation: float  # current rolling correlation
    historical_correlation: float  # longer-term average correlation
    deviation: float  # how far current deviates from historical
    break_type: str  # "divergence" | "convergence" | "reversal"
    severity: float  # 0-1
    leading_sector: str  # which sector is leading the move
    description: str  # Chinese description


@dataclasses.dataclass
class CorrelationRegime:
    regime: str  # "normal" | "stress" | "rotation" | "crisis"
    avg_cross_correlation: float  # average correlation across all pairs
    break_count: int  # number of pairs showing breaks
    breaks: list[CorrelationBreak]
    crisis_signal: bool  # True if correlations converging toward 1.0
    description: str  # Chinese description


class SectorCorrelationMonitor:
    """Monitor cross-sector correlations for regime detection."""

    # Rolling window for current correlation (30-min at 5-min bars = 6 bars)
    SHORT_WINDOW = 6
    # Rolling window for historical correlation baseline
    LONG_WINDOW = 48  # ~4 hours
    # Threshold for correlation break detection
    BREAK_THRESHOLD = 0.4  # deviation from historical
    # Crisis threshold — all correlations converging
    CRISIS_CORRELATION = 0.8

    def analyze(self, sector_returns: dict[str, pd.Series]) -> CorrelationRegime:
        """Analyze sector return series for correlation breaks.

        Args:
            sector_returns: dict mapping sector name -> pd.Series of 5-min returns
                           (indexed by datetime)

        Returns:
            CorrelationRegime with detected breaks
        """
        breaks: list[CorrelationBreak] = []
        all_current_corrs: list[float] = []

        for sector_a, sector_b in CORRELATED_PAIRS:
            if sector_a not in sector_returns or sector_b not in sector_returns:
                continue

            ret_a = sector_returns[sector_a]
            ret_b = sector_returns[sector_b]

            # Align series on index
            aligned = pd.concat([ret_a, ret_b], axis=1, join="inner")
            if len(aligned) < self.SHORT_WINDOW:
                logger.debug(
                    "Insufficient data for %s/%s (%d bars, need %d)",
                    sector_a,
                    sector_b,
                    len(aligned),
                    self.SHORT_WINDOW,
                )
                continue

            col_a = aligned.iloc[:, 0]
            col_b = aligned.iloc[:, 1]

            # Compute rolling correlations
            short_corr = col_a.rolling(self.SHORT_WINDOW).corr(col_b)
            current_corr = short_corr.iloc[-1]

            if np.isnan(current_corr):
                continue

            # Historical correlation: use long window if enough data, else all data
            if len(aligned) >= self.LONG_WINDOW:
                long_corr = col_a.rolling(self.LONG_WINDOW).corr(col_b)
                hist_corr = long_corr.iloc[-1]
            else:
                hist_corr = col_a.corr(col_b)

            if np.isnan(hist_corr):
                continue

            all_current_corrs.append(current_corr)

            deviation = current_corr - hist_corr

            # Classify break type
            break_type: str | None = None
            if current_corr < -0.3:
                break_type = "reversal"
            elif deviation < -self.BREAK_THRESHOLD:
                break_type = "divergence"
            elif deviation > self.BREAK_THRESHOLD:
                break_type = "convergence"

            if break_type is None:
                continue

            severity = min(1.0, abs(deviation) / 0.8)

            # Leading sector: larger absolute return in short window
            abs_ret_a = col_a.iloc[-self.SHORT_WINDOW :].abs().sum()
            abs_ret_b = col_b.iloc[-self.SHORT_WINDOW :].abs().sum()
            leading = sector_a if abs_ret_a >= abs_ret_b else sector_b

            # Determine direction for description
            net_ret_leading = (
                col_a.iloc[-self.SHORT_WINDOW :].sum()
                if leading == sector_a
                else col_b.iloc[-self.SHORT_WINDOW :].sum()
            )
            direction = "领涨" if net_ret_leading > 0 else "领跌"

            desc = (
                f"{sector_a}与{sector_b}相关性断裂"
                f"(当前{current_corr:.2f} vs 历史{hist_corr:.2f})，"
                f"{leading}{direction}"
            )

            breaks.append(
                CorrelationBreak(
                    sector_a=sector_a,
                    sector_b=sector_b,
                    current_correlation=round(current_corr, 4),
                    historical_correlation=round(hist_corr, 4),
                    deviation=round(deviation, 4),
                    break_type=break_type,
                    severity=round(severity, 4),
                    leading_sector=leading,
                    description=desc,
                )
            )

        # Regime classification
        break_count = len(breaks)
        avg_corr = float(np.mean(all_current_corrs)) if all_current_corrs else 0.0
        crisis_signal = (
            len(all_current_corrs) >= 3 and avg_corr > self.CRISIS_CORRELATION
        )

        if crisis_signal:
            regime = "crisis"
            regime_desc = (
                f"⚠️ 全市场相关性趋向1.0，流动性危机信号(平均相关性{avg_corr:.2f})"
            )
        elif break_count >= 2:
            # Check for rotation: breaks with different leading sectors
            leading_sectors = {b.leading_sector for b in breaks}
            if len(leading_sectors) >= 2:
                regime = "rotation"
                regime_desc = f"市场处于轮动状态，{break_count}组板块相关性异常"
            else:
                regime = "stress"
                regime_desc = f"市场处于压力状态，{break_count}组板块相关性异常"
        elif break_count == 1:
            regime = "stress"
            regime_desc = f"市场处于压力状态，{break_count}组板块相关性异常"
        else:
            regime = "normal"
            regime_desc = "市场相关性结构正常"

        return CorrelationRegime(
            regime=regime,
            avg_cross_correlation=round(avg_corr, 4),
            break_count=break_count,
            breaks=breaks,
            crisis_signal=crisis_signal,
            description=regime_desc,
        )

    def analyze_from_prices(
        self, sector_prices: dict[str, pd.Series]
    ) -> CorrelationRegime:
        """Convenience method — converts prices to returns first."""
        sector_returns: dict[str, pd.Series] = {}
        for name, prices in sector_prices.items():
            if len(prices) < 2:
                continue
            returns = prices.pct_change().dropna()
            if not returns.empty:
                sector_returns[name] = returns
        return self.analyze(sector_returns)
