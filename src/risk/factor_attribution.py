"""Factor attribution and risk decomposition.

Part of v17.0 Institutional Risk Engine.

Decomposes portfolio risk into:
- Market risk (beta exposure to benchmark)
- Sector/industry risk (sector tilts)
- Idiosyncratic risk (stock-specific)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class FactorExposure:
    """Exposure to a single factor."""

    factor_name: str
    beta: float  # Sensitivity coefficient
    contribution_pct: float  # Contribution to total portfolio variance
    description: str = ""


@dataclass
class AttributionResult:
    """Full factor attribution result for a portfolio."""

    total_variance: float
    total_volatility: float  # annualized
    market_contribution_pct: float
    sector_contribution_pct: float
    idiosyncratic_contribution_pct: float
    market_beta: float
    factors: list[FactorExposure] = field(default_factory=list)
    r_squared: float = 0.0
    warnings: list[str] = field(default_factory=list)


@dataclass
class FactorConfig:
    """Configuration for factor attribution."""

    benchmark_index: str = "000300"
    beta_window: int = 60


class FactorAttribution:
    """Decomposes portfolio risk into factor exposures."""

    def __init__(self, config: FactorConfig | None = None):
        self.config = config or FactorConfig()

    def calculate_beta(
        self,
        asset_returns: np.ndarray,
        benchmark_returns: np.ndarray,
    ) -> tuple[float, float, float]:
        """Calculate beta, alpha, and R-squared via OLS regression.

        Returns:
            (beta, alpha, r_squared)
        """
        asset_returns = np.asarray(asset_returns, dtype=float)
        benchmark_returns = np.asarray(benchmark_returns, dtype=float)

        # Align lengths
        n = min(len(asset_returns), len(benchmark_returns))
        if n < 10:
            return 1.0, 0.0, 0.0

        y = asset_returns[-n:]
        x = benchmark_returns[-n:]

        # Remove non-finite
        mask = np.isfinite(y) & np.isfinite(x)
        y, x = y[mask], x[mask]

        if len(y) < 10:
            return 1.0, 0.0, 0.0

        # OLS: y = alpha + beta * x
        x_mean = np.mean(x)
        y_mean = np.mean(y)
        cov_xy = np.mean((x - x_mean) * (y - y_mean))
        var_x = np.var(x)

        if var_x < 1e-12:
            return 1.0, 0.0, 0.0

        beta = float(cov_xy / var_x)
        alpha = float(y_mean - beta * x_mean)

        # R-squared
        y_pred = alpha + beta * x
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - y_mean) ** 2)
        r_squared = float(1 - ss_res / ss_tot) if ss_tot > 1e-12 else 0.0

        return beta, alpha, max(r_squared, 0.0)

    def decompose_risk(
        self,
        portfolio_returns: np.ndarray,
        benchmark_returns: np.ndarray,
        sector_returns: dict[str, np.ndarray] | None = None,
        weights: dict[str, float] | None = None,
    ) -> AttributionResult:
        """Decompose portfolio risk into market + sector + idiosyncratic.

        Args:
            portfolio_returns: Daily portfolio returns array.
            benchmark_returns: Daily benchmark index returns.
            sector_returns: {sector_name: daily_returns} for sector factors.
            weights: {sector_name: weight} portfolio allocation to each sector.
        """
        portfolio_returns = np.asarray(portfolio_returns, dtype=float)
        benchmark_returns = np.asarray(benchmark_returns, dtype=float)
        portfolio_returns = portfolio_returns[np.isfinite(portfolio_returns)]
        benchmark_returns = benchmark_returns[np.isfinite(benchmark_returns)]

        warnings: list[str] = []
        n = min(len(portfolio_returns), len(benchmark_returns))

        if n < 30:
            warnings.append(f"样本量不足: {n} < 30，归因结果可靠性低")

        # 1. Market beta
        beta, alpha, r_sq = self.calculate_beta(
            portfolio_returns[-n:], benchmark_returns[-n:]
        )

        # Total portfolio variance (annualized)
        total_var = float(np.var(portfolio_returns[-n:], ddof=1))
        total_vol = float(np.sqrt(total_var * 252))
        benchmark_var = float(np.var(benchmark_returns[-n:], ddof=1))

        # Market contribution = beta^2 * var(benchmark) / var(portfolio)
        market_var_contrib = beta**2 * benchmark_var
        market_pct = market_var_contrib / total_var * 100 if total_var > 1e-12 else 0.0

        factors: list[FactorExposure] = [
            FactorExposure(
                factor_name="市场",
                beta=round(beta, 4),
                contribution_pct=round(min(market_pct, 100), 2),
                description=f"沪深300基准, R²={r_sq:.2f}",
            )
        ]

        # 2. Sector contributions
        sector_pct = 0.0
        if sector_returns and weights:
            for sector_name, sec_ret in sector_returns.items():
                sec_ret = np.asarray(sec_ret, dtype=float)
                sec_n = min(n, len(sec_ret))
                if sec_n < 10:
                    continue
                sec_beta, _, _ = self.calculate_beta(
                    portfolio_returns[-sec_n:], sec_ret[-sec_n:]
                )
                sec_var = float(np.var(sec_ret[-sec_n:], ddof=1))
                weight = weights.get(sector_name, 0)
                sec_contrib = (sec_beta * weight) ** 2 * sec_var
                sec_contrib_pct = (
                    sec_contrib / total_var * 100 if total_var > 1e-12 else 0
                )
                sector_pct += sec_contrib_pct

                factors.append(
                    FactorExposure(
                        factor_name=sector_name,
                        beta=round(sec_beta, 4),
                        contribution_pct=round(sec_contrib_pct, 2),
                        description=f"权重 {weight:.1%}",
                    )
                )

        # 3. Idiosyncratic = remainder
        idio_pct = max(100 - market_pct - sector_pct, 0)

        return AttributionResult(
            total_variance=round(total_var, 8),
            total_volatility=round(total_vol, 4),
            market_contribution_pct=round(min(market_pct, 100), 2),
            sector_contribution_pct=round(min(sector_pct, 100 - market_pct), 2),
            idiosyncratic_contribution_pct=round(idio_pct, 2),
            market_beta=round(beta, 4),
            factors=factors,
            r_squared=round(r_sq, 4),
            warnings=warnings,
        )
