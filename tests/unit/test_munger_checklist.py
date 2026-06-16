"""Tests for MungerChecklist."""

import pytest

from src.intelligence.munger_checklist import MungerChecklist


@pytest.fixture
def checklist():
    return MungerChecklist()


class TestSafetyMargin:
    def test_good_margin(self, checklist):
        check = checklist.check_safety_margin(current_price=18.0, fair_value=22.0)
        assert check.passed
        assert check.severity == "pass"

    def test_insufficient_margin(self, checklist):
        check = checklist.check_safety_margin(current_price=20.0, fair_value=21.0)
        assert not check.passed
        assert check.severity == "warn"

    def test_overvalued(self, checklist):
        check = checklist.check_safety_margin(current_price=25.0, fair_value=20.0)
        assert not check.passed
        assert check.severity == "block"

    def test_no_data_skips(self, checklist):
        check = checklist.check_safety_margin()
        assert check.passed
        assert check.severity == "info"


class TestCircleOfCompetence:
    def test_known_sector(self, checklist):
        check = checklist.check_circle_of_competence("黄金", ["黄金", "银行"])
        assert check.passed

    def test_unknown_sector(self, checklist):
        check = checklist.check_circle_of_competence("半导体", ["黄金", "银行"])
        assert not check.passed
        assert check.severity == "warn"

    def test_no_history(self, checklist):
        check = checklist.check_circle_of_competence("黄金", None)
        assert check.passed


class TestInversion:
    def test_acceptable_loss(self, checklist):
        check = checklist.check_inversion(worst_case_loss_pct=3.0)
        assert check.passed

    def test_excessive_loss(self, checklist):
        check = checklist.check_inversion(worst_case_loss_pct=8.0)
        assert not check.passed
        assert "止损" in check.finding


class TestIncentiveBias:
    def test_all_bullish_consensus(self, checklist):
        check = checklist.check_incentive_bias(bullish_signals=5, bearish_signals=0)
        assert not check.passed
        assert "共识陷阱" in check.finding

    def test_all_bearish(self, checklist):
        check = checklist.check_incentive_bias(bullish_signals=0, bearish_signals=5)
        assert not check.passed
        assert "恐慌" in check.finding

    def test_balanced_signals(self, checklist):
        check = checklist.check_incentive_bias(bullish_signals=3, bearish_signals=2)
        assert check.passed


class TestAnchoring:
    def test_normal_move(self, checklist):
        check = checklist.check_anchoring(recent_gain_pct=5.0)
        assert check.passed

    def test_large_recent_gain(self, checklist):
        check = checklist.check_anchoring(recent_gain_pct=20.0)
        assert not check.passed
        assert "衰竭" in check.finding

    def test_large_recent_drop(self, checklist):
        check = checklist.check_anchoring(recent_gain_pct=-18.0)
        assert not check.passed


class TestAvailabilityBias:
    def test_normal_coverage(self, checklist):
        check = checklist.check_availability_bias(news_count_24h=3)
        assert check.passed

    def test_excessive_coverage(self, checklist):
        check = checklist.check_availability_bias(news_count_24h=25)
        assert not check.passed
        assert "泡沫" in check.finding


class TestFullChecklist:
    def test_all_pass(self, checklist):
        result = checklist.run_checklist(
            "002155",
            "湖南黄金",
            current_price=18.0,
            fair_value=22.0,
            sector="黄金",
            traded_sectors=["黄金"],
            worst_case_loss_pct=3.0,
            bullish_signals=3,
            bearish_signals=2,
            recent_gain_pct=5.0,
            news_count_24h=3,
        )
        assert result.overall_passed
        assert result.block_count == 0
        assert result.warn_count == 0

    def test_mixed_warnings(self, checklist):
        result = checklist.run_checklist(
            "002155",
            "湖南黄金",
            current_price=18.0,
            fair_value=22.0,
            worst_case_loss_pct=8.0,  # triggers warn
            news_count_24h=25,  # triggers warn
        )
        assert result.overall_passed  # warns don't block
        assert result.warn_count >= 2

    def test_blocked_by_overvaluation(self, checklist):
        result = checklist.run_checklist(
            "002155",
            "湖南黄金",
            current_price=25.0,
            fair_value=20.0,  # overvalued -> block
        )
        assert not result.overall_passed
        assert result.block_count >= 1

    def test_serialization(self, checklist):
        result = checklist.run_checklist("002155", "湖南黄金")
        d = result.to_dict()
        assert d["symbol"] == "002155"
        assert "checks" in d
        assert len(d["checks"]) == 6

    def test_no_data_all_pass(self, checklist):
        """With no data, all checks should pass with 'info' severity."""
        result = checklist.run_checklist("002155", "湖南黄金")
        assert result.overall_passed
