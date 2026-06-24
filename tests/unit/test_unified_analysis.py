"""Tests for v7.0 unified analysis — framework constants, helpers, and parser.

Covers:
  - analysis_frameworks.py: constants, compute_quant_signals, clamp_confidence,
    get_confidence_label, format_* helpers
  - realtime_analyzer.py: analyze_stock_unified(), _parse_unified_result()
  - V01-V07 validation rules, FR-PR006/PR007/PR008/PR010

Mock strategy: Mock LLMRouter only.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm.base import LLMProviderError, LLMResponse, ProviderName
from src.llm.router import RoutingStrategy


# ---------------------------------------------------------------------------
# Sample LLM response for unified analysis
# ---------------------------------------------------------------------------

SAMPLE_UNIFIED_RESULT = json.dumps(
    {
        "action": "hold",
        "confidence": {
            "score": 0.65,
            "label": "较高",
            "basis": ["MA多头排列", "资金净流入"],
        },
        "risk_level": "medium",
        "summary": "技术面偏强，RSI=62 尚未超买，建议持有观察",
        "dimensions": [
            {
                "key": "fundamentals",
                "label": "基本面",
                "signal": "neutral",
                "score": 0.5,
                "reasoning": "无最新财报",
            },
            {
                "key": "valuation",
                "label": "估值",
                "signal": "neutral",
                "score": 0.45,
                "reasoning": "PE中位水平",
            },
            {
                "key": "technical",
                "label": "技术面",
                "signal": "bullish",
                "score": 0.72,
                "reasoning": "MA5>MA20多头排列",
            },
            {
                "key": "capital_flow",
                "label": "资金面",
                "signal": "bullish",
                "score": 0.6,
                "reasoning": "主力净流入1.2亿",
            },
            {
                "key": "macro",
                "label": "宏观环境",
                "signal": "neutral",
                "score": 0.5,
                "reasoning": "无重大政策",
            },
            {
                "key": "risk",
                "label": "风险",
                "signal": "neutral",
                "score": 0.4,
                "reasoning": "流动性正常",
            },
            {
                "key": "confidence_basis",
                "label": "置信度",
                "signal": "neutral",
                "score": 0.65,
                "reasoning": "技术面和资金面一致看多",
            },
        ],
        "risk_warnings": [
            {
                "type": "technical",
                "description": "近期涨幅较大",
                "data_reference": "RSI=62",
            }
        ],
        "target_price": {"low": 10.5, "high": 12.0},
        "stop_loss": 9.0,
        "contrarian_check": "如果大盘出现系统性下跌，技术面强势可能被打破",
        "data_references": [
            {"field": "RSI", "value": "62", "source": "ta library"},
            {"field": "MA5", "value": "10.8", "source": "ta library"},
            {"field": "主力净流入", "value": "1.2亿", "source": "fund flow API"},
        ],
    }
)

SAMPLE_AGENT_CONFIG: dict = {
    "ai_analysis": {
        "quick_cache_ttl_seconds": 300,
        "deep_cache_ttl_seconds": 1800,
        "max_tokens_quick": 512,
        "max_tokens_deep": 4096,
        "temperature": 0.3,
    },
}


def _make_llm_response(
    text: str, model: str = "claude-sonnet-4-5-20250929"
) -> LLMResponse:
    """Create a mock LLMResponse wrapping JSON in markdown code block."""
    return LLMResponse(
        text=f"```json\n{text}\n```",
        provider=ProviderName.ANTHROPIC,
        model=model,
        input_tokens=400,
        output_tokens=800,
        latency_ms=2000.0,
        cost_usd=0.02,
    )


@pytest.fixture
def mock_router():
    router = MagicMock()
    router.complete.return_value = _make_llm_response(SAMPLE_UNIFIED_RESULT)
    return router


@pytest.fixture
def analyzer(mock_router):
    with patch("src.prediction.realtime_analyzer.load_config") as mock_cfg:
        mock_cfg.return_value = SAMPLE_AGENT_CONFIG
        from src.prediction.realtime_analyzer import RealtimeAnalyzer

        yield RealtimeAnalyzer(router=mock_router, config_name="agent")


# ═══════════════════════════════════════════════════════════════════════════
# Framework Constants Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestFrameworkConstants:
    def test_seven_dimension_framework_exists(self):
        from src.prediction.analysis_frameworks import SEVEN_DIMENSION_FRAMEWORK

        assert "D1 Fundamentals" in SEVEN_DIMENSION_FRAMEWORK
        assert "D7 Confidence Assessment" in SEVEN_DIMENSION_FRAMEWORK

    def test_role_definitions_keys(self):
        from src.prediction.analysis_frameworks import ROLE_DEFINITIONS

        expected_keys = {
            "unified",
            "quick_insight",
            "move_analyst",
            "sentiment_analyst",
            "portfolio_doctor",
        }
        assert set(ROLE_DEFINITIONS.keys()) == expected_keys

    def test_standard_disclaimer_not_empty(self):
        from src.prediction.analysis_frameworks import STANDARD_DISCLAIMER

        assert len(STANDARD_DISCLAIMER) > 20
        assert "投资建议" in STANDARD_DISCLAIMER

    def test_valid_actions_set(self):
        from src.prediction.analysis_frameworks import VALID_ACTIONS

        assert VALID_ACTIONS == {"buy", "add", "hold", "reduce", "sell", "watch"}

    def test_action_labels_cover_all_actions(self):
        from src.prediction.analysis_frameworks import ACTION_LABELS, VALID_ACTIONS

        for action in VALID_ACTIONS:
            assert action in ACTION_LABELS


# ═══════════════════════════════════════════════════════════════════════════
# compute_quant_signals Tests  (FR-PR008)
# ═══════════════════════════════════════════════════════════════════════════


class TestComputeQuantSignals:
    def test_with_full_data(self):
        from src.prediction.analysis_frameworks import compute_quant_signals

        result = compute_quant_signals(
            indicators={"rsi": 65.0, "macd": {"histogram": 0.5}},
            strategy_signals={
                "signals": {"trend": {"direction": "buy", "strength": 0.7}},
                "consensus": {"agreement": "strong_bullish"},
            },
            bayesian={"composite": {"confidence": 0.72}},
        )

        assert "technical_score" in result
        assert "momentum_score" in result
        assert "bayesian_probability" in result
        assert "strategy_consensus" in result
        assert result["bayesian_probability"] == 0.72
        assert result["strategy_consensus"] == "强烈看多共识"

    def test_with_missing_data(self):
        from src.prediction.analysis_frameworks import compute_quant_signals

        result = compute_quant_signals(None, None, None)

        assert result["technical_score"] == 50.0
        assert result["momentum_score"] == 50.0
        assert result["bayesian_probability"] == 0.5
        assert result["strategy_consensus"] == "无数据"

    def test_rsi_scoring(self):
        from src.prediction.analysis_frameworks import compute_quant_signals

        # RSI 70 → should score high
        result_high = compute_quant_signals({"rsi": 70}, None, None)
        # RSI 30 → should score low
        result_low = compute_quant_signals({"rsi": 30}, None, None)

        assert result_high["technical_score"] > result_low["technical_score"]


# ═══════════════════════════════════════════════════════════════════════════
# clamp_confidence Tests  (FR-PR006)
# ═══════════════════════════════════════════════════════════════════════════


class TestClampConfidence:
    def test_high_quality_no_clamp(self):
        from src.prediction.analysis_frameworks import clamp_confidence

        assert clamp_confidence(0.9, 90) == 0.9

    def test_medium_quality_caps_at_07(self):
        from src.prediction.analysis_frameworks import clamp_confidence

        assert clamp_confidence(0.9, 65) == 0.7

    def test_low_quality_caps_at_05(self):
        from src.prediction.analysis_frameworks import clamp_confidence

        assert clamp_confidence(0.9, 45) == 0.5

    def test_very_low_quality_caps_at_03(self):
        from src.prediction.analysis_frameworks import clamp_confidence

        assert clamp_confidence(0.9, 30) == 0.3

    def test_already_below_cap(self):
        from src.prediction.analysis_frameworks import clamp_confidence

        # Score already below cap → should not change
        assert clamp_confidence(0.2, 30) == 0.2


# ═══════════════════════════════════════════════════════════════════════════
# get_confidence_label Tests  (FR-PR006)
# ═══════════════════════════════════════════════════════════════════════════


class TestConfidenceLabels:
    def test_label_mapping(self):
        from src.prediction.analysis_frameworks import get_confidence_label

        assert "极低" in get_confidence_label(0.1)
        assert "低" in get_confidence_label(0.3)
        assert "中" in get_confidence_label(0.5)
        assert "较高" in get_confidence_label(0.7)
        assert "高" in get_confidence_label(0.9)


# ═══════════════════════════════════════════════════════════════════════════
# Unified Analysis Parser Tests (V01-V07)
# ═══════════════════════════════════════════════════════════════════════════


class TestParseUnifiedResult:
    def test_valid_result(self, analyzer):
        result = analyzer._parse_unified_result(
            f"```json\n{SAMPLE_UNIFIED_RESULT}\n```",
            "600519",
        )
        assert result["action"] == "hold"
        assert result["confidence"]["score"] == 0.65
        assert result["risk_level"] == "medium"
        assert len(result["dimensions"]) == 7
        assert result["target_price"]["low"] == 10.5
        assert result["stop_loss"] == 9.0

    def test_v01_confidence_100x_fix(self, analyzer):
        """V01: confidence > 1 should be divided by 100."""
        data = json.dumps({"action": "hold", "confidence": 72, "risk_level": "low"})
        result = analyzer._parse_unified_result(f"```json\n{data}\n```", "000001")
        assert result["confidence"]["score"] == 0.72

    def test_v02_low_confidence_forces_watch(self, analyzer):
        """V02: confidence < 0.3 → action must be watch."""
        data = json.dumps({"action": "buy", "confidence": 0.15, "risk_level": "low"})
        result = analyzer._parse_unified_result(f"```json\n{data}\n```", "000001")
        assert result["action"] == "watch"

    def test_v03_medium_confidence_restricts_actions(self, analyzer):
        """V03: confidence 0.3-0.5 → buy/sell restricted."""
        data = json.dumps({"action": "buy", "confidence": 0.4, "risk_level": "low"})
        result = analyzer._parse_unified_result(f"```json\n{data}\n```", "000001")
        assert result["action"] in ("hold", "watch")

    def test_v04_high_risk_no_buy(self, analyzer):
        """V04 (FR-PR007): risk_level=high → action can't be buy/add."""
        data = json.dumps({"action": "buy", "confidence": 0.8, "risk_level": "high"})
        result = analyzer._parse_unified_result(f"```json\n{data}\n```", "000001")
        assert result["action"] == "watch"

    def test_v04_high_risk_add_blocked(self, analyzer):
        """V04: risk=high + add → watch."""
        data = json.dumps({"action": "add", "confidence": 0.7, "risk_level": "high"})
        result = analyzer._parse_unified_result(f"```json\n{data}\n```", "000001")
        assert result["action"] == "watch"

    def test_v05_invalid_action_defaults_watch(self, analyzer):
        """V05: invalid action string → watch."""
        data = json.dumps({"action": "yolo", "confidence": 0.7, "risk_level": "low"})
        result = analyzer._parse_unified_result(f"```json\n{data}\n```", "000001")
        assert result["action"] == "watch"

    def test_v05_chinese_action_mapping(self, analyzer):
        """V05: Chinese action labels should be mapped correctly."""
        data = json.dumps({"action": "买入", "confidence": 0.8, "risk_level": "low"})
        result = analyzer._parse_unified_result(f"```json\n{data}\n```", "000001")
        assert result["action"] == "buy"

    def test_v06_json_repair(self, analyzer):
        """V06: malformed JSON should be repaired or default."""
        result = analyzer._parse_unified_result("not json at all", "000001")
        # Should return valid result with defaults
        assert result["action"] == "watch"
        assert result["confidence"]["score"] >= 0

    def test_v07_data_references_warning(self, analyzer, caplog):
        """V07: empty data_references should log a warning."""
        import logging

        data = json.dumps({"action": "hold", "confidence": 0.6, "risk_level": "low"})
        with caplog.at_level(logging.WARNING):
            analyzer._parse_unified_result(f"```json\n{data}\n```", "000001")
        assert any("data_references" in r.message for r in caplog.records)

    def test_disclaimer_override(self, analyzer):
        """FR-PR010: disclaimer should always be STANDARD_DISCLAIMER."""
        from src.prediction.analysis_frameworks import STANDARD_DISCLAIMER

        data = json.dumps(
            {
                "action": "hold",
                "confidence": 0.6,
                "risk_level": "low",
                "disclaimer": "custom disclaimer",
            }
        )
        result = analyzer._parse_unified_result(f"```json\n{data}\n```", "000001")
        assert result["disclaimer"] == STANDARD_DISCLAIMER

    def test_data_quality_clamp(self, analyzer):
        """FR-PR006: low data quality should clamp confidence."""
        data = json.dumps({"action": "buy", "confidence": 0.9, "risk_level": "low"})
        result = analyzer._parse_unified_result(
            f"```json\n{data}\n```",
            "000001",
            data_quality_score=30,
        )
        assert result["confidence"]["score"] <= 0.3

    def test_backward_compat_fields(self, analyzer):
        """Backward compat: trend, signal, confidence_number, reasoning, quant_signals."""
        result = analyzer._parse_unified_result(
            f"```json\n{SAMPLE_UNIFIED_RESULT}\n```",
            "600519",
            precomputed_quant={"technical_score": 65.0, "momentum_score": 50.0},
        )
        assert "trend" in result
        assert "signal" in result
        assert "confidence_number" in result
        assert isinstance(result["reasoning"], list)
        assert result["quant_signals"] == {
            "technical_score": 65.0,
            "momentum_score": 50.0,
        }
        assert isinstance(result["ai_reasoning"], list)

    def test_risk_warnings_string_normalization(self, analyzer):
        """String risk warnings should be normalized to dict format."""
        data = json.dumps(
            {
                "action": "hold",
                "confidence": 0.6,
                "risk_level": "medium",
                "risk_warnings": ["风险1", "风险2"],
            }
        )
        result = analyzer._parse_unified_result(f"```json\n{data}\n```", "000001")
        for w in result["risk_warnings"]:
            assert isinstance(w, dict)
            assert "description" in w

    def test_low_data_quality_forces_medium_risk(self, analyzer):
        """Data quality < 40 should force risk_level to at least medium."""
        data = json.dumps({"action": "hold", "confidence": 0.3, "risk_level": "low"})
        result = analyzer._parse_unified_result(
            f"```json\n{data}\n```",
            "000001",
            data_quality_score=35,
        )
        assert result["risk_level"] in ("medium", "high")


# ═══════════════════════════════════════════════════════════════════════════
# analyze_stock_unified Integration Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestAnalyzeStockUnified:
    def test_returns_dict(self, analyzer):
        result = analyzer.analyze_stock_unified(symbol="600519")
        assert isinstance(result, dict)

    def test_status_ok(self, analyzer):
        result = analyzer.analyze_stock_unified(symbol="600519")
        assert result["status"] == "ok"

    def test_contains_action_and_confidence(self, analyzer):
        result = analyzer.analyze_stock_unified(symbol="600519")
        assert result["action"] in {"buy", "add", "hold", "reduce", "sell", "watch"}
        assert isinstance(result["confidence"], dict)
        assert "score" in result["confidence"]
        assert "label" in result["confidence"]

    def test_contains_dimensions(self, analyzer):
        result = analyzer.analyze_stock_unified(symbol="600519")
        assert isinstance(result["dimensions"], list)

    def test_uses_quality_strategy(self, analyzer, mock_router):
        analyzer.analyze_stock_unified(symbol="600519")
        call_kwargs = mock_router.complete.call_args
        assert call_kwargs.kwargs.get("strategy") == RoutingStrategy.QUALITY

    def test_llm_error_returns_error(self, analyzer, mock_router):
        mock_router.complete.side_effect = LLMProviderError(
            "API timeout",
            provider=ProviderName.ANTHROPIC,
        )
        result = analyzer.analyze_stock_unified(symbol="600519")
        assert result["status"] == "error"
        assert result["action"] == "watch"

    def test_cache_hit(self, analyzer, mock_router):
        analyzer.analyze_stock_unified(symbol="600519")
        mock_router.complete.reset_mock()
        result2 = analyzer.analyze_stock_unified(symbol="600519")
        mock_router.complete.assert_not_called()
        assert result2["status"] == "ok"

    def test_disclaimer_always_present(self, analyzer):
        from src.prediction.analysis_frameworks import STANDARD_DISCLAIMER

        result = analyzer.analyze_stock_unified(symbol="600519")
        assert result["disclaimer"] == STANDARD_DISCLAIMER

    def test_model_used_present(self, analyzer):
        result = analyzer.analyze_stock_unified(symbol="600519")
        assert result.get("model_used")

    def test_with_all_data(self, analyzer):
        result = analyzer.analyze_stock_unified(
            symbol="600519",
            quote={"price": 1850.0, "change": 5.0, "volume": 1000000},
            indicators={"rsi": 62, "macd": {"histogram": 0.3}},
            fund_flow=[{"date": "2026-02-14", "main_net": 12000000}],
            strategy_signals={"signals": {}, "consensus": {"agreement": "mixed"}},
            bayesian_analysis={"composite": {"confidence": 0.6}},
            board_type="沪市主板",
            price_limit="±10%",
            data_quality_score=85,
            sector_info={
                "industry": "白酒",
                "concepts": [{"name": "消费升级", "pct_change": 1.5}],
            },
            news_context=[
                {"title": "茅台发布年报", "platform": "eastmoney", "heat_score": 0.8}
            ],
            global_context={"indices": [{"name": "S&P500", "change_pct": 0.5}]},
        )
        assert result["status"] == "ok"
