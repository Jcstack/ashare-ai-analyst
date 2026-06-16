"""Concept board API endpoints.

Per PRD v3.3 FR-CS004:
  GET /concept/hot                        – concept heat ranking
  GET /concept/{board_code}/constituents  – constituent stocks
  GET /concept/{board_code}/history       – historical OHLCV
  GET /stock/{symbol}/concepts            – stock's concepts + resonance
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Query

from src.analysis.concept_analyzer import ConceptAnalyzer
from src.data.concept_board import ConceptBoardService
from src.web.dependencies import get_concept_analyzer, get_concept_board_service
from src.web.schemas.concept import (
    ConceptConstituentItem,
    ConceptHeatListResponse,
    ConceptHeatResponse,
    ConceptHistoryRecord,
    ConceptLeader,
    ResonanceResponse,
    StockConceptItemResponse,
    StockConceptsResponse,
)

router = APIRouter(tags=["concept"])


@router.get("/concept/hot", response_model=ConceptHeatListResponse)
async def get_concept_hot(
    top_n: int = Query(20, ge=1, le=100),
    analyzer: ConceptAnalyzer = Depends(get_concept_analyzer),
) -> ConceptHeatListResponse:
    """Return concept boards ranked by multi-factor heat score."""
    import asyncio

    items = await asyncio.to_thread(analyzer.rank_concepts, top_n)
    return ConceptHeatListResponse(
        items=[
            ConceptHeatResponse(
                code=h.code,
                name=h.name,
                pct_change=h.pct_change,
                amount=h.amount,
                up_count=h.up_count,
                down_count=h.down_count,
                heat_score=h.heat_score,
                leader=ConceptLeader(
                    symbol=h.leader_symbol,
                    name=h.leader_name,
                    pct_change=h.leader_pct,
                ),
            )
            for h in items
        ],
        updated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )


@router.get(
    "/concept/{board_code}/constituents",
    response_model=list[ConceptConstituentItem],
)
async def get_concept_constituents(
    board_code: str,
    sort_by: str = Query("pct_change", pattern="^(pct_change|amount)$"),
    svc: ConceptBoardService = Depends(get_concept_board_service),
) -> list[ConceptConstituentItem]:
    """Return constituent stocks for a concept board."""
    import asyncio

    stocks = await asyncio.to_thread(svc.fetch_concept_constituents, board_code)
    items = [
        ConceptConstituentItem(
            symbol=s.symbol,
            name=s.name,
            price=s.price,
            pct_change=s.pct_change,
            amount=s.amount,
            amplitude=s.amplitude,
        )
        for s in stocks
    ]
    # Sort
    if sort_by == "amount":
        items.sort(key=lambda x: x.amount or 0, reverse=True)
    else:
        items.sort(key=lambda x: x.pct_change or 0, reverse=True)
    return items


@router.get(
    "/concept/{board_code}/history",
    response_model=list[ConceptHistoryRecord],
)
async def get_concept_history(
    board_code: str,
    period: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    days: int = Query(60, ge=7, le=365),
    svc: ConceptBoardService = Depends(get_concept_board_service),
) -> list[ConceptHistoryRecord]:
    """Return historical OHLCV data for a concept board."""
    import asyncio

    records = await asyncio.to_thread(
        svc.fetch_concept_history, board_code, period, days
    )
    return [ConceptHistoryRecord(**r) for r in records]


@router.get(
    "/stock/{symbol}/concepts",
    response_model=StockConceptsResponse,
)
async def get_stock_concepts(
    symbol: str,
    analyzer: ConceptAnalyzer = Depends(get_concept_analyzer),
) -> StockConceptsResponse:
    """Return concept boards a stock belongs to, with resonance analysis."""
    import asyncio

    analysis = await asyncio.to_thread(analyzer.analyze_stock_concepts, symbol)
    return StockConceptsResponse(
        symbol=analysis.symbol,
        industry=analysis.industry,
        concepts=[
            StockConceptItemResponse(
                code=c.code,
                name=c.name,
                pct_change=c.pct_change,
                amount=c.amount,
                up_count=c.up_count,
                down_count=c.down_count,
                stock_rank_pct=c.stock_rank_pct,
            )
            for c in analysis.concepts
        ],
        resonance=ResonanceResponse(
            level=analysis.resonance.level,
            concepts=analysis.resonance.concepts,
            top_driver=analysis.resonance.top_driver,
            rank_in_driver=analysis.resonance.rank_in_driver,
        ),
    )
