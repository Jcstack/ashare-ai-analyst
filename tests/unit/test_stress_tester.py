"""Tests for stress testing engine.

Part of v17.0 Risk Engine.
"""

from __future__ import annotations

from src.risk.stress_tester import PRESET_SCENARIOS, StressScenario, StressTester


def _sample_positions():
    return [
        {
            "symbol": "600519",
            "stock_name": "贵州茅台",
            "current_value": 500_000,
            "sector": "消费",
        },
        {
            "symbol": "601318",
            "stock_name": "中国平安",
            "current_value": 300_000,
            "sector": "银行",
        },
        {
            "symbol": "300750",
            "stock_name": "宁德时代",
            "current_value": 200_000,
            "sector": "新能源",
        },
    ]


class TestPresetScenarios:
    def test_three_presets_exist(self):
        assert len(PRESET_SCENARIOS) == 3
        assert "crash_2015" in PRESET_SCENARIOS
        assert "covid_2020" in PRESET_SCENARIOS
        assert "realestate_2022" in PRESET_SCENARIOS

    def test_2015_crash_shock(self):
        s = PRESET_SCENARIOS["crash_2015"]
        assert s.market_shock == -0.45
        assert s.duration_days == 60

    def test_covid_has_medical_counter_move(self):
        s = PRESET_SCENARIOS["covid_2020"]
        assert s.sector_multipliers.get("医药", 0) < 0  # counter-move


class TestStressTester:
    def test_list_scenarios(self):
        tester = StressTester()
        scenarios = tester.list_scenarios()
        assert len(scenarios) >= 3
        names = {s["id"] for s in scenarios}
        assert "crash_2015" in names

    def test_run_2015_crash(self):
        tester = StressTester()
        positions = _sample_positions()
        result = tester.run_scenario("crash_2015", positions)

        assert result.scenario == "2015年股灾"
        assert result.portfolio_value == 1_000_000
        assert result.total_loss < 0  # It's a loss
        assert result.total_loss_pct < 0
        assert result.stressed_value < result.portfolio_value
        assert len(result.position_impacts) == 3

    def test_sector_multipliers_applied(self):
        tester = StressTester()
        # Bank has 0.8 multiplier in 2015 crash
        positions = [
            {
                "symbol": "601318",
                "stock_name": "平安",
                "current_value": 100_000,
                "sector": "银行",
            },
        ]
        result = tester.run_scenario("crash_2015", positions)
        # Bank shock = -0.45 * 0.8 = -0.36
        impact = result.position_impacts[0]
        assert abs(impact.shock_pct - (-0.36)) < 0.01

    def test_counter_move_sector(self):
        tester = StressTester()
        positions = [
            {
                "symbol": "600276",
                "stock_name": "恒瑞医药",
                "current_value": 100_000,
                "sector": "医药",
            },
        ]
        result = tester.run_scenario("covid_2020", positions)
        # Medical has -0.5 multiplier → shock = -0.15 * (-0.5) = +0.075
        impact = result.position_impacts[0]
        assert impact.shock_pct > 0  # positive (counter-move = gain)

    def test_unknown_scenario(self):
        tester = StressTester()
        result = tester.run_scenario("nonexistent", [])
        assert "未找到场景" in result.warnings[0]

    def test_empty_portfolio(self):
        tester = StressTester()
        result = tester.run_scenario("crash_2015", [])
        assert "持仓为空" in result.warnings[0]
        assert result.total_loss == 0

    def test_custom_shock(self):
        tester = StressTester()
        positions = _sample_positions()
        result = tester.run_custom_shock("自定义测试", -0.20, positions, {"银行": 1.5})
        assert result.scenario == "自定义测试"
        assert result.total_loss_pct < 0

    def test_run_all_presets(self):
        tester = StressTester()
        positions = _sample_positions()
        results = tester.run_all_presets(positions)
        assert len(results) == 3

    def test_worst_position_identified(self):
        tester = StressTester()
        positions = [
            {
                "symbol": "000001",
                "stock_name": "券商A",
                "current_value": 100_000,
                "sector": "券商",
            },
            {
                "symbol": "000002",
                "stock_name": "消费B",
                "current_value": 100_000,
                "sector": "消费",
            },
        ]
        result = tester.run_scenario("crash_2015", positions)
        # 券商 has 1.5 multiplier, should be worst
        assert result.worst_position == "券商A"

    def test_custom_scenarios_extend(self):
        custom = {
            "my_scenario": StressScenario(
                name="自定义", description="测试", market_shock=-0.10, duration_days=5
            )
        }
        tester = StressTester(custom_scenarios=custom)
        assert len(tester.scenarios) == 4  # 3 preset + 1 custom
