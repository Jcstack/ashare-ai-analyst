"""Unit tests for PerformanceMetrics.

Tests cover:
- Total return calculation with known input/output
- Sharpe ratio calculation with 2.5% risk-free rate
- Max drawdown from a known drawdown scenario
- Win rate calculation from winning/losing trades
- Report generation produces Chinese output
- Graceful handling of zero-trade edge case
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.backtest.engine import BacktestResult
from src.backtest.metrics import (
    PerformanceMetrics,
    RISK_FREE_RATE,
)


# ---- Helpers ------------------------------------------------------------


def _make_trade(
    date: str, action: str, price: float, shares: int, commission: float
) -> dict:
    """Build a single trade dict."""
    return {
        "date": pd.Timestamp(date),
        "action": action,
        "price": price,
        "shares": shares,
        "commission": commission,
        "value": price * shares,
    }


def _returns_from_equity(equity: list[float]) -> list[float]:
    """Compute daily returns from an equity curve."""
    returns = [0.0]
    for i in range(1, len(equity)):
        returns.append((equity[i] - equity[i - 1]) / equity[i - 1])
    return returns


# ---- Fixtures -----------------------------------------------------------


@pytest.fixture
def metrics() -> PerformanceMetrics:
    """Return a PerformanceMetrics instance."""
    return PerformanceMetrics()


@pytest.fixture
def profitable_result() -> BacktestResult:
    """BacktestResult with 20% return and two round-trips (1 win, 1 loss)."""
    trades = [
        _make_trade("2024-01-05", "buy", 10.0, 1000, 5.0),
        _make_trade("2024-01-15", "sell", 12.0, 1000, 17.0),
        _make_trade("2024-02-01", "buy", 11.0, 1000, 5.0),
        _make_trade("2024-02-10", "sell", 10.5, 1000, 15.5),
    ]
    equity = [
        100_000.0,
        100_200.0,
        100_500.0,
        101_000.0,
        101_500.0,
        102_000.0,
        103_000.0,
        104_000.0,
        105_000.0,
        106_000.0,
        107_000.0,
        108_000.0,
        109_000.0,
        110_000.0,
        111_000.0,
        112_000.0,
        113_000.0,
        114_000.0,
        116_000.0,
        120_000.0,
    ]
    return BacktestResult(
        trades=trades,
        equity_curve=equity,
        daily_returns=_returns_from_equity(equity),
        initial_capital=100_000.0,
        final_capital=120_000.0,
    )


@pytest.fixture
def losing_result() -> BacktestResult:
    """BacktestResult with -10% return."""
    trades = [
        _make_trade("2024-01-05", "buy", 10.0, 1000, 5.0),
        _make_trade("2024-01-15", "sell", 9.0, 1000, 14.0),
    ]
    equity = [
        100_000.0,
        99_500.0,
        99_000.0,
        98_000.0,
        97_000.0,
        96_000.0,
        95_000.0,
        94_000.0,
        93_000.0,
        90_000.0,
    ]
    return BacktestResult(
        trades=trades,
        equity_curve=equity,
        daily_returns=_returns_from_equity(equity),
        initial_capital=100_000.0,
        final_capital=90_000.0,
    )


@pytest.fixture
def no_trades_result() -> BacktestResult:
    """BacktestResult with zero trades."""
    return BacktestResult(
        trades=[],
        equity_curve=[100_000.0] * 20,
        daily_returns=[0.0] * 20,
        initial_capital=100_000.0,
        final_capital=100_000.0,
    )


@pytest.fixture
def drawdown_result() -> BacktestResult:
    """Peak at 120k, trough at 90k => drawdown = 25%."""
    equity = [
        100_000.0,
        110_000.0,
        120_000.0,
        115_000.0,
        105_000.0,
        95_000.0,
        90_000.0,
        95_000.0,
        100_000.0,
        110_000.0,
    ]
    return BacktestResult(
        trades=[],
        equity_curve=equity,
        daily_returns=_returns_from_equity(equity),
        initial_capital=100_000.0,
        final_capital=110_000.0,
    )


# ---- Tests ---------------------------------------------------------------


class TestCalculateTotalReturn:
    """Verify total return calculation."""

    def test_calculate_total_return_positive(self, metrics, profitable_result):
        """20% gain should produce total_return = 0.20."""
        result = metrics.calculate(profitable_result)
        assert result["total_return"] == pytest.approx(0.20)

    def test_calculate_total_return_negative(self, metrics, losing_result):
        """10% loss should produce total_return = -0.10."""
        result = metrics.calculate(losing_result)
        assert result["total_return"] == pytest.approx(-0.10)

    def test_calculate_total_return_flat(self, metrics, no_trades_result):
        """No change should produce total_return = 0.0."""
        result = metrics.calculate(no_trades_result)
        assert result["total_return"] == pytest.approx(0.0)

    def test_total_return_formula(self, metrics):
        """Verify the formula: (final - initial) / initial."""
        result = BacktestResult(
            trades=[],
            equity_curve=[200_000.0],
            daily_returns=[0.0],
            initial_capital=100_000.0,
            final_capital=250_000.0,
        )
        assert metrics.calculate(result)["total_return"] == pytest.approx(1.50)


class TestCalculateSharpeRatio:
    """Verify Sharpe ratio uses 2.5% risk-free rate."""

    def test_calculate_sharpe_ratio_positive(self, metrics, profitable_result):
        """A profitable result should have a positive Sharpe ratio."""
        assert metrics.calculate(profitable_result)["sharpe_ratio"] > 0

    def test_calculate_sharpe_ratio_negative(self, metrics, losing_result):
        """A losing result should have a negative Sharpe ratio."""
        assert metrics.calculate(losing_result)["sharpe_ratio"] < 0

    def test_risk_free_rate_is_two_point_five_percent(self):
        """The module constant should be 0.025."""
        assert RISK_FREE_RATE == pytest.approx(0.025)

    def test_sharpe_zero_std(self, metrics):
        """Zero standard deviation should return Sharpe = 0.0."""
        result = BacktestResult(
            trades=[],
            equity_curve=[100_000.0] * 10,
            daily_returns=[0.0] * 10,
            initial_capital=100_000.0,
            final_capital=100_000.0,
        )
        assert metrics.calculate(result)["sharpe_ratio"] == pytest.approx(0.0)

    def test_sharpe_single_day(self, metrics):
        """Single data point should return Sharpe = 0.0."""
        result = BacktestResult(
            trades=[],
            equity_curve=[100_000.0],
            daily_returns=[0.0],
            initial_capital=100_000.0,
            final_capital=100_000.0,
        )
        assert metrics.calculate(result)["sharpe_ratio"] == pytest.approx(0.0)


class TestCalculateMaxDrawdown:
    """Verify maximum drawdown from known scenarios."""

    def test_calculate_max_drawdown(self, metrics, drawdown_result):
        """Peak 120k to trough 90k = 25% drawdown."""
        assert metrics.calculate(drawdown_result)["max_drawdown"] == pytest.approx(0.25)

    def test_no_drawdown_monotonic_increase(self, metrics):
        """A monotonically increasing curve has zero drawdown."""
        equity = [100_000.0 + i * 1000 for i in range(20)]
        result = BacktestResult(
            trades=[],
            equity_curve=equity,
            daily_returns=_returns_from_equity(equity),
            initial_capital=100_000.0,
            final_capital=equity[-1],
        )
        assert metrics.calculate(result)["max_drawdown"] == pytest.approx(0.0)

    def test_drawdown_entire_period_decline(self, metrics):
        """Steady decline: drawdown = (100k - 70k) / 100k = 30%."""
        equity = [100_000.0, 90_000.0, 80_000.0, 70_000.0]
        result = BacktestResult(
            trades=[],
            equity_curve=equity,
            daily_returns=_returns_from_equity(equity),
            initial_capital=100_000.0,
            final_capital=70_000.0,
        )
        assert metrics.calculate(result)["max_drawdown"] == pytest.approx(0.30)


class TestCalculateWinRate:
    """Verify win rate from winning/losing trade pairs."""

    def test_calculate_win_rate(self, metrics, profitable_result):
        """One win + one loss = 50% win rate."""
        assert metrics.calculate(profitable_result)["win_rate"] == pytest.approx(0.50)

    def test_all_winning_trades(self, metrics):
        """All winning trades should give 100% win rate."""
        trades = [
            _make_trade("2024-01-05", "buy", 10.0, 100, 5.0),
            _make_trade("2024-01-10", "sell", 12.0, 100, 5.0),
        ]
        result = BacktestResult(
            trades=trades,
            equity_curve=[100_000.0] * 5,
            daily_returns=[0.0] * 5,
            initial_capital=100_000.0,
            final_capital=100_200.0,
        )
        assert metrics.calculate(result)["win_rate"] == pytest.approx(1.0)

    def test_all_losing_trades(self, metrics):
        """All losing trades should give 0% win rate."""
        trades = [
            _make_trade("2024-01-05", "buy", 12.0, 100, 5.0),
            _make_trade("2024-01-10", "sell", 10.0, 100, 5.0),
        ]
        result = BacktestResult(
            trades=trades,
            equity_curve=[100_000.0] * 5,
            daily_returns=[0.0] * 5,
            initial_capital=100_000.0,
            final_capital=99_800.0,
        )
        assert metrics.calculate(result)["win_rate"] == pytest.approx(0.0)


class TestGenerateReportInChinese:
    """Verify report output is in Chinese."""

    def test_generate_report_in_chinese(self, metrics, profitable_result):
        """Report should contain all expected Chinese labels."""
        m = metrics.calculate(profitable_result)
        report = metrics.generate_report(m)
        for label in [
            "回测绩效报告",
            "总收益率",
            "年化收益率",
            "夏普比率",
            "最大回撤",
            "胜率",
            "盈亏比",
            "交易次数",
            "平均持仓天数",
            "综合评级",
        ]:
            assert label in report

    def test_report_contains_disclaimer(self, metrics, profitable_result):
        """Report must include the investment disclaimer."""
        report = metrics.generate_report(metrics.calculate(profitable_result))
        assert "不构成任何投资建议" in report

    def test_report_rating_excellent(self, metrics):
        """Sharpe >= 2.0 should be rated '优秀'."""
        assert "优秀" in metrics.generate_report({"sharpe_ratio": 2.5})

    def test_report_rating_good(self, metrics):
        """Sharpe >= 1.0 and < 2.0 should be rated '良好'."""
        assert "良好" in metrics.generate_report({"sharpe_ratio": 1.5})

    def test_report_rating_average(self, metrics):
        """Sharpe >= 0.5 and < 1.0 should be rated '一般'."""
        assert "一般" in metrics.generate_report({"sharpe_ratio": 0.7})

    def test_report_rating_poor(self, metrics):
        """Sharpe < 0.5 should be rated '较差'."""
        assert "较差" in metrics.generate_report({"sharpe_ratio": 0.2})


class TestNoTradesMetrics:
    """Verify graceful handling of zero-trade scenarios."""

    def test_no_trades_metrics(self, metrics, no_trades_result):
        """Zero trades should not crash and return sensible defaults."""
        result = metrics.calculate(no_trades_result)
        assert result["total_return"] == pytest.approx(0.0)
        assert result["total_trades"] == 0
        assert result["win_rate"] == pytest.approx(0.0)
        assert result["profit_factor"] == pytest.approx(0.0)
        assert result["avg_holding_days"] == pytest.approx(0.0)

    def test_no_trades_report_generates(self, metrics, no_trades_result):
        """Report should still be generated even with zero trades."""
        report = metrics.generate_report(metrics.calculate(no_trades_result))
        assert isinstance(report, str) and len(report) > 0


class TestProfitFactor:
    """Verify profit factor calculation."""

    def test_profit_factor_mixed(self, metrics, profitable_result):
        """Profit factor should be positive for mixed win/loss."""
        assert metrics.calculate(profitable_result)["profit_factor"] > 0

    def test_profit_factor_all_wins(self, metrics):
        """All-win scenario should return infinity."""
        trades = [
            _make_trade("2024-01-05", "buy", 10.0, 100, 0.0),
            _make_trade("2024-01-10", "sell", 12.0, 100, 0.0),
        ]
        result = BacktestResult(
            trades=trades,
            equity_curve=[100_000.0] * 5,
            daily_returns=[0.0] * 5,
            initial_capital=100_000.0,
            final_capital=100_200.0,
        )
        assert metrics.calculate(result)["profit_factor"] == float("inf")


class TestAvgHoldingDays:
    """Verify average holding days calculation."""

    def test_avg_holding_days(self, metrics, profitable_result):
        """Average: (Jan5->Jan15=10d + Feb1->Feb10=9d) / 2 = 9.5."""
        assert metrics.calculate(profitable_result)[
            "avg_holding_days"
        ] == pytest.approx(9.5)

    def test_avg_holding_days_no_trades(self, metrics, no_trades_result):
        """Zero trades should return 0.0 avg holding days."""
        assert metrics.calculate(no_trades_result)["avg_holding_days"] == pytest.approx(
            0.0
        )


class TestAnnualReturn:
    """Verify annualized return calculation."""

    def test_annual_return_one_year(self, metrics):
        """252 trading days with 20% return should annualize to ~20%."""
        result = BacktestResult(
            trades=[],
            equity_curve=[100_000.0] * 252,
            daily_returns=[0.0] * 252,
            initial_capital=100_000.0,
            final_capital=120_000.0,
        )
        assert metrics.calculate(result)["annual_return"] == pytest.approx(
            0.20, abs=0.001
        )

    def test_annual_return_half_year(self, metrics):
        """126 days with 10% return annualizes to ~21%."""
        result = BacktestResult(
            trades=[],
            equity_curve=[100_000.0] * 126,
            daily_returns=[0.0] * 126,
            initial_capital=100_000.0,
            final_capital=110_000.0,
        )
        expected = (1.10) ** (252 / 126) - 1.0
        assert metrics.calculate(result)["annual_return"] == pytest.approx(
            expected, abs=0.001
        )
