"""Stress testing engine for portfolio scenarios.

Part of v17.0 Institutional Risk Engine.

Provides:
- 3 preset A-share historical scenarios (2015 crash, 2020 COVID, 2022 real estate)
- Custom shock vector support
- Sector-specific multiplier adjustments
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class StressScenario:
    """Definition of a stress test scenario."""

    name: str
    description: str
    market_shock: float  # Overall market drop (e.g., -0.45 = -45%)
    duration_days: int
    sector_multipliers: dict[str, float] = field(default_factory=dict)


@dataclass
class PositionImpact:
    """Impact of a stress scenario on a single position."""

    symbol: str
    stock_name: str
    current_value: float
    shock_pct: float
    loss_amount: float
    stressed_value: float
    sector: str = ""


@dataclass
class StressResult:
    """Result of running a stress test on a portfolio."""

    scenario: str
    description: str
    portfolio_value: float
    total_loss: float
    total_loss_pct: float
    stressed_value: float
    position_impacts: list[PositionImpact] = field(default_factory=list)
    worst_position: str = ""
    worst_loss_pct: float = 0.0
    warnings: list[str] = field(default_factory=list)


# Preset historical scenarios
PRESET_SCENARIOS: dict[str, StressScenario] = {
    "crash_2015": StressScenario(
        name="2015年股灾",
        description="2015.06-2015.08 A股去杠杆崩盘，上证指数最大跌幅超45%",
        market_shock=-0.45,
        duration_days=60,
        sector_multipliers={
            "券商": 1.5,
            "创业板": 1.3,
            "银行": 0.8,
            "消费": 0.7,
        },
    ),
    "covid_2020": StressScenario(
        name="2020年新冠疫情",
        description="2020.01-2020.03 全球疫情冲击，沪指下跌约15%",
        market_shock=-0.15,
        duration_days=30,
        sector_multipliers={
            "航空": 2.0,
            "旅游": 1.8,
            "酒店": 1.5,
            "医药": -0.5,  # Positive impact (counter-move)
            "在线教育": -0.3,
        },
    ),
    "realestate_2022": StressScenario(
        name="2022年地产危机",
        description="2022 房企暴雷连锁反应，地产链深度调整",
        market_shock=-0.12,
        duration_days=90,
        sector_multipliers={
            "地产": 2.5,
            "银行": 1.3,
            "建材": 1.5,
            "家电": 1.2,
            "新能源": 0.5,
        },
    ),
}


class StressTester:
    """Runs stress tests on portfolio positions."""

    def __init__(self, custom_scenarios: dict[str, StressScenario] | None = None):
        self.scenarios = dict(PRESET_SCENARIOS)
        if custom_scenarios:
            self.scenarios.update(custom_scenarios)

    def list_scenarios(self) -> list[dict]:
        """List available stress test scenarios."""
        return [
            {
                "id": sid,
                "name": s.name,
                "description": s.description,
                "market_shock": s.market_shock,
                "duration_days": s.duration_days,
            }
            for sid, s in self.scenarios.items()
        ]

    def run_scenario(
        self,
        scenario_id: str,
        positions: list[dict],
    ) -> StressResult:
        """Run a preset scenario on a portfolio.

        Args:
            scenario_id: Key in self.scenarios (e.g., "crash_2015").
            positions: List of position dicts, each containing:
                - symbol: Stock code
                - stock_name: Display name
                - current_value: Current market value
                - sector: Sector/industry name (optional)
        """
        scenario = self.scenarios.get(scenario_id)
        if not scenario:
            return StressResult(
                scenario=scenario_id,
                description="未知场景",
                portfolio_value=0,
                total_loss=0,
                total_loss_pct=0,
                stressed_value=0,
                warnings=[f"未找到场景: {scenario_id}"],
            )

        return self._apply_scenario(scenario, positions)

    def run_custom_shock(
        self,
        name: str,
        market_shock: float,
        positions: list[dict],
        sector_multipliers: dict[str, float] | None = None,
    ) -> StressResult:
        """Run a custom shock scenario."""
        scenario = StressScenario(
            name=name,
            description=f"自定义冲击: 市场 {market_shock:+.1%}",
            market_shock=market_shock,
            duration_days=0,
            sector_multipliers=sector_multipliers or {},
        )
        return self._apply_scenario(scenario, positions)

    def _apply_scenario(
        self,
        scenario: StressScenario,
        positions: list[dict],
    ) -> StressResult:
        """Apply a scenario to portfolio positions."""
        warnings: list[str] = []
        impacts: list[PositionImpact] = []
        total_value = 0.0
        total_loss = 0.0

        for pos in positions:
            current_value = pos.get("current_value", 0)
            sector = pos.get("sector", "")
            symbol = pos.get("symbol", "")
            stock_name = pos.get("stock_name", symbol)
            total_value += current_value

            # Determine shock for this position
            multiplier = 1.0
            for sector_key, mult in scenario.sector_multipliers.items():
                if sector_key in sector:
                    multiplier = mult
                    break

            # Negative multiplier means counter-move (position benefits)
            if multiplier < 0:
                shock_pct = scenario.market_shock * multiplier  # Double negative = gain
            else:
                shock_pct = scenario.market_shock * multiplier

            # Cap at -100%
            shock_pct = max(shock_pct, -1.0)
            loss_amount = current_value * shock_pct
            stressed_value = current_value + loss_amount

            impacts.append(
                PositionImpact(
                    symbol=symbol,
                    stock_name=stock_name,
                    current_value=round(current_value, 2),
                    shock_pct=round(shock_pct, 4),
                    loss_amount=round(loss_amount, 2),
                    stressed_value=round(max(stressed_value, 0), 2),
                    sector=sector,
                )
            )
            total_loss += loss_amount

        if not positions:
            warnings.append("持仓为空，无法进行压力测试")

        # Find worst position
        worst = ""
        worst_loss = 0.0
        for imp in impacts:
            if imp.shock_pct < worst_loss:
                worst_loss = imp.shock_pct
                worst = imp.stock_name

        portfolio_loss_pct = total_loss / total_value if total_value > 0 else 0

        return StressResult(
            scenario=scenario.name,
            description=scenario.description,
            portfolio_value=round(total_value, 2),
            total_loss=round(total_loss, 2),
            total_loss_pct=round(portfolio_loss_pct, 4),
            stressed_value=round(max(total_value + total_loss, 0), 2),
            position_impacts=impacts,
            worst_position=worst,
            worst_loss_pct=round(worst_loss, 4),
            warnings=warnings,
        )

    def run_all_presets(self, positions: list[dict]) -> list[StressResult]:
        """Run all preset scenarios on a portfolio."""
        return [self.run_scenario(sid, positions) for sid in PRESET_SCENARIOS]
