"""Value-at-Risk (VaR) and Conditional VaR (CVaR) calculator.

Part of v17.0 Institutional Risk Engine.

Methods:
- Historical VaR: Non-parametric, uses actual return distribution.
- Parametric VaR: Assumes normal distribution, fast computation.
- Monte Carlo CVaR: Simulated tail-risk estimate (Expected Shortfall).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class VaRResult:
    """Result of a VaR calculation."""

    method: str  # "historical", "parametric", "monte_carlo"
    confidence_level: float
    holding_period: int
    var_pct: float  # VaR as percentage loss (positive = loss)
    var_amount: float  # VaR in currency units (positive = loss)
    portfolio_value: float
    cvar_pct: float | None = None  # CVaR (Expected Shortfall)
    cvar_amount: float | None = None
    sample_size: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class VaRConfig:
    """Configuration for VaR calculation."""

    historical_window: int = 250
    confidence_levels: list[float] = field(default_factory=lambda: [0.95, 0.99])
    monte_carlo_simulations: int = 10000
    holding_period: int = 1


def _norm_pdf(x: float) -> float:
    """Standard normal PDF: φ(x) = exp(-x²/2) / √(2π)."""
    return float(np.exp(-0.5 * x * x) / np.sqrt(2.0 * np.pi))


def _norm_ppf(p: float) -> float:
    """Inverse standard normal CDF (rational approximation).

    Accurate to ~1e-8 for 0.0001 < p < 0.9999.
    Uses the Beasley-Springer-Moro algorithm.
    """
    if p <= 0 or p >= 1:
        raise ValueError(f"p must be in (0, 1), got {p}")

    # Rational approximation for the central region
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]

    p_low = 0.02425
    p_high = 1.0 - p_low

    if p < p_low:
        q = np.sqrt(-2.0 * np.log(p))
        return float(
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        )
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        return float(
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
            * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
        )
    else:
        q = np.sqrt(-2.0 * np.log(1.0 - p))
        return float(
            -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        )


class VaRCalculator:
    """Calculates portfolio VaR using multiple methods."""

    def __init__(self, config: VaRConfig | None = None):
        self.config = config or VaRConfig()

    def historical_var(
        self,
        returns: np.ndarray,
        portfolio_value: float,
        confidence_level: float = 0.95,
        holding_period: int = 1,
    ) -> VaRResult:
        """Historical simulation VaR.

        Uses the empirical distribution of past returns to estimate VaR.
        No distributional assumptions required.
        """
        returns = np.asarray(returns, dtype=float)
        returns = returns[np.isfinite(returns)]

        warnings: list[str] = []
        if len(returns) < 30:
            warnings.append(f"样本量不足: {len(returns)} < 30，结果可靠性低")
        if len(returns) < self.config.historical_window:
            warnings.append(
                f"样本量 {len(returns)} < 目标窗口 {self.config.historical_window}"
            )

        # Scale returns by holding period (sqrt-T rule)
        if holding_period > 1:
            scaled_returns = returns * np.sqrt(holding_period)
        else:
            scaled_returns = returns

        # VaR = quantile of the loss distribution
        alpha = 1 - confidence_level
        var_pct = -float(np.percentile(scaled_returns, alpha * 100))

        # CVaR = mean of losses beyond VaR
        tail_returns = scaled_returns[scaled_returns <= -var_pct]
        if len(tail_returns) > 0:
            cvar_pct = -float(np.mean(tail_returns))
        else:
            cvar_pct = var_pct  # fallback

        return VaRResult(
            method="historical",
            confidence_level=confidence_level,
            holding_period=holding_period,
            var_pct=round(var_pct, 6),
            var_amount=round(var_pct * portfolio_value, 2),
            portfolio_value=portfolio_value,
            cvar_pct=round(cvar_pct, 6),
            cvar_amount=round(cvar_pct * portfolio_value, 2),
            sample_size=len(returns),
            warnings=warnings,
        )

    def parametric_var(
        self,
        returns: np.ndarray,
        portfolio_value: float,
        confidence_level: float = 0.95,
        holding_period: int = 1,
    ) -> VaRResult:
        """Parametric (variance-covariance) VaR.

        Assumes returns are normally distributed.
        VaR = -μ + z_α * σ, scaled by sqrt(T).
        Uses the Beasley-Springer-Moro rational approximation for
        the inverse normal CDF (no scipy required).
        """
        returns = np.asarray(returns, dtype=float)
        returns = returns[np.isfinite(returns)]

        warnings: list[str] = []
        if len(returns) < 30:
            warnings.append(f"样本量不足: {len(returns)} < 30")

        mu = float(np.mean(returns))
        sigma = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0

        # z-score for the confidence level (no scipy)
        z = _norm_ppf(confidence_level)

        # VaR (positive = loss)
        var_pct = (-mu + z * sigma) * np.sqrt(holding_period)

        # CVaR for normal distribution: E[X | X > VaR] = μ + σ * φ(z) / (1-α)
        alpha = 1 - confidence_level
        phi_z = _norm_pdf(z)
        cvar_pct = (-mu + sigma * phi_z / alpha) * np.sqrt(holding_period)

        return VaRResult(
            method="parametric",
            confidence_level=confidence_level,
            holding_period=holding_period,
            var_pct=round(max(var_pct, 0), 6),
            var_amount=round(max(var_pct, 0) * portfolio_value, 2),
            portfolio_value=portfolio_value,
            cvar_pct=round(max(cvar_pct, 0), 6),
            cvar_amount=round(max(cvar_pct, 0) * portfolio_value, 2),
            sample_size=len(returns),
            warnings=warnings,
        )

    def monte_carlo_cvar(
        self,
        returns: np.ndarray,
        portfolio_value: float,
        confidence_level: float = 0.95,
        holding_period: int = 1,
        n_simulations: int | None = None,
    ) -> VaRResult:
        """Monte Carlo CVaR (Expected Shortfall).

        Simulates future returns from fitted distribution, estimates tail risk.
        """
        returns = np.asarray(returns, dtype=float)
        returns = returns[np.isfinite(returns)]
        n_sims = n_simulations or self.config.monte_carlo_simulations

        warnings: list[str] = []
        if len(returns) < 30:
            warnings.append(f"样本量不足: {len(returns)} < 30")

        mu = float(np.mean(returns))
        sigma = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0

        # Simulate returns
        rng = np.random.default_rng(42)
        simulated = rng.normal(
            mu * holding_period,
            sigma * np.sqrt(holding_period),
            size=n_sims,
        )

        # VaR from simulated distribution
        alpha = 1 - confidence_level
        var_pct = -float(np.percentile(simulated, alpha * 100))

        # CVaR = mean of simulated losses beyond VaR
        tail = simulated[simulated <= -var_pct]
        if len(tail) > 0:
            cvar_pct = -float(np.mean(tail))
        else:
            cvar_pct = var_pct

        return VaRResult(
            method="monte_carlo",
            confidence_level=confidence_level,
            holding_period=holding_period,
            var_pct=round(max(var_pct, 0), 6),
            var_amount=round(max(var_pct, 0) * portfolio_value, 2),
            portfolio_value=portfolio_value,
            cvar_pct=round(max(cvar_pct, 0), 6),
            cvar_amount=round(max(cvar_pct, 0) * portfolio_value, 2),
            sample_size=len(returns),
            warnings=warnings,
        )

    def calculate_all(
        self,
        returns: np.ndarray,
        portfolio_value: float,
        confidence_level: float = 0.95,
        holding_period: int = 1,
    ) -> list[VaRResult]:
        """Run all three VaR methods and return results."""
        results = []

        results.append(
            self.historical_var(
                returns, portfolio_value, confidence_level, holding_period
            )
        )
        results.append(
            self.parametric_var(
                returns, portfolio_value, confidence_level, holding_period
            )
        )
        results.append(
            self.monte_carlo_cvar(
                returns, portfolio_value, confidence_level, holding_period
            )
        )

        return results
