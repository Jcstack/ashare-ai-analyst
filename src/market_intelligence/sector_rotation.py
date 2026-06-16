"""Sector rotation detection service.

Analyses relative sector performance to identify rotation patterns —
capital flowing from lagging sectors into leading ones.

Part of v20.0 Phase 5 market intelligence layer.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger("market_intelligence.sector_rotation")

# A-share sector index codes mapped to sector names.
_DEFAULT_SECTORS: dict[str, str] = {
    "880301": "银行",
    "880302": "房地产",
    "880303": "医药生物",
    "880304": "电子",
    "880305": "计算机",
    "880306": "食品饮料",
    "880307": "有色金属",
    "880308": "电力设备",
    "880309": "机械设备",
    "880310": "化工",
}

_PERIOD_DAYS: dict[str, int] = {
    "1d": 1,
    "1w": 5,
    "2w": 10,
    "1m": 20,
    "3m": 60,
}


class SectorRotationDetector:
    """Detect sector rotation patterns from relative performance.

    Uses momentum-based analysis across A-share sector indices to identify
    capital flows between sectors.

    Args:
        stock_service: Optional shared StockService for fetching sector data.
    """

    def __init__(self, stock_service: Any | None = None) -> None:
        self._stock_service = stock_service
        self._sectors = dict(_DEFAULT_SECTORS)

    def detect_rotation(self, lookback_days: int = 20) -> dict[str, Any]:
        """Detect sector rotation patterns.

        Computes short-term vs long-term momentum for each sector and ranks
        them. Sectors accelerating relative to peers are classified as
        *leading*; those decelerating are *lagging*.

        Args:
            lookback_days: Number of trading days to analyse.

        Returns:
            Dict with leading_sectors, lagging_sectors, rotation_strength,
            and timestamp.
        """
        performances = self._fetch_sector_returns(lookback_days)
        if not performances:
            return {
                "leading_sectors": [],
                "lagging_sectors": [],
                "rotation_strength": 0.0,
                "timestamp": _now(),
            }

        # Split lookback into two halves to compute acceleration
        half = max(1, lookback_days // 2)
        first_half = self._fetch_sector_returns(lookback_days, offset=half)

        leading: list[dict[str, Any]] = []
        lagging: list[dict[str, Any]] = []

        for code, name in self._sectors.items():
            recent_ret = performances.get(code, 0.0)
            prior_ret = first_half.get(code, 0.0)
            acceleration = recent_ret - prior_ret

            entry = {
                "sector_code": code,
                "sector_name": name,
                "return_pct": round(recent_ret * 100, 2),
                "acceleration": round(acceleration * 100, 2),
            }

            if acceleration > 0:
                leading.append(entry)
            else:
                lagging.append(entry)

        # Sort by acceleration magnitude
        leading.sort(key=lambda x: x["acceleration"], reverse=True)
        lagging.sort(key=lambda x: x["acceleration"])

        # Rotation strength: spread between top leader and worst lagger
        all_accels = [e["acceleration"] for e in leading + lagging]
        if len(all_accels) >= 2:
            spread = max(all_accels) - min(all_accels)
            rotation_strength = float(np.clip(spread / 10.0, 0.0, 1.0))
        else:
            rotation_strength = 0.0

        return {
            "leading_sectors": leading[:5],
            "lagging_sectors": lagging[:5],
            "rotation_strength": round(rotation_strength, 3),
            "timestamp": _now(),
        }

    def get_sector_performance(self, period: str = "1w") -> list[dict[str, Any]]:
        """Get relative sector performance for the given period.

        Args:
            period: Time window — one of ``"1d"``, ``"1w"``, ``"2w"``,
                ``"1m"``, ``"3m"``.

        Returns:
            List of dicts with sector_code, sector_name, return_pct, rank.
        """
        days = _PERIOD_DAYS.get(period, 5)
        performances = self._fetch_sector_returns(days)

        results: list[dict[str, Any]] = []
        for code, name in self._sectors.items():
            ret = performances.get(code, 0.0)
            results.append(
                {
                    "sector_code": code,
                    "sector_name": name,
                    "return_pct": round(ret * 100, 2),
                }
            )

        results.sort(key=lambda x: x["return_pct"], reverse=True)
        for rank, entry in enumerate(results, 1):
            entry["rank"] = rank

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_sector_returns(
        self,
        days: int,
        offset: int = 0,
    ) -> dict[str, float]:
        """Fetch sector-level returns from the stock service.

        Falls back to random placeholders when the service is unavailable
        so that the orchestration layer can still be exercised during
        development.
        """
        results: dict[str, float] = {}

        for code in self._sectors:
            closes = self._get_closes(code, days + offset)
            if closes is not None and len(closes) > offset + 1:
                segment = closes.iloc[: len(closes) - offset] if offset > 0 else closes
                if len(segment) >= 2:
                    ret = (segment.iloc[-1] - segment.iloc[0]) / segment.iloc[0]
                    results[code] = float(ret)
                    continue
            # Fallback: zero return when data unavailable
            results[code] = 0.0

        return results

    def _get_closes(self, symbol: str, days: int) -> pd.Series | None:
        """Retrieve closing prices for *symbol* over *days* trading days."""
        if self._stock_service is None:
            return None
        try:
            df = self._stock_service.get_historical_data(symbol, period=days)
            if df is not None and "close" in df.columns:
                return df["close"]
        except Exception:
            logger.debug("Failed to fetch closes for %s", symbol, exc_info=True)
        return None


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")
