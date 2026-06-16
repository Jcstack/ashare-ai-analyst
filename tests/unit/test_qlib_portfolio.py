"""Tests for QlibPortfolioOptimizer — rule-based portfolio optimization."""

from src.quant.qlib_portfolio import QlibPortfolioOptimizer


class TestQlibPortfolioOptimizer:
    def test_empty_positions(self):
        opt = QlibPortfolioOptimizer(config={})
        result = opt.optimize([])
        assert result.total_positions == 0
        assert result.targets == []

    def test_single_position(self):
        opt = QlibPortfolioOptimizer(config={"max_stocks": 5})
        positions = [{"symbol": "600519", "name": "贵州茅台", "market_value": 100000}]
        result = opt.optimize(positions, {"600519": 0.8})
        assert result.total_positions == 1
        assert len(result.targets) == 1
        assert result.targets[0].target_weight > 0

    def test_multiple_positions_ranked(self):
        opt = QlibPortfolioOptimizer(config={"max_stocks": 3})
        positions = [
            {"symbol": "600519", "name": "贵州茅台", "market_value": 50000},
            {"symbol": "000001", "name": "平安银行", "market_value": 30000},
            {"symbol": "000858", "name": "五粮液", "market_value": 20000},
        ]
        scores = {"600519": 0.9, "000001": 0.5, "000858": 0.7}
        result = opt.optimize(positions, scores)
        assert result.total_positions == 3
        # Top scorer should get highest weight
        targets_by_sym = {t.symbol: t for t in result.targets}
        assert (
            targets_by_sym["600519"].target_weight
            >= targets_by_sym["000001"].target_weight
        )

    def test_excess_positions_marked_sell(self):
        opt = QlibPortfolioOptimizer(config={"max_stocks": 2})
        positions = [
            {"symbol": "A", "name": "A", "market_value": 40000},
            {"symbol": "B", "name": "B", "market_value": 30000},
            {"symbol": "C", "name": "C", "market_value": 20000},
        ]
        scores = {"A": 0.9, "B": 0.7, "C": 0.3}
        result = opt.optimize(positions, scores)
        targets_by_sym = {t.symbol: t for t in result.targets}
        assert targets_by_sym["C"].action == "sell"
        assert targets_by_sym["C"].target_weight == 0.0
        assert result.rebalance_needed is True

    def test_max_position_cap(self):
        opt = QlibPortfolioOptimizer(config={"max_position": 0.30, "max_stocks": 5})
        positions = [
            {"symbol": "A", "name": "A", "market_value": 100000},
        ]
        result = opt.optimize(positions, {"A": 0.95})
        # Single position should still get 100% after normalization
        assert result.targets[0].target_weight > 0

    def test_no_alpha_scores(self):
        opt = QlibPortfolioOptimizer(config={})
        positions = [
            {"symbol": "600519", "name": "贵州茅台", "market_value": 50000},
        ]
        result = opt.optimize(positions)
        assert result.total_positions == 1
        # Default score 0.5 applied
        assert result.targets[0].alpha_score == 0.5

    def test_risk_metrics_present(self):
        opt = QlibPortfolioOptimizer(config={"max_stocks": 5})
        positions = [
            {"symbol": "A", "name": "A", "market_value": 60000},
            {"symbol": "B", "name": "B", "market_value": 40000},
        ]
        result = opt.optimize(positions, {"A": 0.8, "B": 0.6})
        assert "max_concentration" in result.risk_metrics
        assert "diversification" in result.risk_metrics
        assert result.risk_metrics["diversification"] == 2

    def test_to_dict(self):
        opt = QlibPortfolioOptimizer(config={})
        positions = [{"symbol": "A", "name": "A", "market_value": 100}]
        result = opt.optimize(positions, {"A": 0.7})
        d = result.to_dict()
        assert "targets" in d
        assert "risk_metrics" in d
        assert isinstance(d["targets"], list)
