"""ACLED (Armed Conflict Location & Event Data) fetcher.

Real-time data on political violence and protests in 200+ countries.
Free for academic/non-commercial use. Requires API key registration
at https://acleddata.com/

Maps conflict regions to market impact channels:
  Middle East → energy prices
  East Asia → supply chain / trade routes
  Eastern Europe → commodity / grain prices
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.data.circuit_breaker import CircuitBreaker
from src.data.http_client import create_session
from src.utils.logger import get_logger

logger = get_logger("data.acled_fetcher")

__all__ = ["ConflictEvent", "AcledConflictFetcher"]

_CACHE_TTL = 3600  # 1 hour
_API_URL = "https://api.acleddata.com/acled/read"

# Region → market impact channel mapping
_REGION_MARKET_MAP: dict[str, str] = {
    "Middle East": "energy",
    "Northern Africa": "energy",
    "Eastern Europe": "commodities",
    "Western Asia": "energy",
    "South-Eastern Asia": "supply_chain",
    "Eastern Asia": "trade_route",
    "Southern Asia": "supply_chain",
    "South America": "commodities",
    "Central America": "trade_route",
}

# Countries on key shipping/energy routes
_STRATEGIC_COUNTRIES = {
    "Iran",
    "Iraq",
    "Saudi Arabia",
    "Yemen",
    "Israel",
    "Lebanon",
    "Syria",
    "Ukraine",
    "Russia",
    "Taiwan",
    "Myanmar",
    "Libya",
    "Egypt",
}


@dataclass
class ConflictEvent:
    """A single armed conflict or protest event."""

    event_id: str
    event_date: str  # YYYY-MM-DD
    event_type: str  # Battles|Violence against civilians|Explosions|Protests|Riots|Strategic developments
    country: str
    region: str
    fatalities: int
    notes: str  # event description
    source: str
    market_relevance: str  # energy|commodities|supply_chain|trade_route|none

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.event_id,
            "date": self.event_date,
            "type": self.event_type,
            "country": self.country,
            "region": self.region,
            "fatalities": self.fatalities,
            "notes": self.notes[:200],
            "market_relevance": self.market_relevance,
        }


class AcledConflictFetcher:
    """Fetch armed conflict event data from ACLED.

    Requires ACLED_API_KEY and ACLED_EMAIL env vars.
    Returns gracefully empty results if not configured.

    Usage::

        fetcher = AcledConflictFetcher()
        events = await fetcher.fetch_recent(days=7)
        mideast = await fetcher.fetch_middle_east(days=7)
    """

    def __init__(self) -> None:
        self._api_key = os.environ.get("ACLED_API_KEY", "")
        self._email = os.environ.get("ACLED_EMAIL", "")
        self._session = create_session(timeout=(10.0, 30.0), retries=2)
        self._cache: dict[str, tuple[float, Any]] = {}
        self._circuit = CircuitBreaker(
            "acled", failure_threshold=3, recovery_timeout=3600.0
        )
        if not self._api_key:
            logger.info("ACLED_API_KEY not set — conflict data will be unavailable")

    def _get_cache(self, key: str) -> Any | None:
        if key in self._cache:
            expire_ts, val = self._cache[key]
            if time.time() < expire_ts:
                return val
        return None

    def _set_cache(self, key: str, val: Any) -> None:
        self._cache[key] = (time.time() + _CACHE_TTL, val)

    @staticmethod
    def assess_market_relevance(country: str, region: str) -> str:
        """Map country/region to market impact channel."""
        if country in _STRATEGIC_COUNTRIES:
            return _REGION_MARKET_MAP.get(region, "energy")
        return _REGION_MARKET_MAP.get(region, "none")

    def _parse_event(self, row: dict[str, Any]) -> ConflictEvent:
        country = str(row.get("country", ""))
        region = str(row.get("region", ""))
        return ConflictEvent(
            event_id=str(row.get("data_id", row.get("event_id_cnty", ""))),
            event_date=str(row.get("event_date", ""))[:10],
            event_type=str(row.get("event_type", "")),
            country=country,
            region=region,
            fatalities=int(float(row.get("fatalities", 0))),
            notes=str(row.get("notes", ""))[:500],
            source=str(row.get("source", "")),
            market_relevance=self.assess_market_relevance(country, region),
        )

    def fetch_recent_sync(
        self,
        days: int = 7,
        regions: list[str] | None = None,
        event_types: list[str] | None = None,
    ) -> list[ConflictEvent]:
        """Fetch recent conflict events.

        Args:
            days: Lookback window.
            regions: Filter by ACLED regions (e.g., ["Middle East"]).
            event_types: Filter by event type (e.g., ["Battles", "Explosions/Remote violence"]).

        Returns:
            List of ConflictEvent, sorted by date descending.
        """
        if not self._api_key:
            return []

        cache_key = f"recent_{days}_{regions}_{event_types}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        if self._circuit.state == "open":
            return []

        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        params: dict[str, str] = {
            "key": self._api_key,
            "email": self._email,
            "event_date": f"{start_date}|",
            "event_date_where": "BETWEEN",
            "limit": "500",
        }

        if regions:
            params["region"] = "|".join(regions)
        if event_types:
            params["event_type"] = "|".join(event_types)

        try:
            resp = self._session.get(_API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

            if not data.get("success", True):
                logger.warning("ACLED API error: %s", data.get("error", "unknown"))
                return []

            rows = data.get("data", [])
            results = [self._parse_event(row) for row in rows]
            results.sort(key=lambda e: e.event_date, reverse=True)

            self._circuit._on_success()
            self._set_cache(cache_key, results)
            logger.info("ACLED: fetched %d events (last %d days)", len(results), days)
            return results

        except Exception as exc:
            logger.warning("ACLED fetch failed: %s", exc)
            self._circuit._on_failure()
            return []

    def fetch_middle_east_sync(self, days: int = 7) -> list[ConflictEvent]:
        """Fetch Middle East conflict events specifically."""
        return self.fetch_recent_sync(
            days=days,
            regions=["Middle East"],
            event_types=[
                "Battles",
                "Explosions/Remote violence",
                "Violence against civilians",
            ],
        )

    def get_conflict_summary(self, events: list[ConflictEvent]) -> dict[str, Any]:
        """Summarize conflict events by region and market impact."""
        by_region: dict[str, int] = {}
        by_relevance: dict[str, int] = {}
        total_fatalities = 0

        for e in events:
            by_region[e.region] = by_region.get(e.region, 0) + 1
            if e.market_relevance != "none":
                by_relevance[e.market_relevance] = (
                    by_relevance.get(e.market_relevance, 0) + 1
                )
            total_fatalities += e.fatalities

        return {
            "total_events": len(events),
            "total_fatalities": total_fatalities,
            "by_region": by_region,
            "market_channels": by_relevance,
        }

    # -- Async wrappers -------------------------------------------------------

    async def fetch_recent(
        self,
        days: int = 7,
        regions: list[str] | None = None,
        event_types: list[str] | None = None,
    ) -> list[ConflictEvent]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self.fetch_recent_sync, days, regions, event_types
        )

    async def fetch_middle_east(self, days: int = 7) -> list[ConflictEvent]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.fetch_middle_east_sync, days)
