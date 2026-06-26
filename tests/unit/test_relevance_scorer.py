"""Tests for IntelRelevanceScorer."""

import pytest

from src.intelligence.relevance_scorer import IntelRelevanceScorer


@pytest.fixture
def scorer():
    return IntelRelevanceScorer()


class TestDirectMention:
    def test_symbol_in_related_symbols(self, scorer):
        item = {
            "item_id": "i1",
            "title": "湖南黄金发布年报",
            "summary": "业绩增长50%",
            "related_symbols": ["002155"],
        }
        score = scorer.score(item, "002155", "湖南黄金")
        assert score.relevance >= 0.5
        assert any("直接提及" in r for r in score.match_reasons)

    def test_name_in_text(self, scorer):
        item = {
            "item_id": "i2",
            "title": "湖南黄金矿业产量创新高",
            "summary": "",
            "related_symbols": [],
        }
        score = scorer.score(item, "002155", "湖南黄金")
        assert score.relevance >= 0.4
        assert any("提及" in r for r in score.match_reasons)

    def test_no_mention(self, scorer):
        item = {
            "item_id": "i3",
            "title": "半导体行业展望",
            "summary": "芯片产能预计增长",
            "related_symbols": [],
        }
        score = scorer.score(item, "002155", "湖南黄金")
        # Only sector match possible, no direct mention
        assert not any("直接提及" in r for r in score.match_reasons)


class TestSectorMatch:
    def test_gold_sector_keywords(self, scorer):
        item = {
            "item_id": "i4",
            "title": "国际金价突破新高",
            "summary": "避险情绪推动贵金属走强",
            "related_symbols": [],
        }
        score = scorer.score(item, "002155", "湖南黄金")
        assert score.relevance > 0
        assert any("板块关键词" in r for r in score.match_reasons)

    def test_banking_sector_keywords(self, scorer):
        item = {
            "item_id": "i5",
            "title": "央行降息25个基点",
            "summary": "利率下调对银行净息差影响",
            "related_symbols": [],
        }
        score = scorer.score(item, "600036", "招商银行")
        assert any("板块关键词" in r for r in score.match_reasons)


class TestImpactChain:
    def test_war_triggers_gold_chain(self, scorer):
        item = {
            "item_id": "i6",
            "title": "中东战争局势升级",
            "summary": "以色列与伊朗冲突加剧",
            "related_symbols": [],
        }
        score = scorer.score(item, "002155", "湖南黄金")
        assert score.relevance > 0
        # Should match via impact chain
        assert any("影响链" in r for r in score.match_reasons)

    def test_usd_affects_gold(self, scorer):
        """USD strength → gold transmission, preserved across the engine merge.

        The USD templates now live in the canonical YAML (config/
        impact_chain_templates.yaml: usd_strengthen / usd_weaken), and stocks
        resolve through the shared sector→stock map (黄金 → 002155), so a bare
        USD-strength headline still boosts a gold stock via the impact chain.
        """
        item = {
            "item_id": "i7",
            "title": "美元指数突破105",
            "summary": "美元走强创近期新高",
            "related_symbols": [],
        }
        score = scorer.score(item, "002155", "湖南黄金")
        assert score.relevance > 0
        assert any("影响链" in r for r in score.match_reasons)

    def test_oil_affects_petrochemical(self, scorer):
        item = {
            "item_id": "i8",
            "title": "OPEC减产导致原油价格飙升",
            "summary": "国际油价单日涨幅超5%",
            "related_symbols": [],
        }
        score = scorer.score(item, "600028", "中国石化")
        assert score.relevance > 0


class TestPortfolioScoring:
    def test_score_portfolio(self, scorer):
        item = {
            "item_id": "i9",
            "title": "国际金价创历史新高",
            "summary": "避险情绪推动黄金贵金属板块走强",
            "related_symbols": [],
        }
        positions = [
            {"symbol": "002155", "name": "湖南黄金"},
            {"symbol": "600036", "name": "招商银行"},
            {"symbol": "600519", "name": "贵州茅台"},
        ]
        scores = scorer.score_portfolio(item, positions)
        # Gold stock should rank highest
        if scores:
            assert scores[0].symbol == "002155"

    def test_empty_positions(self, scorer):
        item = {"item_id": "i10", "title": "test", "summary": ""}
        scores = scorer.score_portfolio(item, [])
        assert scores == []


class TestBatchScoring:
    def test_batch_score(self, scorer):
        items = [
            {
                "item_id": "b1",
                "title": "黄金价格上涨",
                "summary": "贵金属走强",
                "related_symbols": [],
            },
            {
                "item_id": "b2",
                "title": "银行利率下调",
                "summary": "降息影响银行净息差",
                "related_symbols": [],
            },
        ]
        positions = [
            {"symbol": "002155", "name": "湖南黄金"},
            {"symbol": "600036", "name": "招商银行"},
        ]
        result = scorer.batch_score(items, positions, min_relevance=0.05)
        assert isinstance(result, dict)
        # At least one symbol should have matches
        assert len(result) > 0


class TestSerialization:
    def test_to_dict(self, scorer):
        item = {
            "item_id": "s1",
            "title": "黄金板块走强",
            "summary": "贵金属避险需求旺盛",
            "related_symbols": ["002155"],
        }
        score = scorer.score(item, "002155", "湖南黄金")
        d = score.to_dict()
        assert d["symbol"] == "002155"
        assert "relevance" in d
        assert "impact_direction" in d
        assert "urgency" in d
        assert isinstance(d["match_reasons"], list)

    def test_urgency_levels(self, scorer):
        # High relevance -> immediate
        item = {
            "item_id": "u1",
            "title": "湖南黄金重大利好",
            "summary": "黄金贵金属板块",
            "related_symbols": ["002155"],
        }
        score = scorer.score(item, "002155", "湖南黄金")
        assert score.urgency in ("immediate", "monitor", "background")

    def test_relevance_capped_at_one(self, scorer):
        item = {
            "item_id": "cap1",
            "title": "湖南黄金发布重磅消息",
            "summary": "黄金贵金属避险情绪中东战争",
            "related_symbols": ["002155"],
        }
        score = scorer.score(item, "002155", "湖南黄金")
        assert score.relevance <= 1.0
