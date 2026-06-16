"""Tests for concept board API routes."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.analysis.concept_analyzer import (
    ConceptAnalyzer,
    ConceptHeatItem,
    ResonanceInfo,
    StockConceptAnalysis,
    StockConceptDetail,
)
from src.data.concept_board import ConceptBoardService, ConstituentStock


@pytest.fixture
def mock_concept_svc():
    return MagicMock(spec=ConceptBoardService)


@pytest.fixture
def mock_analyzer():
    return MagicMock(spec=ConceptAnalyzer)


@pytest.fixture
def client(mock_concept_svc, mock_analyzer):
    from fastapi import FastAPI

    from src.web.routes.api_v1.concept import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    from src.web.dependencies import get_concept_analyzer, get_concept_board_service

    app.dependency_overrides[get_concept_board_service] = lambda: mock_concept_svc
    app.dependency_overrides[get_concept_analyzer] = lambda: mock_analyzer

    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /concept/hot
# ---------------------------------------------------------------------------


def test_concept_hot(client, mock_analyzer):
    mock_analyzer.rank_concepts.return_value = [
        ConceptHeatItem(
            code="BK0896",
            name="文生视频",
            pct_change=5.12,
            amount=1.2e10,
            up_count=25,
            down_count=3,
            heat_score=92.3,
            leader_symbol="001330",
            leader_name="博纳影业",
            leader_pct=7.83,
        ),
    ]

    resp = client.get("/api/v1/concept/hot?top_n=5")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["name"] == "文生视频"
    assert data["items"][0]["heat_score"] == 92.3
    assert data["items"][0]["leader"]["symbol"] == "001330"


# ---------------------------------------------------------------------------
# GET /concept/{board_code}/constituents
# ---------------------------------------------------------------------------


def test_concept_constituents(client, mock_concept_svc):
    mock_concept_svc.fetch_concept_constituents.return_value = [
        ConstituentStock(
            symbol="001330", name="博纳影业", price=8.5, pct_change=7.83, amount=5e8
        ),
        ConstituentStock(
            symbol="600977", name="中国电影", price=12.3, pct_change=3.2, amount=8e8
        ),
    ]

    resp = client.get("/api/v1/concept/BK0501/constituents")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    # Default sort by pct_change desc
    assert data[0]["symbol"] == "001330"
    assert data[0]["pct_change"] == 7.83


def test_concept_constituents_sort_by_amount(client, mock_concept_svc):
    mock_concept_svc.fetch_concept_constituents.return_value = [
        ConstituentStock(symbol="001330", name="博纳影业", pct_change=7.83, amount=5e8),
        ConstituentStock(symbol="600977", name="中国电影", pct_change=3.2, amount=8e8),
    ]

    resp = client.get("/api/v1/concept/BK0501/constituents?sort_by=amount")
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["symbol"] == "600977"  # higher amount


# ---------------------------------------------------------------------------
# GET /concept/{board_code}/history
# ---------------------------------------------------------------------------


def test_concept_history(client, mock_concept_svc):
    mock_concept_svc.fetch_concept_history.return_value = [
        {
            "date": "2026-02-13",
            "open": 100.0,
            "close": 103.0,
            "high": 104.0,
            "low": 99.0,
            "volume": 1e6,
            "amount": 1e8,
            "pct_change": 3.0,
        }
    ]

    resp = client.get("/api/v1/concept/BK0501/history?days=30")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["pct_change"] == 3.0


# ---------------------------------------------------------------------------
# GET /stock/{symbol}/concepts
# ---------------------------------------------------------------------------


def test_stock_concepts(client, mock_analyzer):
    mock_analyzer.analyze_stock_concepts.return_value = StockConceptAnalysis(
        symbol="001330",
        industry="文化传媒",
        concepts=[
            StockConceptDetail(
                code="BK0501", name="影视院线", pct_change=3.21, stock_rank_pct=0.05
            ),
            StockConceptDetail(
                code="BK0896", name="文生视频", pct_change=5.12, stock_rank_pct=0.15
            ),
        ],
        resonance=ResonanceInfo(
            level="moderate",
            concepts=["影视院线", "文生视频"],
            top_driver="文生视频",
            rank_in_driver="领涨",
        ),
    )

    resp = client.get("/api/v1/stock/001330/concepts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "001330"
    assert data["industry"] == "文化传媒"
    assert len(data["concepts"]) == 2
    assert data["resonance"]["level"] == "moderate"
    assert data["resonance"]["top_driver"] == "文生视频"


def test_stock_concepts_empty(client, mock_analyzer):
    mock_analyzer.analyze_stock_concepts.return_value = StockConceptAnalysis(
        symbol="999999"
    )

    resp = client.get("/api/v1/stock/999999/concepts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["concepts"] == []
    assert data["resonance"]["level"] == "none"
