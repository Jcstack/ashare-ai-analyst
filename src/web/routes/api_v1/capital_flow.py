"""Capital flow API endpoints.

Per PRD v26.0 FR-CF003: Macro capital flow overview and history.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, Query

from src.web.dependencies import get_capital_flow_service
from src.web.schemas.capital_flow import (
    HeatmapResponse,
    MacroFlowHistoryResponse,
    MacroFlowOverview,
    SectorFlowResponse,
)
from src.web.services.capital_flow_service import CapitalFlowService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["capital-flow"])


@router.get("/macro", response_model=MacroFlowOverview)
async def get_macro_overview(
    svc: CapitalFlowService = Depends(get_capital_flow_service),
) -> dict:
    """Get today's macro capital flow overview.

    Returns composite environment score [-100, +100] with 4-channel breakdown:
    northbound, southbound, margin, and ETF net flow.
    """
    return await asyncio.to_thread(svc.get_macro_overview)


@router.get("/macro/history", response_model=MacroFlowHistoryResponse)
async def get_macro_history(
    days: int = Query(30, ge=1, le=180, description="Number of days"),
    svc: CapitalFlowService = Depends(get_capital_flow_service),
) -> dict:
    """Get macro capital flow history with daily scores."""
    return await asyncio.to_thread(svc.get_macro_history, days)


@router.get("/sectors", response_model=SectorFlowResponse)
async def get_sector_ranking(
    type: str = Query("industry", description="industry or concept"),
    period: str = Query("today", description="today/3d/5d/10d"),
    svc: CapitalFlowService = Depends(get_capital_flow_service),
) -> dict:
    """Get sector capital flow ranking.

    Returns industry (申万一级) or concept board fund flow ranking
    sorted by net inflow for the specified period.
    """
    return await asyncio.to_thread(svc.get_sector_ranking, type, period)


@router.get("/sectors/heatmap", response_model=HeatmapResponse)
async def get_sector_heatmap(
    svc: CapitalFlowService = Depends(get_capital_flow_service),
) -> dict:
    """Get sector flow heatmap data.

    Returns industry sector flow data normalised for heatmap visualisation,
    with color_value in [-1, 1] range based on net inflow.
    """
    return await asyncio.to_thread(svc.get_heatmap_data)
