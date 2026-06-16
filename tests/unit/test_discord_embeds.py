"""Unit tests for Discord embed card builders."""

from __future__ import annotations

import discord

from src.discord_bot.embeds import split_embed_fields
from src.discord_bot.embeds.capital_flow_card import build_capital_flow_embed
from src.discord_bot.embeds.concept_card import build_concept_embed
from src.discord_bot.embeds.global_market_card import build_global_market_embed
from src.discord_bot.embeds.intel_card import (
    build_intel_clusters_embed,
    build_intel_embed,
    build_intel_overview_embed,
    build_report_embed,
    build_report_list_embed,
)
from src.discord_bot.embeds.market_card import build_market_embed
from src.discord_bot.embeds.portfolio_card import build_portfolio_embed
from src.discord_bot.embeds.quote_card import build_quote_embed
from src.discord_bot.embeds.recommendation_card import build_recommendation_embed
from src.discord_bot.embeds.risk_card import build_risk_embed
from src.discord_bot.embeds.sentiment_card import (
    build_pulse_embed,
    build_sentiment_embed,
)
from src.discord_bot.embeds.stock_card import build_stock_embed

# ── Colour constants ──────────────────────────────────────────────
_GREEN = 0x00C853
_RED = 0xFF1744
_GRAY = 0x9E9E9E


# ── stock_card ────────────────────────────────────────────────────


class TestStockCard:
    def test_buy_signal_green(self):
        embed = build_stock_embed(
            {"symbol": "600519", "signal": "buy", "summary": "看涨"}
        )
        assert embed.color.value == _GREEN  # type: ignore[union-attr]
        assert "600519" in embed.title

    def test_sell_signal_red(self):
        embed = build_stock_embed(
            {"symbol": "000001", "signal": "sell", "summary": "看跌"}
        )
        assert embed.color.value == _RED  # type: ignore[union-attr]

    def test_neutral_signal_gray(self):
        embed = build_stock_embed(
            {"symbol": "300750", "signal": "neutral", "summary": "中性"}
        )
        assert embed.color.value == _GRAY  # type: ignore[union-attr]

    def test_with_quote(self):
        embed = build_stock_embed(
            {"symbol": "600519", "signal": "buy", "summary": "好"},
            quote={"price": 1800.0, "pct_change": 2.5, "volume": 50000},
        )
        field_names = [f.name for f in embed.fields]
        assert "现价" in field_names

    def test_with_risks_and_points(self):
        embed = build_stock_embed(
            {
                "symbol": "600519",
                "signal": "buy",
                "summary": "汇总",
                "risks": ["风险A", "风险B"],
                "points": ["要点1", "要点2"],
            }
        )
        field_names = [f.name for f in embed.fields]
        assert "风险提示" in field_names
        assert "分析要点" in field_names

    def test_empty_analysis(self):
        embed = build_stock_embed({"symbol": "?", "signal": "neutral", "summary": ""})
        assert isinstance(embed, discord.Embed)

    def test_footer_present(self):
        embed = build_stock_embed({"symbol": "600519", "signal": "buy", "summary": "x"})
        assert embed.footer.text is not None
        assert "不构成投资建议" in embed.footer.text


# ── quote_card ────────────────────────────────────────────────────


class TestQuoteCard:
    def test_positive_change_green(self):
        embed = build_quote_embed(
            {"symbol": "600519", "name": "贵州茅台", "price": 1800.0, "pct_change": 1.5}
        )
        assert embed.color.value == _GREEN  # type: ignore[union-attr]

    def test_negative_change_red(self):
        embed = build_quote_embed(
            {
                "symbol": "600519",
                "name": "贵州茅台",
                "price": 1700.0,
                "pct_change": -2.0,
            }
        )
        assert embed.color.value == _RED  # type: ignore[union-attr]

    def test_zero_change_gray(self):
        embed = build_quote_embed(
            {"symbol": "600519", "name": "茅台", "price": 1800.0, "pct_change": 0}
        )
        assert embed.color.value == _GRAY  # type: ignore[union-attr]

    def test_fields_present(self):
        embed = build_quote_embed(
            {
                "symbol": "600519",
                "name": "茅台",
                "price": 1800.0,
                "pct_change": 1.0,
                "open": 1790.0,
                "high": 1810.0,
                "low": 1785.0,
                "prev_close": 1782.0,
                "volume": 120000,
                "amount": 2.1e9,
            }
        )
        field_names = [f.name for f in embed.fields]
        assert "开盘" in field_names
        assert "最高" in field_names
        assert "成交量" in field_names
        assert "成交额" in field_names


# ── market_card ───────────────────────────────────────────────────


class TestMarketCard:
    def test_with_indices(self):
        indices = [
            {"name": "上证指数", "price": 3200.0, "pct_change": 0.5, "change": 16.0},
            {"name": "深证成指", "price": 10500.0, "pct_change": -0.3, "change": -31.5},
        ]
        embed = build_market_embed(indices)
        assert len(embed.fields) == 2
        assert "上证指数" in embed.fields[0].name

    def test_empty_indices(self):
        embed = build_market_embed([])
        assert "暂不可用" in (embed.description or "")


# ── recommendation_card ───────────────────────────────────────────


class TestRecommendationCard:
    def test_with_recommendations(self):
        recs = [{"symbol": "600519", "name": "茅台", "score": 85.0, "confidence": 0.8}]
        embed = build_recommendation_embed(recs)
        assert len(embed.fields) == 1

    def test_empty_recommendations(self):
        embed = build_recommendation_embed([])
        assert "无推荐" in (embed.description or "")


# ── capital_flow_card ─────────────────────────────────────────────


class TestCapitalFlowCard:
    def test_bullish_green(self):
        embed = build_capital_flow_embed(
            {"signal": "bullish", "environment_score": 70, "date": "2026-02-27"}
        )
        assert embed.color.value == _GREEN  # type: ignore[union-attr]

    def test_bearish_red(self):
        embed = build_capital_flow_embed(
            {"signal": "bearish", "environment_score": 30, "date": "2026-02-27"}
        )
        assert embed.color.value == _RED  # type: ignore[union-attr]


# ── intel_card ────────────────────────────────────────────────────


class TestIntelCard:
    def test_with_items(self):
        items = [
            {
                "title": "央行降准",
                "summary": "释放流动性",
                "priority": "high",
                "category": "policy",
                "source_name": "新浪",
            }
        ]
        embed = build_intel_embed(items)
        assert len(embed.fields) == 1
        assert "🏛️" in embed.fields[0].name  # policy badge

    def test_empty_items(self):
        embed = build_intel_embed([])
        assert "暂无情报" in (embed.description or "")

    def test_category_filter_in_title(self):
        embed = build_intel_embed([], category="macro")
        assert "宏观" in embed.title

    def test_query_in_title(self):
        embed = build_intel_embed([], query="半导体")
        assert "半导体" in embed.title

    def test_total_in_description(self):
        items = [{"title": "A", "summary": "B"}]
        embed = build_intel_embed(items, total=50)
        assert "50" in (embed.description or "")

    def test_breaking_priority_badge(self):
        items = [{"title": "紧急", "summary": "x", "priority": "breaking"}]
        embed = build_intel_embed(items)
        assert "🔴" in embed.fields[0].name

    def test_score_string_safe(self):
        """content_score as string should not crash."""
        items = [{"title": "T", "summary": "S", "content_score": "N/A"}]
        embed = build_intel_embed(items)
        assert len(embed.fields) == 1


class TestIntelOverview:
    def test_overview_with_categories(self):
        overview = {
            "total_items": 120,
            "sources_count": 5,
            "categories": {
                "policy": {"total": 30, "unread": 5},
                "macro": {"total": 40, "unread": 0},
            },
        }
        embed = build_intel_overview_embed(overview)
        assert "120" in (embed.description or "")
        assert len(embed.fields) >= 1

    def test_empty_overview(self):
        embed = build_intel_overview_embed({"total_items": 0, "sources_count": 0})
        assert isinstance(embed, discord.Embed)


class TestIntelClusters:
    def test_with_clusters(self):
        clusters = [
            {
                "representative_title": "半导体产业利好",
                "unique_sources": 3,
                "cross_verification_score": 0.85,
                "items": [
                    {"source_name": "新浪", "title": "半导体政策落地"},
                    {"source_name": "东财", "title": "芯片板块异动"},
                ],
            }
        ]
        embed = build_intel_clusters_embed(clusters)
        assert len(embed.fields) == 1
        assert "3 个来源" in embed.fields[0].value

    def test_empty_clusters(self):
        embed = build_intel_clusters_embed([])
        assert "暂无" in (embed.description or "")


class TestReportEmbed:
    def test_bullish_report(self):
        report = {
            "symbol": "600519",
            "stock_name": "贵州茅台",
            "action": "buy",
            "signal": "bullish",
            "confidence": 0.85,
            "summary": "基本面强劲",
            "factors": [
                {"category": "基本面", "impact": "正面", "description": "营收增长20%"}
            ],
            "risk_warnings": ["估值偏高"],
            "outlook": "看好长期",
        }
        embed = build_report_embed(report)
        assert embed.color.value == 0x00C853  # green
        assert "贵州茅台" in embed.title
        assert any("买入" in f.value for f in embed.fields)

    def test_bearish_report(self):
        embed = build_report_embed(
            {
                "symbol": "000001",
                "signal": "bearish",
                "action": "sell",
                "confidence": "high",
            }
        )
        assert embed.color.value == 0xFF1744  # red

    def test_minimal_report(self):
        embed = build_report_embed({"symbol": "300750"})
        assert isinstance(embed, discord.Embed)


class TestReportListEmbed:
    def test_report_list(self):
        reports = [
            {
                "symbol": "600519",
                "stock_name": "茅台",
                "action": "buy",
                "signal": "bullish",
                "confidence": 0.9,
                "summary": "强势",
            },
            {
                "symbol": "000001",
                "stock_name": "平安",
                "action": "hold",
                "signal": "neutral",
                "confidence": 0.5,
                "summary": "震荡",
            },
        ]
        embed = build_report_list_embed(reports, total=10)
        assert len(embed.fields) == 2
        assert "10" in (embed.description or "")

    def test_empty_report_list(self):
        embed = build_report_list_embed([])
        assert "暂无" in (embed.description or "")


# ── risk_card ─────────────────────────────────────────────────────


class TestRiskCard:
    def test_critical_red(self):
        embed = build_risk_embed(
            {"severity": "critical", "title": "跌停预警", "summary": "多只股票跌停"}
        )
        assert embed.color.value == 0xFF1744  # type: ignore[union-attr]

    def test_missing_fields(self):
        embed = build_risk_embed({})
        assert isinstance(embed, discord.Embed)


# ── portfolio_card ────────────────────────────────────────────────


class TestPortfolioCard:
    def test_healthy_portfolio(self):
        embed = build_portfolio_embed(
            {"health_score": 80, "total_value": 500000, "total_pnl": 12000}
        )
        assert embed.color.value == _GREEN  # type: ignore[union-attr]
        field_names = [f.name for f in embed.fields]
        assert "健康评分" in field_names

    def test_unhealthy_portfolio(self):
        embed = build_portfolio_embed({"health_score": 30})
        assert embed.color.value == _RED  # type: ignore[union-attr]

    def test_no_score(self):
        embed = build_portfolio_embed({})
        assert embed.color.value == _GRAY  # type: ignore[union-attr]


# ── Extended limit tests ─────────────────────────────────────────


class TestStockEmbedLongContent:
    def test_risks_show_up_to_8(self):
        analysis = {
            "symbol": "000001",
            "signal": "neutral",
            "risks": [f"risk_{i}" for i in range(12)],
        }
        embed = build_stock_embed(analysis)
        risk_field = next(f for f in embed.fields if f.name == "风险提示")
        assert risk_field.value.count("•") == 8

    def test_points_show_up_to_10(self):
        analysis = {
            "symbol": "000001",
            "signal": "neutral",
            "points": [f"point_{i}" for i in range(15)],
        }
        embed = build_stock_embed(analysis)
        pts_field = next(f for f in embed.fields if f.name == "分析要点")
        assert pts_field.value.count("•") == 10

    def test_long_content_within_limits(self):
        analysis = {
            "symbol": "600519",
            "signal": "buy",
            "summary": "A" * 200,
            "risks": [f"风险{i}: " + "x" * 80 for i in range(12)],
            "points": [f"要点{i}: " + "y" * 80 for i in range(15)],
        }
        quote = {"price": 1800.0, "pct_change": 2.5, "volume": 50000}
        embed = build_stock_embed(analysis, quote)
        assert len(embed.fields) <= 25
        for field in embed.fields:
            assert len(field.value) <= 1024


class TestRecommendationReasoningLength:
    def test_reasoning_200_chars(self):
        reasoning = "A" * 250
        recs = [
            {
                "symbol": "600519",
                "name": "贵州茅台",
                "score": 85,
                "confidence": "high",
                "reasoning": reasoning,
            }
        ]
        embed = build_recommendation_embed(recs)
        field = embed.fields[0]
        assert "A" * 200 in field.value
        assert "A" * 201 not in field.value

    def test_shows_up_to_12(self):
        recs = [
            {"symbol": f"{600000 + i}", "name": f"stock_{i}", "score": 80 - i}
            for i in range(15)
        ]
        embed = build_recommendation_embed(recs)
        assert len(embed.fields) == 12


class TestReportFactorsUpTo8:
    def test_factors_up_to_8(self):
        report = {
            "symbol": "600519",
            "stock_name": "贵州茅台",
            "action": "buy",
            "signal": "bullish",
            "confidence": 0.8,
            "factors": [
                {
                    "category": "fundamental",
                    "impact": "positive",
                    "description": f"因素{i}",
                }
                for i in range(12)
            ],
        }
        embed = build_report_embed(report)
        factor_field = next(f for f in embed.fields if f.name == "分析因素")
        assert factor_field.value.count("•") == 8


# ── sentiment_card ───────────────────────────────────────────────


class TestSentimentCard:
    def test_basic_render(self):
        report = {
            "status": "ok",
            "overall_outlook": "市场情绪偏多，短期看涨",
            "core_trends": ["趋势1", "趋势2"],
            "policy_signals": ["政策1"],
            "risk_alerts": ["风险1"],
            "sector_outlook": ["板块1"],
        }
        embed = build_sentiment_embed(report)
        assert embed.title == "📊 市场舆情分析"
        assert embed.color.value == _GREEN  # 偏多 → green
        assert len(embed.fields) == 4

    def test_bearish_outlook(self):
        report = {
            "status": "ok",
            "overall_outlook": "市场偏空，建议谨慎",
        }
        embed = build_sentiment_embed(report)
        assert embed.color.value == _RED

    def test_error_status(self):
        report = {"status": "error", "message": "暂不可用"}
        embed = build_sentiment_embed(report)
        assert "暂不可用" in embed.description


class TestPulseCard:
    def test_basic_render(self):
        pulse = {
            "status": "ok",
            "hot_events": [{"title": "AI大模型", "heat_score": 95}],
            "holdings_news": {"items": [{"title": "茅台发布年报"}]},
            "global_snapshot": {"indices": [{"name": "S&P 500", "pct_change": 0.5}]},
        }
        embed = build_pulse_embed(pulse)
        assert embed.title == "💓 市场脉搏"
        assert len(embed.fields) >= 2

    def test_error_status(self):
        pulse = {"status": "error", "message": "脉搏不可用"}
        embed = build_pulse_embed(pulse)
        assert "不可用" in embed.description


# ── global_market_card ───────────────────────────────────────────


class TestGlobalMarketCard:
    def test_full_snapshot(self):
        snapshot = {
            "indices": [
                {"name": "S&P 500", "price": 5200, "pct_change": 0.8},
                {"name": "NASDAQ", "price": 16500, "pct_change": 1.2},
            ],
            "commodities": [
                {"name": "黄金", "price": 2300, "pct_change": -0.3, "unit": "USD/oz"},
            ],
            "currencies": [
                {"name": "USD/CNY", "price": 7.23, "pct_change": 0.1},
            ],
        }
        embed = build_global_market_embed(snapshot)
        assert embed.title == "🌍 全球市场概览"
        assert len(embed.fields) == 3

    def test_empty_snapshot(self):
        embed = build_global_market_embed({})
        assert "暂不可用" in embed.description


# ── concept_card ─────────────────────────────────────────────────


class TestConceptCard:
    def test_basic_render(self):
        boards = [
            {
                "name": "人工智能",
                "pct_change": 3.5,
                "zt_count": 5,
                "up_count": 30,
                "down_count": 2,
            },
            {
                "name": "半导体",
                "pct_change": 2.1,
                "zt_count": 3,
                "up_count": 25,
                "down_count": 5,
            },
        ]
        embed = build_concept_embed(boards, limit=10)
        assert embed.title == "🧩 概念板块热度"
        assert "人工智能" in embed.description
        assert "半导体" in embed.description

    def test_dataclass_support(self):
        class FakeBoard:
            def __init__(self, name, pct_change, zt_count=0, up_count=0, down_count=0):
                self.name = name
                self.pct_change = pct_change
                self.zt_count = zt_count
                self.up_count = up_count
                self.down_count = down_count

        boards = [FakeBoard("AI芯片", 4.2, zt_count=3, up_count=20, down_count=1)]
        embed = build_concept_embed(boards)
        assert "AI芯片" in embed.description

    def test_empty(self):
        embed = build_concept_embed([])
        assert "暂不可用" in embed.description


# ── split_embed_fields ───────────────────────────────────────────


class TestSplitEmbedFields:
    def test_no_split_needed(self):
        embed = discord.Embed(title="Test")
        for i in range(5):
            embed.add_field(name=f"f{i}", value=f"v{i}")
        result = split_embed_fields(embed)
        assert len(result) == 1
        assert result[0] is embed

    def test_split_at_20(self):
        embed = discord.Embed(title="Test", color=0xFF0000)
        embed.set_footer(text="footer")
        for i in range(30):
            embed.add_field(name=f"f{i}", value=f"v{i}")
        result = split_embed_fields(embed, max_fields=20)
        assert len(result) == 2
        assert len(result[0].fields) == 20
        assert len(result[1].fields) == 10
        assert result[0].title == "Test"
        assert "续" in result[1].title
        assert result[1].footer.text == "footer"


# ── Cross-cutting field limit tests ──────────────────────────────


class TestEmbedFieldLimits:
    def test_stock_fields_within_25(self):
        analysis = {
            "symbol": "600519",
            "signal": "buy",
            "summary": "test",
            "risks": [f"r{i}" for i in range(20)],
            "points": [f"p{i}" for i in range(20)],
        }
        embed = build_stock_embed(analysis, {"price": 100, "volume": 50000})
        assert len(embed.fields) <= 25

    def test_recommendation_fields_within_25(self):
        recs = [{"symbol": f"{i}", "name": f"s{i}", "score": i} for i in range(20)]
        embed = build_recommendation_embed(recs)
        assert len(embed.fields) <= 25

    def test_stock_field_values_within_1024(self):
        analysis = {
            "symbol": "000001",
            "signal": "neutral",
            "risks": ["x" * 200 for _ in range(10)],
            "points": ["y" * 200 for _ in range(15)],
        }
        embed = build_stock_embed(analysis)
        for field in embed.fields:
            assert len(field.value) <= 1024
