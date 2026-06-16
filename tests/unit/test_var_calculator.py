"""Tests for VaR calculator.

Part of v17.0 Risk Engine.
"""

from __future__ import annotations

import numpy as np

from src.risk.var_calculator import VaRCalculator


class TestHistoricalVaR:
    def test_basic_calculation(self):
        calc = VaRCalculator()
        # Simulate 250 days of returns with known distribution
        rng = np.random.default_rng(42)
        returns = rng.normal(0.0005, 0.02, 250)  # ~0.05% daily mean, 2% vol

        result = calc.historical_var(returns, portfolio_value=1_000_000)
        assert result.method == "historical"
        assert result.var_pct > 0
        assert result.var_amount > 0
        assert result.cvar_pct >= result.var_pct  # CVaR >= VaR
        assert result.sample_size == 250

    def test_confidence_levels(self):
        calc = VaRCalculator()
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.02, 500)

        var_95 = calc.historical_var(returns, 1_000_000, confidence_level=0.95)
        var_99 = calc.historical_var(returns, 1_000_000, confidence_level=0.99)
        # 99% VaR should be larger than 95% VaR
        assert var_99.var_pct > var_95.var_pct

    def test_small_sample_warning(self):
        calc = VaRCalculator()
        returns = np.array([0.01, -0.02, 0.005, -0.01, 0.003])
        result = calc.historical_var(returns, 100_000)
        assert any("样本量不足" in w for w in result.warnings)

    def test_holding_period_scaling(self):
        calc = VaRCalculator()
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.02, 250)

        var_1d = calc.historical_var(returns, 1_000_000, holding_period=1)
        var_5d = calc.historical_var(returns, 1_000_000, holding_period=5)
        # 5-day VaR should be larger (sqrt-T scaling)
        assert var_5d.var_pct > var_1d.var_pct

    def test_portfolio_value_scaling(self):
        calc = VaRCalculator()
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.02, 250)

        var_small = calc.historical_var(returns, 100_000)
        var_large = calc.historical_var(returns, 1_000_000)
        # Same VaR%, different amounts
        assert abs(var_small.var_pct - var_large.var_pct) < 1e-6
        assert var_large.var_amount > var_small.var_amount


class TestParametricVaR:
    def test_basic_calculation(self):
        calc = VaRCalculator()
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.02, 250)

        result = calc.parametric_var(returns, 1_000_000)
        assert result.method == "parametric"
        assert result.var_pct > 0
        assert result.cvar_pct >= result.var_pct

    def test_zero_volatility(self):
        calc = VaRCalculator()
        returns = np.array([0.01] * 50)  # constant returns
        result = calc.parametric_var(returns, 1_000_000)
        # With zero vol, VaR should be ~0 (or negative, capped at 0)
        assert result.var_pct >= 0


class TestMonteCarloVaR:
    def test_basic_calculation(self):
        calc = VaRCalculator()
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.02, 250)

        result = calc.monte_carlo_cvar(returns, 1_000_000, n_simulations=5000)
        assert result.method == "monte_carlo"
        assert result.var_pct > 0
        assert result.cvar_pct >= result.var_pct

    def test_reproducible(self):
        calc = VaRCalculator()
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.02, 250)

        r1 = calc.monte_carlo_cvar(returns, 1_000_000, n_simulations=5000)
        r2 = calc.monte_carlo_cvar(returns, 1_000_000, n_simulations=5000)
        # Fixed seed → reproducible
        assert r1.var_pct == r2.var_pct


class TestCalculateAll:
    def test_returns_three_methods(self):
        calc = VaRCalculator()
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.02, 250)

        results = calc.calculate_all(returns, 1_000_000)
        methods = {r.method for r in results}
        assert "historical" in methods
        assert "parametric" in methods
        assert "monte_carlo" in methods

    def test_all_positive_var(self):
        calc = VaRCalculator()
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.02, 250)

        results = calc.calculate_all(returns, 1_000_000)
        for r in results:
            assert r.var_pct >= 0
            assert r.var_amount >= 0
