"""Tests for src/intelligence/reflection_agent.py."""

import pytest

from src.intelligence.reflection_agent import (
    ReflectionAgent,
    ReflectionConfig,
)


@pytest.fixture
def agent() -> ReflectionAgent:
    return ReflectionAgent()


@pytest.fixture
def disabled_agent() -> ReflectionAgent:
    config = ReflectionConfig(enabled=False)
    return ReflectionAgent(config)


def _make_analysis(
    confidence: float = 0.70,
    direction: str = "bullish",
    risk_level: str = "MEDIUM",
    assumptions: list[str] | None = None,
    dimensions: list[dict] | None = None,
) -> dict:
    return {
        "confidence": confidence,
        "direction": direction,
        "risk_level": risk_level,
        "key_assumptions": assumptions or [],
        "dimensions": dimensions or [],
    }


class TestReflectionDisabled:
    def test_returns_original_confidence(self, disabled_agent: ReflectionAgent):
        analysis = _make_analysis(confidence=0.85)
        result = disabled_agent.reflect(analysis)
        assert result.original_confidence == 0.85
        assert result.adjusted_confidence == 0.85
        assert result.confidence_delta == 0.0
        assert result.recommendation == "accept"


class TestAssumptionChecks:
    def test_no_assumptions(self, agent: ReflectionAgent):
        analysis = _make_analysis(assumptions=[])
        result = agent.reflect(analysis)
        assert result.assumptions_checked == 0
        assert result.assumptions_valid == 0

    def test_valid_assumptions(self, agent: ReflectionAgent):
        analysis = _make_analysis(
            assumptions=[
                "短期均线向下趋势明显",
                "资金面净流出持续三日",
                "板块整体走弱拖累个股",
            ]
        )
        result = agent.reflect(analysis)
        assert result.assumptions_checked == 3
        assert result.assumptions_valid == 3

    def test_weak_assumptions_flagged(self, agent: ReflectionAgent):
        analysis = _make_analysis(
            assumptions=[
                "这只股票一定会涨",  # Contains "一定"
                "不可能跌破支撑位",  # Contains "不可能"
                "零风险的投资机会",  # Contains "零风险"
            ]
        )
        result = agent.reflect(analysis)
        assert result.assumptions_checked == 3
        assert result.assumptions_valid == 0
        assert any("假设验证通过率低" in issue for issue in result.issues_found)

    def test_short_assumption_invalid(self, agent: ReflectionAgent):
        analysis = _make_analysis(assumptions=["涨"])
        result = agent.reflect(analysis)
        assert result.assumptions_valid == 0

    def test_max_assumptions_capped(self):
        config = ReflectionConfig(max_assumptions_to_check=2)
        agent = ReflectionAgent(config)
        analysis = _make_analysis(
            assumptions=["假设A有效", "假设B有效", "假设C有效", "假设D有效"]
        )
        result = agent.reflect(analysis)
        assert result.assumptions_checked == 2


class TestSignalConsistency:
    def test_consistent_bullish(self, agent: ReflectionAgent):
        analysis = _make_analysis(
            direction="bullish",
            dimensions=[
                {"signal": "bullish", "confidence": 0.70},
                {"signal": "bullish", "confidence": 0.65},
                {"signal": "neutral", "confidence": 0.50},
            ],
        )
        result = agent.reflect(analysis)
        assert "维度信号存在矛盾" not in result.issues_found

    def test_inconsistent_signals(self, agent: ReflectionAgent):
        analysis = _make_analysis(
            direction="bullish",
            dimensions=[
                {"signal": "bearish", "confidence": 0.70},
                {"signal": "bearish", "confidence": 0.65},
                {"signal": "bullish", "confidence": 0.60},
            ],
        )
        result = agent.reflect(analysis)
        assert "维度信号存在矛盾" in result.issues_found

    def test_mixed_with_high_confidence(self, agent: ReflectionAgent):
        analysis = _make_analysis(
            confidence=0.85,
            direction="bullish",
            dimensions=[
                {"signal": "bullish", "confidence": 0.80},
                {"signal": "bearish", "confidence": 0.60},
            ],
        )
        result = agent.reflect(analysis)
        # Should get a small penalty for mixed signals at high confidence
        assert result.adjusted_confidence < 0.85

    def test_single_dimension_no_penalty(self, agent: ReflectionAgent):
        analysis = _make_analysis(
            direction="bullish",
            dimensions=[{"signal": "bearish", "confidence": 0.70}],
        )
        result = agent.reflect(analysis)
        # Single dimension can't be "inconsistent"
        assert "维度信号存在矛盾" not in result.issues_found


class TestCalibration:
    def test_overconfident_with_high_risk(self, agent: ReflectionAgent):
        analysis = _make_analysis(
            confidence=0.95,
            risk_level="HIGH",
        )
        result = agent.reflect(analysis)
        assert result.adjusted_confidence < 0.95

    def test_very_overconfident(self, agent: ReflectionAgent):
        analysis = _make_analysis(confidence=0.98, risk_level="LOW")
        result = agent.reflect(analysis)
        assert result.adjusted_confidence < 0.98

    def test_moderate_confidence_no_penalty(self, agent: ReflectionAgent):
        analysis = _make_analysis(confidence=0.65, risk_level="LOW")
        result = agent.reflect(analysis)
        assert result.adjusted_confidence == result.original_confidence


class TestHistoricalAccuracy:
    def test_low_historical_accuracy(self, agent: ReflectionAgent):
        analysis = _make_analysis(confidence=0.70)
        history = {"accuracy_t5": 0.35}
        result = agent.reflect(analysis, historical_accuracy=history)
        assert result.adjusted_confidence < 0.70
        assert any("历史准确率偏低" in issue for issue in result.issues_found)

    def test_below_baseline_accuracy(self, agent: ReflectionAgent):
        analysis = _make_analysis(confidence=0.70)
        history = {"accuracy_t5": 0.45}
        result = agent.reflect(analysis, historical_accuracy=history)
        assert any("历史准确率低于基线" in issue for issue in result.issues_found)

    def test_good_historical_accuracy(self, agent: ReflectionAgent):
        analysis = _make_analysis(confidence=0.70)
        history = {"accuracy_t5": 0.65}
        result = agent.reflect(analysis, historical_accuracy=history)
        assert not any("历史准确率" in issue for issue in result.issues_found)

    def test_no_historical_data(self, agent: ReflectionAgent):
        analysis = _make_analysis(confidence=0.70)
        result = agent.reflect(analysis, historical_accuracy=None)
        assert result.consistency_score is None


class TestPenaltyCapping:
    def test_penalty_capped_at_max(self):
        config = ReflectionConfig(max_confidence_reduction=0.10)
        agent = ReflectionAgent(config)
        # Multiple issues that would exceed cap
        analysis = _make_analysis(
            confidence=0.96,
            risk_level="HIGH",
            assumptions=["一定涨", "不可能跌", "零风险"],
            dimensions=[
                {"signal": "bearish", "confidence": 0.80},
                {"signal": "bearish", "confidence": 0.70},
            ],
        )
        history = {"accuracy_t5": 0.30}
        result = agent.reflect(analysis, historical_accuracy=history)
        # Delta should not exceed max_confidence_reduction
        assert abs(result.confidence_delta) <= 0.10 + 0.001

    def test_adjusted_never_below_floor(self, agent: ReflectionAgent):
        analysis = _make_analysis(
            confidence=0.15,
            risk_level="HIGH",
            assumptions=["一定涨", "不可能跌", "零风险"],
        )
        history = {"accuracy_t5": 0.10}
        result = agent.reflect(analysis, historical_accuracy=history)
        assert result.adjusted_confidence >= 0.1


class TestRecommendation:
    def test_accept_no_issues(self, agent: ReflectionAgent):
        analysis = _make_analysis(confidence=0.65, risk_level="LOW")
        result = agent.reflect(analysis)
        assert result.recommendation == "accept"

    def test_reduce_confidence(self, agent: ReflectionAgent):
        analysis = _make_analysis(confidence=0.95, risk_level="MEDIUM")
        result = agent.reflect(analysis)
        assert result.recommendation in ("reduce_confidence", "flag_for_review")

    def test_flag_for_review(self, agent: ReflectionAgent):
        analysis = _make_analysis(
            confidence=0.96,
            risk_level="HIGH",
            assumptions=["一定涨", "不可能跌", "零风险"],
        )
        history = {"accuracy_t5": 0.30}
        result = agent.reflect(analysis, historical_accuracy=history)
        assert result.recommendation == "flag_for_review"
