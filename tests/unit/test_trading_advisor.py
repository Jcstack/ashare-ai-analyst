"""Tests for TradingAdvisor — dual-layer quant + AI recommendations.

Per PRD v3.2 FR-TA001~003, FR-HS003~004.
"""

import json
from dataclasses import dataclass
from unittest.mock import MagicMock

from src.prediction.trading_advisor import TradingAdvisor


@dataclass
class FakeLLMResponse:
    text: str
    model: str = "test-model"


class TestAdviseStock:
    def test_basic_advice(self):
        mock_router = MagicMock()
        mock_router.complete.return_value = FakeLLMResponse(
            text=json.dumps(
                {
                    "action": "buy",
                    "confidence": 0.75,
                    "risk_level": "medium",
                    "quant_signals": {
                        "technical_score": 0.7,
                        "momentum_score": 0.6,
                        "strategy_consensus": "看多",
                        "bayesian_probability": 0.65,
                    },
                    "ai_reasoning": ["均线多头排列", "资金净流入"],
                    "risk_warnings": ["短期涨幅过大"],
                    "target_price": {"low": 10.0, "high": 12.0},
                    "stop_loss": 8.5,
                    "data_references": [
                        {"field": "最新价", "value": "10.50", "source": "实时行情"},
                        {"field": "涨跌幅", "value": "+2.3%", "source": "实时行情"},
                        {"field": "主力净流入", "value": "1.2亿", "source": "资金流向"},
                    ],
                }
            )
        )

        advisor = TradingAdvisor(router=mock_router)
        result = advisor.advise_stock("600519", quote={"price": 10.5})

        assert result["status"] == "success"
        assert result["action"] == "buy"
        assert result["confidence"] == 0.75
        assert result["risk_level"] == "medium"
        assert len(result["ai_reasoning"]) == 2
        assert result["target_price"]["low"] == 10.0
        assert result["stop_loss"] == 8.5
        assert result["disclaimer"]

    def test_low_confidence_forces_watch(self):
        mock_router = MagicMock()
        mock_router.complete.return_value = FakeLLMResponse(
            text=json.dumps(
                {
                    "action": "buy",
                    "confidence": 0.2,
                    "risk_level": "high",
                    "ai_reasoning": ["信号不明确"],
                    "risk_warnings": [],
                }
            )
        )

        advisor = TradingAdvisor(router=mock_router)
        result = advisor.advise_stock("600519")

        assert result["action"] == "watch"
        assert result["confidence"] == 0.2

    def test_medium_confidence_limits_actions(self):
        mock_router = MagicMock()
        mock_router.complete.return_value = FakeLLMResponse(
            text=json.dumps(
                {
                    "action": "sell",
                    "confidence": 0.4,
                    "risk_level": "medium",
                    "ai_reasoning": [],
                    "risk_warnings": [],
                }
            )
        )

        advisor = TradingAdvisor(router=mock_router)
        result = advisor.advise_stock("600519")

        # sell with 0.4 confidence should be demoted to watch
        assert result["action"] == "watch"

    def test_chinese_action_mapping(self):
        mock_router = MagicMock()
        mock_router.complete.return_value = FakeLLMResponse(
            text=json.dumps(
                {
                    "action": "买入",
                    "confidence": 0.8,
                    "risk_level": "low",
                    "ai_reasoning": ["趋势确认"],
                    "risk_warnings": [],
                    "data_references": [
                        {"field": "最新价", "value": "10.50", "source": "实时行情"},
                        {"field": "趋势", "value": "多头排列", "source": "技术指标"},
                    ],
                }
            )
        )

        advisor = TradingAdvisor(router=mock_router)
        result = advisor.advise_stock("600519")

        assert result["action"] == "buy"
        assert result["action_label"] == "买入"

    def test_invalid_json_returns_error(self):
        mock_router = MagicMock()
        mock_router.complete.return_value = FakeLLMResponse(text="not json at all")

        advisor = TradingAdvisor(router=mock_router)
        result = advisor.advise_stock("600519")

        assert result["status"] == "error"
        assert result["action"] == "watch"

    def test_llm_error_returns_error(self):
        mock_router = MagicMock()
        mock_router.complete.side_effect = Exception("API timeout")

        advisor = TradingAdvisor(router=mock_router)
        result = advisor.advise_stock("600519")

        assert result["status"] == "error"
        assert "API timeout" in result.get("message", "")

    def test_cache_hit(self):
        mock_router = MagicMock()
        mock_router.complete.return_value = FakeLLMResponse(
            text=json.dumps(
                {
                    "action": "hold",
                    "confidence": 0.6,
                    "risk_level": "low",
                    "ai_reasoning": ["test"],
                    "risk_warnings": [],
                }
            )
        )

        advisor = TradingAdvisor(router=mock_router)
        result1 = advisor.advise_stock("600519")
        result2 = advisor.advise_stock("600519")

        assert result1["action"] == result2["action"]
        assert mock_router.complete.call_count == 1  # second call from cache


class TestRiskActionEnforcement:
    """V04 (FR-PR007): high risk → buy/add forced to watch."""

    def test_high_risk_buy_forced_to_watch(self):
        mock_router = MagicMock()
        mock_router.complete.return_value = FakeLLMResponse(
            text=json.dumps(
                {
                    "action": "buy",
                    "confidence": 0.8,
                    "risk_level": "high",
                    "ai_reasoning": ["技术面强势"],
                    "risk_warnings": ["估值极端"],
                }
            )
        )

        advisor = TradingAdvisor(router=mock_router)
        result = advisor.advise_stock("600519")

        # V04: high risk forces buy → watch
        assert result["action"] == "watch"

    def test_high_risk_add_forced_to_watch(self):
        mock_router = MagicMock()
        mock_router.complete.return_value = FakeLLMResponse(
            text=json.dumps(
                {
                    "action": "add",
                    "confidence": 0.75,
                    "risk_level": "high",
                    "ai_reasoning": ["加仓信号"],
                    "risk_warnings": ["高风险"],
                }
            )
        )

        advisor = TradingAdvisor(router=mock_router)
        result = advisor.advise_stock("600519")

        assert result["action"] == "watch"

    def test_high_risk_hold_allowed(self):
        mock_router = MagicMock()
        mock_router.complete.return_value = FakeLLMResponse(
            text=json.dumps(
                {
                    "action": "hold",
                    "confidence": 0.7,
                    "risk_level": "high",
                    "ai_reasoning": ["持有等待"],
                    "risk_warnings": ["高风险"],
                }
            )
        )

        advisor = TradingAdvisor(router=mock_router)
        result = advisor.advise_stock("600519")

        # hold is allowed under high risk
        assert result["action"] == "hold"

    def test_medium_risk_buy_allowed(self):
        mock_router = MagicMock()
        mock_router.complete.return_value = FakeLLMResponse(
            text=json.dumps(
                {
                    "action": "buy",
                    "confidence": 0.8,
                    "risk_level": "medium",
                    "ai_reasoning": ["趋势确认"],
                    "risk_warnings": [],
                    "data_references": [
                        {"field": "最新价", "value": "10.50", "source": "实时行情"},
                        {"field": "MA5", "value": "10.30", "source": "技术指标"},
                    ],
                }
            )
        )

        advisor = TradingAdvisor(router=mock_router)
        result = advisor.advise_stock("600519")

        # medium risk allows buy
        assert result["action"] == "buy"


class TestSectorInfo:
    def test_advise_with_sector_info(self):
        """Sector info should be included in the prompt sent to LLM."""
        mock_router = MagicMock()
        mock_router.complete.return_value = FakeLLMResponse(
            text=json.dumps(
                {
                    "action": "buy",
                    "confidence": 0.8,
                    "risk_level": "medium",
                    "ai_reasoning": ["概念共振强"],
                    "risk_warnings": [],
                    "data_references": [
                        {"field": "最新价", "value": "10.50", "source": "实时行情"},
                        {
                            "field": "概念共振",
                            "value": "moderate",
                            "source": "板块数据",
                        },
                    ],
                }
            )
        )

        advisor = TradingAdvisor(router=mock_router)
        result = advisor.advise_stock(
            "001330",
            quote={"price": 10.5},
            sector_info={
                "industry": "文化传媒",
                "concepts": [
                    {"name": "影视院线", "pct_change": 3.21, "stock_rank_pct": 0.12},
                    {"name": "文生视频", "pct_change": 5.12, "stock_rank_pct": 0.08},
                ],
                "resonance": {
                    "level": "moderate",
                    "concepts": ["影视院线", "文生视频", "AIGC"],
                    "top_driver": "文生视频",
                    "rank_in_driver": "领涨",
                },
            },
        )

        assert result["status"] == "success"
        assert result["action"] == "buy"
        # Verify sector info was included in the prompt
        call_args = mock_router.complete.call_args
        user_msg = call_args.kwargs.get(
            "messages", call_args[0][0] if call_args[0] else []
        )
        if hasattr(user_msg, "__iter__"):
            prompt_text = " ".join(
                str(m.content) for m in user_msg if hasattr(m, "content")
            )
        else:
            prompt_text = str(user_msg)
        assert "概念板块" in prompt_text
        assert "影视院线" in prompt_text

    def test_advise_without_sector_info(self):
        """Without sector_info, advice should still work normally."""
        mock_router = MagicMock()
        mock_router.complete.return_value = FakeLLMResponse(
            text=json.dumps(
                {
                    "action": "hold",
                    "confidence": 0.6,
                    "risk_level": "low",
                    "ai_reasoning": ["无概念数据"],
                    "risk_warnings": [],
                }
            )
        )

        advisor = TradingAdvisor(router=mock_router)
        result = advisor.advise_stock("600519", sector_info=None)

        assert result["status"] == "success"
        assert result["action"] == "hold"

    def test_format_sector_info(self):
        """_format_sector_info should produce correct prompt text."""
        from src.prediction.trading_advisor import _format_sector_info

        text = _format_sector_info(
            {
                "industry": "文化传媒",
                "concepts": [
                    {"name": "影视院线", "pct_change": 3.21, "stock_rank_pct": 0.12},
                    {"name": "AIGC", "pct_change": -1.5, "stock_rank_pct": None},
                ],
                "resonance": {
                    "level": "moderate",
                    "concepts": ["影视院线", "文生视频"],
                    "top_driver": "文生视频",
                    "rank_in_driver": "领涨",
                },
            }
        )

        assert "概念板块" in text
        assert "文化传媒" in text
        assert "影视院线" in text
        assert "+3.21%" in text
        assert "前12%" in text
        assert "moderate" in text
        assert "文生视频" in text


class TestHolidayImpact:
    def test_basic_holiday_impact(self):
        mock_router = MagicMock()
        mock_router.complete.return_value = FakeLLMResponse(
            text=json.dumps(
                {
                    "impact_score": 0.7,
                    "impact_direction": "negative",
                    "factors": [
                        {
                            "name": "海外市场下跌",
                            "impact": "negative",
                            "weight": 0.5,
                            "description": "美股大跌3%",
                        }
                    ],
                    "ai_assessment": "假期海外市场下跌，节后可能低开",
                    "suggested_action": "reduce",
                    "confidence": 0.65,
                }
            )
        )

        advisor = TradingAdvisor(router=mock_router)
        result = advisor.assess_holiday_impact("600519")

        assert result["status"] == "success"
        assert result["impact_score"] == 0.7
        assert result["impact_direction"] == "negative"
        assert len(result["factors"]) == 1
        assert result["suggested_action"] == "reduce"


class TestReopenBriefing:
    def test_basic_briefing(self):
        mock_router = MagicMock()
        mock_router.complete.return_value = FakeLLMResponse(
            text=json.dumps(
                {
                    "market_outlook": "bearish",
                    "confidence": 0.6,
                    "summary": "节后市场可能承压",
                    "key_events": ["美联储加息", "中东冲突"],
                    "position_impacts": [
                        {"symbol": "600519", "impact": "neutral", "brief": "消费稳健"}
                    ],
                    "recommendations": ["控制仓位", "关注消费"],
                    "risk_warnings": ["全球流动性收紧"],
                }
            )
        )

        advisor = TradingAdvisor(router=mock_router)
        result = advisor.generate_reopen_briefing()

        assert result["status"] == "success"
        assert result["market_outlook"] == "bearish"
        assert len(result["key_events"]) == 2
        assert len(result["position_impacts"]) == 1
        assert result["disclaimer"]
