"""Performance metrics for A-share backtest evaluation.

Computes standard portfolio performance metrics and generates
Chinese-language summary reports.

Implements FR-B002 from the PRD.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from src.backtest.engine import BacktestResult
from src.utils.logger import get_logger

logger = get_logger(__name__)

# A-share convention: 252 trading days per year
TRADING_DAYS_PER_YEAR: int = 252

# Risk-free rate used for Sharpe ratio (PRD: 2.5%)
RISK_FREE_RATE: float = 0.025


class PerformanceMetrics:
    """Calculate and report backtest performance metrics.

    Metrics produced:

    * **total_return** -- cumulative return over the period.
    * **annual_return** -- annualized return assuming 252 trading days.
    * **sharpe_ratio** -- risk-adjusted return using 2.5% risk-free rate.
    * **max_drawdown** -- largest peak-to-trough decline.
    * **win_rate** -- fraction of profitable round-trip trades.
    * **profit_factor** -- gross profits / gross losses.
    * **total_trades** -- number of completed round-trip trades.
    * **avg_holding_days** -- mean holding period in trading days.
    """

    def __init__(self) -> None:
        logger.info("PerformanceMetrics initialized.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate(self, result: BacktestResult) -> dict[str, Any]:
        """Calculate all performance metrics from a backtest result.

        Args:
            result: A :class:`BacktestResult` produced by
                :meth:`BacktestEngine.run`.

        Returns:
            Dictionary with metric names as keys and numeric values.
            Keys: ``total_return``, ``annual_return``, ``sharpe_ratio``,
            ``max_drawdown``, ``win_rate``, ``profit_factor``,
            ``total_trades``, ``avg_holding_days``.
        """
        total_return = self._total_return(result)
        num_days = len(result.equity_curve)
        annual_return = self._annual_return(total_return, num_days)
        sharpe_ratio = self._sharpe_ratio(result.daily_returns)
        max_drawdown = self._max_drawdown(result.equity_curve)

        round_trips = self._extract_round_trips(result.trades)
        win_rate = self._win_rate(round_trips)
        profit_factor = self._profit_factor(round_trips)
        total_trades = len(round_trips)
        avg_holding_days = self._avg_holding_days(round_trips)

        metrics: dict[str, Any] = {
            "total_return": total_return,
            "annual_return": annual_return,
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown": max_drawdown,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "total_trades": total_trades,
            "avg_holding_days": avg_holding_days,
        }

        logger.info(
            "Metrics calculated: total_return=%.4f, sharpe=%.4f, "
            "max_drawdown=%.4f, trades=%d",
            total_return,
            sharpe_ratio,
            max_drawdown,
            total_trades,
        )
        return metrics

    def generate_report(self, metrics: dict[str, Any]) -> str:
        """Generate a Chinese-language performance summary report.

        Args:
            metrics: Dictionary returned by :meth:`calculate`.

        Returns:
            Multi-line string containing a formatted Chinese report
            with all metrics and a rating classification.
        """
        rating = self._rating(metrics.get("sharpe_ratio", 0.0))

        report_lines = [
            "=" * 50,
            "        回测绩效报告",
            "=" * 50,
            "",
            f"总收益率:        {metrics.get('total_return', 0.0):.2%}",
            f"年化收益率:      {metrics.get('annual_return', 0.0):.2%}",
            f"夏普比率:        {metrics.get('sharpe_ratio', 0.0):.4f}",
            f"最大回撤:        {metrics.get('max_drawdown', 0.0):.2%}",
            f"胜率:            {metrics.get('win_rate', 0.0):.2%}",
            f"盈亏比:          {metrics.get('profit_factor', 0.0):.4f}",
            f"交易次数:        {metrics.get('total_trades', 0)}",
            f"平均持仓天数:    {metrics.get('avg_holding_days', 0.0):.1f}",
            "",
            "-" * 50,
            f"综合评级:        {rating}",
            "-" * 50,
            "",
            "注: 本报告仅供研究学习使用，不构成任何投资建议。",
        ]
        return "\n".join(report_lines)

    def calculate_attribution(self, result: BacktestResult) -> dict[str, Any]:
        """Calculate attribution data for backtest results.

        Groups round-trips by month, computes monthly P&L, signal
        distribution, and grouped win rates.

        Args:
            result: A :class:`BacktestResult` produced by the engine.

        Returns:
            Dictionary with keys: ``monthly_pnl``, ``signal_distribution``,
            ``monthly_win_rates``.
        """
        round_trips = result.round_trips
        signals = result.signals

        # Monthly P&L from round-trips
        monthly_pnl: dict[str, float] = {}
        monthly_wins: dict[str, int] = {}
        monthly_total: dict[str, int] = {}

        for rt in round_trips:
            sell_date = rt.get("sell_date", "")
            month_key = sell_date[:7] if sell_date else "unknown"
            monthly_pnl[month_key] = monthly_pnl.get(month_key, 0.0) + rt.get(
                "pnl", 0.0
            )
            monthly_total[month_key] = monthly_total.get(month_key, 0) + 1
            if rt.get("pnl", 0.0) > 0:
                monthly_wins[month_key] = monthly_wins.get(month_key, 0) + 1

        # Monthly win rates
        monthly_win_rates: dict[str, float] = {}
        for month, total in monthly_total.items():
            wins = monthly_wins.get(month, 0)
            monthly_win_rates[month] = round(wins / total, 4) if total > 0 else 0.0

        # Signal distribution
        buy_count = sum(1 for s in signals if s.get("signal") == 1)
        sell_count = sum(1 for s in signals if s.get("signal") == -1)
        hold_count = sum(1 for s in signals if s.get("signal") == 0)

        return {
            "monthly_pnl": monthly_pnl,
            "signal_distribution": {
                "buy": buy_count,
                "sell": sell_count,
                "hold": hold_count,
            },
            "monthly_win_rates": monthly_win_rates,
        }

    # ------------------------------------------------------------------
    # Metric computation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _total_return(result: BacktestResult) -> float:
        """Compute total return: (final - initial) / initial.

        Args:
            result: The backtest result.

        Returns:
            Total return as a decimal (e.g. 0.15 for 15%).
        """
        if result.initial_capital == 0:
            return 0.0
        return (result.final_capital - result.initial_capital) / result.initial_capital

    @staticmethod
    def _annual_return(total_return: float, num_days: int) -> float:
        """Annualize a total return over a given number of trading days.

        Uses the formula:
            ``(1 + total_return) ^ (252 / num_days) - 1``

        Args:
            total_return: Cumulative return as a decimal.
            num_days: Number of trading days in the backtest period.

        Returns:
            Annualized return as a decimal.
        """
        if num_days <= 0:
            return 0.0
        if total_return <= -1.0:
            return -1.0
        years_fraction = num_days / TRADING_DAYS_PER_YEAR
        if years_fraction == 0:
            return 0.0
        return (1.0 + total_return) ** (1.0 / years_fraction) - 1.0

    @staticmethod
    def _sharpe_ratio(daily_returns: list[float]) -> float:
        """Calculate the annualized Sharpe ratio.

        Sharpe = (annualized_return - risk_free_rate) / annualized_std

        The risk-free rate is 2.5% per PRD specification.

        Args:
            daily_returns: List of daily percentage returns.

        Returns:
            Annualized Sharpe ratio.  Returns ``0.0`` when standard
            deviation is zero or there are insufficient data points.
        """
        if len(daily_returns) < 2:
            return 0.0

        mean_daily = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean_daily) ** 2 for r in daily_returns) / (
            len(daily_returns) - 1
        )
        daily_std = math.sqrt(variance) if variance > 0 else 0.0

        if daily_std == 0.0:
            return 0.0

        annual_return = mean_daily * TRADING_DAYS_PER_YEAR
        annual_std = daily_std * math.sqrt(TRADING_DAYS_PER_YEAR)

        return (annual_return - RISK_FREE_RATE) / annual_std

    @staticmethod
    def _max_drawdown(equity_curve: list[float]) -> float:
        """Calculate the maximum drawdown from the equity curve.

        Maximum drawdown is the largest peak-to-trough decline expressed
        as a positive fraction (e.g. 0.20 for a 20% drawdown).

        Args:
            equity_curve: List of daily portfolio values.

        Returns:
            Maximum drawdown as a positive decimal.  Returns ``0.0``
            for an empty or single-value curve.
        """
        if len(equity_curve) < 2:
            return 0.0

        peak = equity_curve[0]
        max_dd = 0.0
        for value in equity_curve:
            if value > peak:
                peak = value
            if peak > 0:
                drawdown = (peak - value) / peak
                if drawdown > max_dd:
                    max_dd = drawdown
        return max_dd

    @staticmethod
    def _extract_round_trips(
        trades: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Pair buy/sell trades into round-trip records.

        Each round trip contains: ``buy_date``, ``sell_date``,
        ``buy_price``, ``sell_price``, ``shares``, ``pnl``,
        ``holding_days``.

        Args:
            trades: Flat list of trade dictionaries from the engine.

        Returns:
            List of round-trip dictionaries.
        """
        round_trips: list[dict[str, Any]] = []
        pending_buy: dict[str, Any] | None = None

        for trade in trades:
            if trade["action"] == "buy":
                pending_buy = trade
            elif trade["action"] == "sell" and pending_buy is not None:
                buy_date = pd.Timestamp(pending_buy["date"])
                sell_date = pd.Timestamp(trade["date"])
                holding_days = (sell_date - buy_date).days

                buy_value = pending_buy["price"] * pending_buy["shares"]
                sell_value = trade["price"] * trade["shares"]
                pnl = (
                    sell_value
                    - buy_value
                    - pending_buy["commission"]
                    - trade["commission"]
                )

                round_trips.append(
                    {
                        "buy_date": buy_date,
                        "sell_date": sell_date,
                        "buy_price": pending_buy["price"],
                        "sell_price": trade["price"],
                        "shares": pending_buy["shares"],
                        "pnl": pnl,
                        "holding_days": holding_days,
                    }
                )
                pending_buy = None

        return round_trips

    @staticmethod
    def _win_rate(round_trips: list[dict[str, Any]]) -> float:
        """Fraction of round-trip trades that are profitable.

        Args:
            round_trips: List of round-trip dictionaries.

        Returns:
            Win rate in ``[0, 1]``.  Returns ``0.0`` for no trades.
        """
        if not round_trips:
            return 0.0
        winners = sum(1 for rt in round_trips if rt["pnl"] > 0)
        return winners / len(round_trips)

    @staticmethod
    def _profit_factor(round_trips: list[dict[str, Any]]) -> float:
        """Ratio of gross profits to gross losses.

        Args:
            round_trips: List of round-trip dictionaries.

        Returns:
            Profit factor (>1 is profitable).  Returns ``0.0`` when
            there are no trades or no losses.
        """
        if not round_trips:
            return 0.0
        gross_profit = sum(rt["pnl"] for rt in round_trips if rt["pnl"] > 0)
        gross_loss = sum(abs(rt["pnl"]) for rt in round_trips if rt["pnl"] < 0)
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    @staticmethod
    def _avg_holding_days(round_trips: list[dict[str, Any]]) -> float:
        """Average holding period in calendar days.

        Args:
            round_trips: List of round-trip dictionaries.

        Returns:
            Mean holding days.  Returns ``0.0`` for no trades.
        """
        if not round_trips:
            return 0.0
        total_days = sum(rt["holding_days"] for rt in round_trips)
        return total_days / len(round_trips)

    @staticmethod
    def _rating(sharpe_ratio: float) -> str:
        """Classify strategy quality based on the Sharpe ratio.

        Args:
            sharpe_ratio: The annualized Sharpe ratio.

        Returns:
            Chinese rating string: ``"优秀"`` (excellent),
            ``"良好"`` (good), ``"一般"`` (average), or
            ``"较差"`` (poor).
        """
        if sharpe_ratio >= 2.0:
            return "优秀"
        if sharpe_ratio >= 1.0:
            return "良好"
        if sharpe_ratio >= 0.5:
            return "一般"
        return "较差"
