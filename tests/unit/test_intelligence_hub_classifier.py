"""Tests for Intelligence Hub classifier rule matching."""

from __future__ import annotations

from src.intelligence_hub.classifier import InfoClassifier
from src.intelligence_hub.models import InfoItem

RULES_CONFIG = {
    "category_rules": [
        {"match_source_type": "policy", "category": "policy"},
        {"match_source_type": "reddit", "category": "social"},
        {
            "match_keywords": ["降准", "降息", "LPR", "货币政策", "CPI", "GDP", "PMI"],
            "category": "macro",
        },
        {"match_keywords": ["板块", "行业", "产业链"], "category": "industry"},
        {"match_keywords": ["公告", "业绩", "增持", "减持"], "category": "company"},
        {"match_keywords": ["美股", "纳斯达克", "港股"], "category": "global"},
        # English keyword rules
        {
            "match_keywords": [
                "interest rate",
                "rate hike",
                "rate cut",
                "inflation",
                "Federal Reserve",
                "Fed",
                "ECB",
                "Bank of Japan",
                "BOJ",
                "monetary policy",
                "fiscal policy",
                "treasury yield",
            ],
            "category": "macro",
        },
        {
            "match_keywords": [
                "S&P 500",
                "Nasdaq",
                "Dow Jones",
                "FTSE",
                "Nikkei",
                "Hang Seng",
                "crude oil",
                "gold price",
                "Wall Street",
                "forex",
            ],
            "category": "global",
        },
        {
            "match_keywords": [
                "semiconductor",
                "EV",
                "electric vehicle",
                "renewable energy",
                "AI chip",
                "supply chain",
                "sector rotation",
            ],
            "category": "industry",
        },
        {
            "match_keywords": [
                "earnings",
                "revenue",
                "buyback",
                "dividend",
                "IPO",
                "merger",
                "acquisition",
                "SEC filing",
            ],
            "category": "company",
        },
    ],
    "priority_rules": [
        {
            "match_keywords": ["紧急", "突发", "重大", "暴跌", "暴涨"],
            "priority": "breaking",
        },
        {"match_keywords": ["降准", "降息", "IPO"], "priority": "high"},
        {"match_source_type": "policy", "priority": "high"},
        # English priority rules
        {
            "match_keywords": [
                "breaking",
                "flash crash",
                "circuit breaker",
                "emergency",
                "plunge",
                "surge",
                "halt",
            ],
            "priority": "breaking",
        },
        {
            "match_keywords": [
                "rate cut",
                "rate hike",
                "FOMC",
                "earnings beat",
                "earnings miss",
            ],
            "priority": "high",
        },
    ],
}


def _make(
    title: str = "Test", category: str = "market", priority: str = "normal"
) -> InfoItem:
    return InfoItem(
        source_id="test",
        source_name="Test",
        title=title,
        category=category,
        priority=priority,
    )


class TestCategoryClassification:
    def test_policy_source_type(self) -> None:
        clf = InfoClassifier(RULES_CONFIG)
        item = _make("Some announcement")
        clf.classify(item, source_type="policy")
        assert item.category == "policy"

    def test_macro_keywords(self) -> None:
        clf = InfoClassifier(RULES_CONFIG)
        item = _make("央行宣布降息25个基点")
        clf.classify(item)
        assert item.category == "macro"

    def test_industry_keywords(self) -> None:
        clf = InfoClassifier(RULES_CONFIG)
        item = _make("新能源板块全线拉升")
        clf.classify(item)
        assert item.category == "industry"

    def test_company_keywords(self) -> None:
        clf = InfoClassifier(RULES_CONFIG)
        item = _make("比亚迪发布业绩快报")
        clf.classify(item)
        assert item.category == "company"

    def test_global_keywords(self) -> None:
        clf = InfoClassifier(RULES_CONFIG)
        item = _make("美股三大指数收涨")
        clf.classify(item)
        assert item.category == "global"

    def test_no_match_keeps_default(self) -> None:
        clf = InfoClassifier(RULES_CONFIG)
        item = _make("Some random news", category="market")
        clf.classify(item)
        assert item.category == "market"

    def test_first_match_wins(self) -> None:
        """Policy source_type match should win over keyword match."""
        clf = InfoClassifier(RULES_CONFIG)
        item = _make("降息公告")
        clf.classify(item, source_type="policy")
        assert item.category == "policy"


class TestPriorityClassification:
    def test_breaking_keywords(self) -> None:
        clf = InfoClassifier(RULES_CONFIG)
        item = _make("突发：A股暴跌")
        clf.classify(item)
        assert item.priority == "breaking"

    def test_high_keywords(self) -> None:
        clf = InfoClassifier(RULES_CONFIG)
        item = _make("央行降准0.5个百分点")
        clf.classify(item)
        assert item.priority == "high"

    def test_policy_source_gets_high(self) -> None:
        clf = InfoClassifier(RULES_CONFIG)
        item = _make("Regular policy update")
        clf.classify(item, source_type="policy")
        assert item.priority == "high"

    def test_no_match_keeps_normal(self) -> None:
        clf = InfoClassifier(RULES_CONFIG)
        item = _make("Regular market update")
        clf.classify(item)
        assert item.priority == "normal"


class TestBatchClassification:
    def test_classify_batch(self) -> None:
        clf = InfoClassifier(RULES_CONFIG)
        items = [
            _make("降息消息"),
            _make("板块轮动"),
            _make("Normal news"),
        ]
        result = clf.classify_batch(items)
        assert len(result) == 3
        assert result[0].category == "macro"
        assert result[1].category == "industry"
        assert result[2].category == "market"


class TestEdgeCases:
    def test_empty_rules(self) -> None:
        clf = InfoClassifier({})
        item = _make("降息消息")
        clf.classify(item)
        assert item.category == "market"
        assert item.priority == "normal"

    def test_none_rules(self) -> None:
        clf = InfoClassifier(None)
        item = _make("Test")
        clf.classify(item)
        assert item.category == "market"

    def test_summary_also_checked(self) -> None:
        clf = InfoClassifier(RULES_CONFIG)
        item = InfoItem(
            source_id="test",
            source_name="Test",
            title="Some news",
            summary="央行降息预期升温",
        )
        clf.classify(item)
        assert item.category == "macro"


class TestEnglishCategoryClassification:
    """Tests for English keyword-based category classification."""

    def test_english_macro_keywords(self) -> None:
        clf = InfoClassifier(RULES_CONFIG)
        item = _make("Federal Reserve signals rate cut in September")
        clf.classify(item)
        assert item.category == "macro"

    def test_english_global_keywords(self) -> None:
        clf = InfoClassifier(RULES_CONFIG)
        item = _make("S&P 500 hits all-time high as Wall Street rallies")
        clf.classify(item)
        assert item.category == "global"

    def test_english_industry_keywords(self) -> None:
        clf = InfoClassifier(RULES_CONFIG)
        item = _make("TSMC semiconductor shortage impacts EV supply chain")
        clf.classify(item)
        assert item.category == "industry"

    def test_english_company_keywords(self) -> None:
        clf = InfoClassifier(RULES_CONFIG)
        item = _make("Apple earnings beat expectations, announces buyback")
        clf.classify(item)
        assert item.category == "company"

    def test_reddit_source_type_override(self) -> None:
        clf = InfoClassifier(RULES_CONFIG)
        item = _make("Random discussion about stocks")
        clf.classify(item, source_type="reddit")
        assert item.category == "social"


class TestEnglishPriorityClassification:
    """Tests for English keyword-based priority classification."""

    def test_english_breaking_keywords(self) -> None:
        clf = InfoClassifier(RULES_CONFIG)
        item = _make("Breaking: markets plunge on circuit breaker trigger")
        clf.classify(item)
        assert item.priority == "breaking"

    def test_english_high_keywords(self) -> None:
        clf = InfoClassifier(RULES_CONFIG)
        item = _make("FOMC announces surprise rate hike")
        clf.classify(item)
        assert item.priority == "high"

    def test_english_normal_default(self) -> None:
        clf = InfoClassifier(RULES_CONFIG)
        item = _make("Markets close mixed in quiet trading session")
        clf.classify(item)
        assert item.priority == "normal"
