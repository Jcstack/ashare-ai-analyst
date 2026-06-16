"""Walk-forward validation engine for strategy robustness testing.

Splits historical data into rolling train/test windows and evaluates
strategy performance across each window. Detects overfitting by comparing
in-sample vs out-of-sample Sharpe ratios.

Part of v15.0 Quant Core layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("quant.walk_forward")

# A-share convention
TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE = 0.025


@dataclass
class WindowResult:
    """Result of evaluating one train/test window pair.

    Attributes:
        window_index: Sequential window number (0-based).
        train_start: ISO date string for training period start.
        train_end: ISO date string for training period end.
        test_start: ISO date string for test period start.
        test_end: ISO date string for test period end.
        train_sharpe: Sharpe ratio computed on training data.
        test_sharpe: Sharpe ratio computed on test data.
        train_return: Total return on training data.
        test_return: Total return on test data.
        train_trades: Number of trades in training period.
        test_trades: Number of trades in test period.
        degradation: 1 - (test_sharpe / train_sharpe), higher = worse.
        is_overfit: Whether degradation exceeds threshold.
    """

    window_index: int = 0
    train_start: str = ""
    train_end: str = ""
    test_start: str = ""
    test_end: str = ""
    train_sharpe: float = 0.0
    test_sharpe: float = 0.0
    train_return: float = 0.0
    test_return: float = 0.0
    train_trades: int = 0
    test_trades: int = 0
    degradation: float = 0.0
    is_overfit: bool = False


@dataclass
class WalkForwardReport:
    """Aggregated walk-forward validation report.

    Attributes:
        windows: Individual window results.
        avg_train_sharpe: Average in-sample Sharpe across all windows.
        avg_test_sharpe: Average out-of-sample Sharpe.
        avg_degradation: Average degradation score.
        overfit_count: Number of windows flagged as overfit.
        total_windows: Total number of windows evaluated.
        is_robust: True if strategy passes walk-forward check.
        summary: Human-readable summary.
    """

    windows: list[WindowResult] = field(default_factory=list)
    avg_train_sharpe: float = 0.0
    avg_test_sharpe: float = 0.0
    avg_degradation: float = 0.0
    overfit_count: int = 0
    total_windows: int = 0
    is_robust: bool = False
    summary: str = ""


class WalkForwardValidator:
    """Rolling window walk-forward validation engine.

    Usage::

        validator = WalkForwardValidator()
        report = validator.validate(
            daily_returns=returns_series,
            trade_dates=trade_date_list,
        )
        if not report.is_robust:
            logger.warning("Strategy may be overfit: %s", report.summary)
    """

    def __init__(self) -> None:
        cfg = load_config("quant").get("walk_forward", {})
        self.train_window = cfg.get("train_window_days", 120)
        self.test_window = cfg.get("test_window_days", 30)
        self.step_days = cfg.get("step_days", 30)
        self.min_trades = cfg.get("min_trades_per_window", 5)
        self.degradation_threshold = cfg.get("degradation_threshold", 0.5)
        self.max_degradation = cfg.get("max_degradation_ratio", 0.7)

    def validate(
        self,
        daily_returns: list[float] | pd.Series,
        trade_dates: list[str] | None = None,
        dates: list[str] | None = None,
    ) -> WalkForwardReport:
        """Run walk-forward validation on a return series.

        Args:
            daily_returns: Daily percentage returns (as decimals, e.g. 0.01 = 1%).
            trade_dates: ISO date strings when trades occurred (for counting).
            dates: ISO date strings aligned with daily_returns (for window labeling).

        Returns:
            WalkForwardReport with per-window results and aggregate metrics.
        """
        returns = (
            daily_returns
            if isinstance(daily_returns, pd.Series)
            else pd.Series(daily_returns)
        )
        n = len(returns)
        total_needed = self.train_window + self.test_window

        if n < total_needed:
            return WalkForwardReport(
                summary=f"Insufficient data: {n} days < {total_needed} required",
            )

        windows: list[WindowResult] = []
        idx = 0
        window_num = 0

        while idx + total_needed <= n:
            train_start = idx
            train_end = idx + self.train_window
            test_start = train_end
            test_end = min(train_end + self.test_window, n)

            train_returns = returns.iloc[train_start:train_end]
            test_returns = returns.iloc[test_start:test_end]

            train_sharpe = _compute_sharpe(train_returns)
            test_sharpe = _compute_sharpe(test_returns)
            train_total = _total_return(train_returns)
            test_total = _total_return(test_returns)

            # Count trades in each window
            train_trades = 0
            test_trades = 0
            if trade_dates and dates:
                date_list = dates if isinstance(dates, list) else list(dates)
                train_date_set = set(date_list[train_start:train_end])
                test_date_set = set(date_list[test_start:test_end])
                train_trades = sum(1 for d in trade_dates if d in train_date_set)
                test_trades = sum(1 for d in trade_dates if d in test_date_set)

            degradation = _compute_degradation(train_sharpe, test_sharpe)
            is_overfit = degradation > self.degradation_threshold

            # Date labels
            train_start_date = (
                dates[train_start]
                if dates and train_start < len(dates)
                else str(train_start)
            )
            train_end_date = (
                dates[train_end - 1]
                if dates and train_end - 1 < len(dates)
                else str(train_end - 1)
            )
            test_start_date = (
                dates[test_start]
                if dates and test_start < len(dates)
                else str(test_start)
            )
            test_end_date = (
                dates[test_end - 1]
                if dates and test_end - 1 < len(dates)
                else str(test_end - 1)
            )

            windows.append(
                WindowResult(
                    window_index=window_num,
                    train_start=train_start_date,
                    train_end=train_end_date,
                    test_start=test_start_date,
                    test_end=test_end_date,
                    train_sharpe=train_sharpe,
                    test_sharpe=test_sharpe,
                    train_return=train_total,
                    test_return=test_total,
                    train_trades=train_trades,
                    test_trades=test_trades,
                    degradation=degradation,
                    is_overfit=is_overfit,
                )
            )

            idx += self.step_days
            window_num += 1

        if not windows:
            return WalkForwardReport(summary="No windows generated")

        avg_train = sum(w.train_sharpe for w in windows) / len(windows)
        avg_test = sum(w.test_sharpe for w in windows) / len(windows)
        avg_deg = sum(w.degradation for w in windows) / len(windows)
        overfit_count = sum(1 for w in windows if w.is_overfit)
        is_robust = (
            avg_deg < self.degradation_threshold and overfit_count < len(windows) / 2
        )

        summary_parts = [
            f"{len(windows)} windows evaluated",
            f"avg train Sharpe {avg_train:.3f}",
            f"avg test Sharpe {avg_test:.3f}",
            f"avg degradation {avg_deg:.3f}",
            f"{overfit_count}/{len(windows)} overfit",
        ]
        if is_robust:
            summary_parts.append("ROBUST")
        else:
            summary_parts.append("OVERFIT WARNING")

        return WalkForwardReport(
            windows=windows,
            avg_train_sharpe=avg_train,
            avg_test_sharpe=avg_test,
            avg_degradation=avg_deg,
            overfit_count=overfit_count,
            total_windows=len(windows),
            is_robust=is_robust,
            summary=" | ".join(summary_parts),
        )

    def generate_windows(self, n_days: int) -> list[dict[str, Any]]:
        """Generate window boundaries without computing metrics.

        Useful for previewing how data will be split.

        Args:
            n_days: Total number of trading days available.

        Returns:
            List of dicts with train_start, train_end, test_start, test_end indices.
        """
        total_needed = self.train_window + self.test_window
        windows = []
        idx = 0

        while idx + total_needed <= n_days:
            windows.append(
                {
                    "train_start": idx,
                    "train_end": idx + self.train_window,
                    "test_start": idx + self.train_window,
                    "test_end": min(idx + total_needed, n_days),
                }
            )
            idx += self.step_days

        return windows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_sharpe(returns: pd.Series) -> float:
    """Annualized Sharpe ratio from daily returns."""
    if len(returns) < 2:
        return 0.0
    mean_r = returns.mean()
    std_r = returns.std()
    if std_r == 0 or np.isnan(std_r):
        return 0.0
    daily_rf = RISK_FREE_RATE / TRADING_DAYS_PER_YEAR
    return float((mean_r - daily_rf) / std_r * np.sqrt(TRADING_DAYS_PER_YEAR))


def _total_return(returns: pd.Series) -> float:
    """Cumulative return from daily returns."""
    if len(returns) == 0:
        return 0.0
    return float((1 + returns).prod() - 1)


def _compute_degradation(train_sharpe: float, test_sharpe: float) -> float:
    """Compute degradation score: 1 - (test / train).

    Higher = worse. Values > 0.5 suggest overfitting.
    Returns 0.0 if train_sharpe <= 0 (no meaningful baseline).
    """
    if train_sharpe <= 0:
        return 0.0
    return max(0.0, 1.0 - test_sharpe / train_sharpe)
