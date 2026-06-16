"""Tests for ConceptAnalyzer."""

from unittest.mock import MagicMock

import pytest

from src.analysis.concept_analyzer import (
    ConceptAnalyzer,
)
from src.data.concept_board import (
    ConceptBoardItem,
    ConceptBoardService,
    ConstituentStock,
    StockConceptItem,
    StockConceptsResult,
)


@pytest.fixture
def mock_svc():
    return MagicMock(spec=ConceptBoardService)


@pytest.fixture
def analyzer(mock_svc):
    return ConceptAnalyzer(concept_service=mock_svc)


# ---------------------------------------------------------------------------
# rank_concepts
# ---------------------------------------------------------------------------


def test_rank_concepts_basic(analyzer, mock_svc):
    mock_svc.fetch_concept_list.return_value = [
        ConceptBoardItem(
            code="BK01",
            name="A",
            pct_change=5.0,
            up_count=20,
            down_count=5,
            amount=1e10,
        ),
        ConceptBoardItem(
            code="BK02",
            name="B",
            pct_change=1.0,
            up_count=10,
            down_count=15,
            amount=5e9,
        ),
        ConceptBoardItem(
            code="BK03", name="C", pct_change=3.0, up_count=18, down_count=2, amount=8e9
        ),
    ]
    mock_svc.fetch_concept_constituents.return_value = [
        ConstituentStock(symbol="000001", name="Test", pct_change=7.0),
    ]

    items = analyzer.rank_concepts(top_n=3)
    assert len(items) == 3
    # First item should have highest heat score
    assert items[0].heat_score >= items[1].heat_score
    assert items[1].heat_score >= items[2].heat_score
    # Leader filled
    assert items[0].leader_symbol == "000001"


def test_rank_concepts_empty(analyzer, mock_svc):
    mock_svc.fetch_concept_list.return_value = []
    assert analyzer.rank_concepts() == []


def test_rank_concepts_top_n(analyzer, mock_svc):
    mock_svc.fetch_concept_list.return_value = [
        ConceptBoardItem(code=f"BK{i:02d}", name=f"C{i}", pct_change=float(i))
        for i in range(10)
    ]
    mock_svc.fetch_concept_constituents.return_value = []

    items = analyzer.rank_concepts(top_n=3)
    assert len(items) == 3


# ---------------------------------------------------------------------------
# analyze_stock_concepts
# ---------------------------------------------------------------------------


def test_analyze_stock_concepts_with_resonance(analyzer, mock_svc):
    mock_svc.fetch_stock_concepts.return_value = StockConceptsResult(
        symbol="001330",
        industry="文化传媒",
        concepts=[
            StockConceptItem(
                code="BK01",
                name="影视院线",
                pct_change=3.21,
                up_count=18,
                down_count=5,
                amount=5e9,
            ),
            StockConceptItem(
                code="BK02",
                name="文生视频",
                pct_change=5.12,
                up_count=25,
                down_count=3,
                amount=1.2e10,
            ),
            StockConceptItem(
                code="BK03",
                name="短剧",
                pct_change=1.5,
                up_count=12,
                down_count=8,
                amount=3e9,
            ),
        ],
    )
    # Mock constituents for rank computation
    mock_svc.fetch_concept_constituents.return_value = [
        ConstituentStock(symbol="001330", name="博纳影业", pct_change=7.83),
        ConstituentStock(symbol="600977", name="中国电影", pct_change=3.2),
        ConstituentStock(symbol="300133", name="华策影视", pct_change=1.1),
    ]

    result = analyzer.analyze_stock_concepts("001330")
    assert result.symbol == "001330"
    assert result.industry == "文化传媒"
    assert len(result.concepts) == 3
    # Resonance: 3 concepts > 1% → moderate
    assert result.resonance.level == "moderate"
    assert "影视院线" in result.resonance.concepts
    assert result.resonance.top_driver == "文生视频"  # highest pct
    # 001330 is first in sorted list → rank_pct = 0.0 → 领涨
    assert result.resonance.rank_in_driver == "领涨"


def test_analyze_stock_concepts_no_resonance(analyzer, mock_svc):
    mock_svc.fetch_stock_concepts.return_value = StockConceptsResult(
        symbol="600000",
        industry="银行",
        concepts=[
            StockConceptItem(code="BK01", name="银行", pct_change=0.2),
            StockConceptItem(code="BK02", name="沪股通", pct_change=0.1),
        ],
    )
    mock_svc.fetch_concept_constituents.return_value = []

    result = analyzer.analyze_stock_concepts("600000")
    assert result.resonance.level == "none"
    assert result.resonance.concepts == []


def test_analyze_stock_concepts_strong_resonance(analyzer, mock_svc):
    # 5 concepts > 1% → strong
    mock_svc.fetch_stock_concepts.return_value = StockConceptsResult(
        symbol="300750",
        concepts=[
            StockConceptItem(code=f"BK0{i}", name=f"C{i}", pct_change=1.5 + i * 0.5)
            for i in range(5)
        ],
    )
    mock_svc.fetch_concept_constituents.return_value = []

    result = analyzer.analyze_stock_concepts("300750")
    assert result.resonance.level == "strong"


def test_analyze_stock_concepts_empty(analyzer, mock_svc):
    mock_svc.fetch_stock_concepts.return_value = StockConceptsResult(symbol="999999")
    result = analyzer.analyze_stock_concepts("999999")
    assert result.concepts == []
    assert result.resonance.level == "none"


# ---------------------------------------------------------------------------
# _detect_resonance edge cases
# ---------------------------------------------------------------------------


def test_resonance_weak(analyzer, mock_svc):
    """2 concepts > 0.5% but < 1% → weak."""
    mock_svc.fetch_stock_concepts.return_value = StockConceptsResult(
        symbol="000001",
        concepts=[
            StockConceptItem(code="BK01", name="A", pct_change=0.8),
            StockConceptItem(code="BK02", name="B", pct_change=0.6),
            StockConceptItem(code="BK03", name="C", pct_change=0.1),
        ],
    )
    mock_svc.fetch_concept_constituents.return_value = []

    result = analyzer.analyze_stock_concepts("000001")
    assert result.resonance.level == "weak"


def test_resonance_strong_via_high_pct(analyzer, mock_svc):
    """3 concepts > 2% → strong."""
    mock_svc.fetch_stock_concepts.return_value = StockConceptsResult(
        symbol="000002",
        concepts=[
            StockConceptItem(code="BK01", name="A", pct_change=2.5),
            StockConceptItem(code="BK02", name="B", pct_change=3.0),
            StockConceptItem(code="BK03", name="C", pct_change=2.1),
        ],
    )
    mock_svc.fetch_concept_constituents.return_value = []

    result = analyzer.analyze_stock_concepts("000002")
    assert result.resonance.level == "strong"


# ---------------------------------------------------------------------------
# _min_max_norm
# ---------------------------------------------------------------------------


def test_min_max_norm():
    from src.analysis.concept_analyzer import _min_max_norm

    assert _min_max_norm([]) == []
    assert _min_max_norm([5.0, 5.0, 5.0]) == [0.5, 0.5, 0.5]
    result = _min_max_norm([0.0, 5.0, 10.0])
    assert result == [0.0, 0.5, 1.0]
