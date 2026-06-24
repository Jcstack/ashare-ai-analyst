"""Dry-run harness — simulate trade impact before execution.

Before a trade proposal is pushed to the human executor, this harness
simulates the impact on portfolio metrics: position concentration,
sector exposure, drawdown risk, and overnight risk.

Returns a DryRunReport that the agent can include in its recommendation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DryRunReport:
    """Results of simulating a trade proposal."""

    symbol: str
    action: str
    shares: int
    simulated_cost: float = 0.0

    # Portfolio impact
    new_position_pct: float = 0.0  # % of portfolio after trade
    new_sector_pct: float = 0.0  # % of portfolio in same sector
    new_cash_pct: float = 0.0  # remaining cash %
    position_count: int = 0  # total positions after trade

    # Risk metrics
    max_loss_amount: float = 0.0  # stop-loss triggered loss
    overnight_risk_pct: float = 0.0  # T+1 max adverse move exposure
    concentration_warning: bool = False
    sector_warning: bool = False

    # Checks passed
    checks_passed: list[str] = field(default_factory=list)
    checks_failed: list[str] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return len(self.checks_failed) == 0

    def to_summary(self) -> str:
        """Chinese summary for LLM consumption."""
        status = "通过" if self.all_passed else "有风险"
        lines = [f"模拟结果: {status}"]
        lines.append(
            f"仓位占比: {self.new_position_pct:.1%} | "
            f"板块占比: {self.new_sector_pct:.1%} | "
            f"剩余现金: {self.new_cash_pct:.1%}"
        )
        if self.max_loss_amount > 0:
            lines.append(f"最大亏损(止损触发): {self.max_loss_amount:.0f}元")
        lines.append(f"隔夜风险: {self.overnight_risk_pct:.1%}")

        if self.checks_failed:
            lines.append(f"未通过: {', '.join(self.checks_failed)}")
        return "\n".join(lines)


class DryRunHarness:
    """Pre-execution simulation for trade proposals.

    Validates a proposal against portfolio constraints before
    the human executor sees it. Does NOT block — just annotates.
    """

    def __init__(
        self,
        max_position_pct: float = 0.30,
        max_sector_pct: float = 0.40,
        min_cash_pct: float = 0.10,
        overnight_risk_budget: float = 0.05,
    ) -> None:
        self._max_position_pct = max_position_pct
        self._max_sector_pct = max_sector_pct
        self._min_cash_pct = min_cash_pct
        self._overnight_risk_budget = overnight_risk_budget

    def simulate(
        self,
        proposal: dict[str, Any],
        portfolio: list[dict[str, Any]],
        available_cash: float,
        total_equity: float | None = None,
    ) -> DryRunReport:
        """Simulate the impact of a trade proposal on the portfolio.

        Args:
            proposal: TradeProposal dict (symbol, action, shares, entry_price, stop_loss).
            portfolio: List of position dicts (symbol, shares, costPrice, currentPrice, sector).
            available_cash: Cash available for trading.
            total_equity: Total portfolio value (computed if None).

        Returns:
            DryRunReport with impact analysis and check results.
        """
        symbol = proposal.get("symbol", "")
        action = proposal.get("action", "")
        shares = int(proposal.get("shares", 0))
        price = float(
            proposal.get("entry_price", 0) or proposal.get("price_target", 0) or 0
        )
        stop_loss = proposal.get("stop_loss")
        sector = proposal.get("sector", "")

        # Compute total equity if not provided
        if total_equity is None:
            total_equity = available_cash + sum(
                float(p.get("currentPrice", p.get("costPrice", 0)))
                * int(p.get("shares", 0))
                for p in portfolio
            )
        if total_equity <= 0:
            total_equity = available_cash or 1.0

        trade_cost = shares * price
        report = DryRunReport(
            symbol=symbol,
            action=action,
            shares=shares,
            simulated_cost=trade_cost,
        )

        if action in ("buy", "add"):
            # Position impact
            existing_value = 0.0
            for p in portfolio:
                if p.get("symbol") == symbol:
                    existing_value += float(
                        p.get("currentPrice", p.get("costPrice", 0))
                    ) * int(p.get("shares", 0))

            new_position_value = existing_value + trade_cost
            report.new_position_pct = new_position_value / total_equity
            report.new_cash_pct = (available_cash - trade_cost) / total_equity
            report.position_count = len({p.get("symbol") for p in portfolio} | {symbol})

            # Sector concentration
            sector_value = trade_cost
            for p in portfolio:
                if p.get("sector") == sector and sector:
                    sector_value += float(
                        p.get("currentPrice", p.get("costPrice", 0))
                    ) * int(p.get("shares", 0))
            report.new_sector_pct = sector_value / total_equity if sector else 0.0

            # Max loss calculation
            if stop_loss and price > 0:
                loss_per_share = price - float(stop_loss)
                report.max_loss_amount = abs(loss_per_share * shares)

            # Overnight risk (T+1: can't sell today)
            # Assume max adverse overnight move = 5% for main board
            report.overnight_risk_pct = (trade_cost * 0.05) / total_equity

            # Run checks
            if report.new_position_pct <= self._max_position_pct:
                report.checks_passed.append(
                    f"仓位{report.new_position_pct:.0%} ≤ {self._max_position_pct:.0%}"
                )
            else:
                report.checks_failed.append(
                    f"仓位过重: {report.new_position_pct:.0%} > {self._max_position_pct:.0%}"
                )
                report.concentration_warning = True

            if report.new_sector_pct <= self._max_sector_pct or not sector:
                report.checks_passed.append(
                    f"板块{report.new_sector_pct:.0%} ≤ {self._max_sector_pct:.0%}"
                )
            else:
                report.checks_failed.append(
                    f"板块集中: {report.new_sector_pct:.0%} > {self._max_sector_pct:.0%}"
                )
                report.sector_warning = True

            if report.new_cash_pct >= self._min_cash_pct:
                report.checks_passed.append(
                    f"现金{report.new_cash_pct:.0%} ≥ {self._min_cash_pct:.0%}"
                )
            else:
                report.checks_failed.append(
                    f"现金不足: {report.new_cash_pct:.0%} < {self._min_cash_pct:.0%}"
                )

            if report.overnight_risk_pct <= self._overnight_risk_budget:
                report.checks_passed.append(
                    f"隔夜风险{report.overnight_risk_pct:.1%} ≤ {self._overnight_risk_budget:.0%}"
                )
            else:
                report.checks_failed.append(
                    f"隔夜风险过大: {report.overnight_risk_pct:.1%} > {self._overnight_risk_budget:.0%}"
                )

        elif action in ("sell", "reduce"):
            # Selling reduces risk — always passes
            report.new_cash_pct = (available_cash + trade_cost) / total_equity
            report.checks_passed.append("卖出/减仓降低风险")

        logger.debug(
            "Dry-run %s %s: %s (%d checks passed, %d failed)",
            action,
            symbol,
            "PASS" if report.all_passed else "WARN",
            len(report.checks_passed),
            len(report.checks_failed),
        )
        return report
