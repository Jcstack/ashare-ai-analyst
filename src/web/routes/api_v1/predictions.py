"""Prediction JSON API endpoints.

Runs Claude AI analysis on a stock and returns structured results.
Per PRD v2.5 FR-EP001~EP006.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.web.dependencies import get_prediction_service
from src.web.routes.api_v1.schemas import (
    ComparisonPredictionRequest,
    ComparisonPredictionResult,
    EnhancedPredictionRequest,
    EnhancedPredictionResult,
    PredictionResult,
)

router = APIRouter(tags=["predictions"])


# NOTE: /predict/compare MUST be registered BEFORE /predict/{symbol}
# so FastAPI does not treat "compare" as a {symbol} path parameter.
@router.post("/predict/compare", response_model=ComparisonPredictionResult)
async def predict_comparison(
    body: ComparisonPredictionRequest,
    svc=Depends(get_prediction_service),
) -> dict:
    """Run multi-stock comparison prediction.

    Args:
        body: Request with symbol list and source selection.

    Returns:
        Comparison result with per-stock analyses and ranking.
    """
    result = svc.predict_comparison(body.symbols, sources=body.sources)
    return result


@router.post("/predict/{symbol}", response_model=PredictionResult)
async def predict_stock(
    symbol: str,
    svc=Depends(get_prediction_service),
) -> dict:
    """Run a Claude prediction analysis for a stock.

    Args:
        symbol: 6-digit stock code.

    Returns:
        Prediction result with trend, signal, confidence, reasoning, etc.
    """
    result = svc.predict(symbol)
    return result


@router.post("/predict/{symbol}/enhanced", response_model=EnhancedPredictionResult)
async def predict_enhanced(
    symbol: str,
    body: EnhancedPredictionRequest | None = None,
    svc=Depends(get_prediction_service),
) -> dict:
    """Run enhanced prediction with selectable data sources.

    Args:
        symbol: 6-digit stock code.
        body: Optional request body with source selection.

    Returns:
        Enhanced prediction result with data source tags.
    """
    sources = body.sources if body else ["indicators", "fund_flow"]
    include_bayesian = body.include_bayesian if body else False
    include_risk = body.include_risk if body else False
    result = svc.predict_enhanced(
        symbol,
        sources=sources,
        include_bayesian=include_bayesian,
        include_risk=include_risk,
    )
    return result
