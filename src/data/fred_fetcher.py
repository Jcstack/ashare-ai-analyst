"""Federal Reserve Economic Data (FRED) fetcher for US macro indicators.

Fetches interest rates, inflation, employment, and financial conditions
data from the FRED API. Fed policy directly impacts A-share valuations
via USD/CNY → northbound capital flows.

Requires FRED_API_KEY env var (free registration at fred.stlouisfed.org).
If key is missing, all methods return None gracefully.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import aiohttp

from src.utils.logger import get_logger

logger = get_logger("data.fred_fetcher")

__all__ = [
    "FredFetcher",
    "FredObservation",
    "FredMacroSnapshot",
    "SERIES_CONFIG",
]

# ---------------------------------------------------------------------------
# Series configuration
# ---------------------------------------------------------------------------

SERIES_CONFIG: dict[str, dict[str, str]] = {
    # Interest rates (直接影响资金流向)
    "DFF": {
        "name": "联邦基金利率",
        "frequency": "daily",
        "impact": "USD强弱→北向资金",
    },
    "DGS10": {
        "name": "美国10年期国债收益率",
        "frequency": "daily",
        "impact": "全球风险偏好",
    },
    "DGS2": {
        "name": "美国2年期国债收益率",
        "frequency": "daily",
        "impact": "加息预期",
    },
    "T10Y2Y": {
        "name": "10Y-2Y利差(衰退指标)",
        "frequency": "daily",
        "impact": "衰退预警→避险",
    },
    # Employment (就业→消费→全球需求)
    "UNRATE": {
        "name": "美国失业率",
        "frequency": "monthly",
        "impact": "消费需求→中国出口",
    },
    "PAYEMS": {
        "name": "非农就业人数",
        "frequency": "monthly",
        "impact": "经济强度信号",
    },
    # Inflation (通胀→加息预期)
    "CPIAUCSL": {
        "name": "CPI通胀指数",
        "frequency": "monthly",
        "impact": "加息路径→USD→北向",
    },
    "PCEPI": {
        "name": "PCE物价指数",
        "frequency": "monthly",
        "impact": "Fed首选通胀指标",
    },
    # Dollar & Trade
    "DTWEXBGS": {
        "name": "美元指数(广义)",
        "frequency": "daily",
        "impact": "USD↑→新兴市场资金外流",
    },
    # Financial conditions
    "BAMLH0A0HYM2": {
        "name": "高收益债利差",
        "frequency": "daily",
        "impact": "信用风险→全球risk-off",
    },
    "VIXCLS": {
        "name": "VIX恐慌指数",
        "frequency": "daily",
        "impact": "全球风险情绪",
    },
}

# Cache TTLs by frequency
_CACHE_TTL: dict[str, int] = {
    "daily": 3600,  # 1 hour
    "monthly": 21600,  # 6 hours
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class FredObservation:
    """A single FRED data point."""

    series_id: str
    series_name: str  # Chinese name
    date: str  # YYYY-MM-DD
    value: float
    previous_value: float | None = None
    change_pct: float | None = None


@dataclass
class FredMacroSnapshot:
    """Aggregated macro snapshot from FRED."""

    fed_funds_rate: float | None = None
    us_10y_yield: float | None = None
    us_2y_yield: float | None = None
    yield_curve_spread: float | None = None  # 10Y-2Y, negative = recession signal
    vix: float | None = None
    dollar_index: float | None = None
    hy_spread: float | None = None  # high yield spread, wider = risk-off
    cpi_yoy: float | None = None
    unemployment_rate: float | None = None

    # Derived signals
    recession_signal: bool = False  # True if yield curve inverted
    risk_appetite: str = "neutral"  # "risk-on" / "risk-off" / "neutral"
    fed_stance: str = "neutral"  # "hawkish" / "dovish" / "neutral"

    fetched_at: datetime = field(default_factory=datetime.now)

    def to_snapshot_text(self) -> str:
        """Serialize for MarketSnapshot injection."""
        parts: list[str] = []
        if self.fed_funds_rate is not None:
            parts.append(f"联邦基金利率:{self.fed_funds_rate:.2f}%")
        if self.us_10y_yield is not None:
            parts.append(f"10Y:{self.us_10y_yield:.2f}%")
        if self.yield_curve_spread is not None:
            inv = " 倒挂" if self.yield_curve_spread < 0 else ""
            parts.append(f"期限利差:{self.yield_curve_spread:+.2f}%{inv}")
        if self.vix is not None:
            parts.append(f"VIX:{self.vix:.1f}")
        if self.dollar_index is not None:
            parts.append(f"美元:{self.dollar_index:.1f}")
        if self.hy_spread is not None:
            parts.append(f"高收益利差:{self.hy_spread:.2f}%")
        parts.append(f"风险偏好:{self.risk_appetite}")
        parts.append(f"Fed立场:{self.fed_stance}")
        if self.recession_signal:
            parts.append("衰退预警")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------


def _parse_fred_value(raw: str) -> float | None:
    """Parse a FRED observation value string.

    FRED uses ``"."`` to indicate missing/unavailable data.
    """
    if raw is None or raw.strip() == ".":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


class FredFetcher:
    """Fetch US macro economic data from FRED API.

    Requires ``FRED_API_KEY`` env var (free registration).
    If key is missing, all methods return ``None`` gracefully.
    """

    BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("FRED_API_KEY", "")
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._last_request_ts: float = 0.0
        # In-memory cache: key → (monotonic_ts, data)
        self._cache: dict[str, tuple[float, object]] = {}
        if self.available:
            logger.info("FredFetcher initialized (API key configured)")
        else:
            logger.warning(
                "FredFetcher: FRED_API_KEY not set — all calls will return None"
            )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Whether FRED API key is configured."""
        return bool(self._api_key)

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _get_cached(self, key: str, ttl: int) -> object | None:
        if key in self._cache:
            ts, val = self._cache[key]
            if time.monotonic() - ts < ttl:
                return val
        return None

    def _set_cached(self, key: str, val: object) -> None:
        self._cache[key] = (time.monotonic(), val)

    def _ttl_for_series(self, series_id: str) -> int:
        """Return cache TTL based on series frequency."""
        cfg = SERIES_CONFIG.get(series_id, {})
        freq = cfg.get("frequency", "daily")
        return _CACHE_TTL.get(freq, 3600)

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    async def _polite_wait(self, interval: float = 0.5) -> None:
        """Wait between requests to stay well under FRED's 120 req/min limit."""
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < interval:
            await asyncio.sleep(interval - elapsed)
        self._last_request_ts = time.monotonic()

    # ------------------------------------------------------------------
    # Core HTTP
    # ------------------------------------------------------------------

    async def _request(self, series_id: str, limit: int = 30) -> list[dict] | None:
        """Execute a single FRED API request.

        Returns the ``observations`` list or ``None`` on error.
        """
        if not self.available:
            return None

        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        params = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": limit,
            "observation_start": start_date,
        }

        await self._polite_wait()

        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.get(self.BASE_URL, params=params) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning(
                            "FRED API error for %s: HTTP %d — %s",
                            series_id,
                            resp.status,
                            body[:200],
                        )
                        return None
                    data = await resp.json()
                    return data.get("observations", [])
        except asyncio.TimeoutError:
            logger.warning("FRED API timeout for %s", series_id)
            return None
        except Exception as exc:
            logger.warning("FRED API request failed for %s: %s", series_id, exc)
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_series(
        self, series_id: str, limit: int = 30
    ) -> list[FredObservation]:
        """Fetch recent observations for a FRED series.

        Args:
            series_id: FRED series identifier (e.g. ``"DGS10"``).
            limit: Maximum number of recent observations.

        Returns:
            List of observations ordered newest-first, or empty list on error.
        """
        if not self.available:
            return []

        cache_key = f"series:{series_id}:{limit}"
        ttl = self._ttl_for_series(series_id)
        cached = self._get_cached(cache_key, ttl)
        if cached is not None:
            return cached  # type: ignore[return-value]

        raw_obs = await self._request(series_id, limit=limit)
        if raw_obs is None:
            return []

        cfg = SERIES_CONFIG.get(series_id, {})
        series_name = cfg.get("name", series_id)

        # Parse observations (newest first from API)
        parsed: list[FredObservation] = []
        for i, obs in enumerate(raw_obs):
            val = _parse_fred_value(obs.get("value", "."))
            if val is None:
                continue
            # Previous value is the next item (older) in the desc-sorted list
            prev_val: float | None = None
            for j in range(i + 1, len(raw_obs)):
                pv = _parse_fred_value(raw_obs[j].get("value", "."))
                if pv is not None:
                    prev_val = pv
                    break

            change_pct: float | None = None
            if prev_val is not None and prev_val != 0:
                change_pct = round((val - prev_val) / abs(prev_val) * 100, 4)

            parsed.append(
                FredObservation(
                    series_id=series_id,
                    series_name=series_name,
                    date=obs.get("date", ""),
                    value=val,
                    previous_value=prev_val,
                    change_pct=change_pct,
                )
            )

        self._set_cached(cache_key, parsed)
        return parsed

    async def fetch_latest(self, series_id: str) -> FredObservation | None:
        """Fetch the most recent observation for a series.

        Returns ``None`` if unavailable.
        """
        obs_list = await self.fetch_series(series_id, limit=5)
        return obs_list[0] if obs_list else None

    async def get_macro_snapshot(self) -> FredMacroSnapshot | None:
        """Build a complete macro snapshot from key FRED series.

        Fetches all key series in parallel and derives risk/fed signals.
        Returns ``None`` if the API key is not configured.
        """
        if not self.available:
            return None

        cache_key = "macro_snapshot"
        cached = self._get_cached(cache_key, ttl=3600)
        if cached is not None:
            return cached  # type: ignore[return-value]

        # Fetch all series in parallel
        series_ids = [
            "DFF",
            "DGS10",
            "DGS2",
            "T10Y2Y",
            "UNRATE",
            "CPIAUCSL",
            "DTWEXBGS",
            "BAMLH0A0HYM2",
            "VIXCLS",
        ]
        results = await asyncio.gather(
            *[self.fetch_latest(sid) for sid in series_ids],
            return_exceptions=True,
        )

        # Build lookup: series_id → latest value
        latest: dict[str, float | None] = {}
        for sid, res in zip(series_ids, results):
            if isinstance(res, FredObservation):
                latest[sid] = res.value
            else:
                if isinstance(res, Exception):
                    logger.warning("FRED fetch exception for %s: %s", sid, res)
                latest[sid] = None

        # Also check recession signal: T10Y2Y < 0 for last 3 observations
        recession = False
        t10y2y_series = await self.fetch_series("T10Y2Y", limit=5)
        if len(t10y2y_series) >= 3:
            last_3 = [obs.value for obs in t10y2y_series[:3]]
            recession = all(v < 0 for v in last_3)

        snapshot = FredMacroSnapshot(
            fed_funds_rate=latest.get("DFF"),
            us_10y_yield=latest.get("DGS10"),
            us_2y_yield=latest.get("DGS2"),
            yield_curve_spread=latest.get("T10Y2Y"),
            vix=latest.get("VIXCLS"),
            dollar_index=latest.get("DTWEXBGS"),
            hy_spread=latest.get("BAMLH0A0HYM2"),
            cpi_yoy=latest.get("CPIAUCSL"),
            unemployment_rate=latest.get("UNRATE"),
            recession_signal=recession,
            risk_appetite=self._derive_risk_appetite(
                latest.get("VIXCLS"), latest.get("BAMLH0A0HYM2")
            ),
            fed_stance=self._derive_fed_stance(
                latest.get("DFF"), latest.get("CPIAUCSL"), latest.get("UNRATE")
            ),
            fetched_at=datetime.now(),
        )

        self._set_cached(cache_key, snapshot)
        logger.info(
            "FRED macro snapshot built: fed=%.2f%%, 10Y=%.2f%%, VIX=%.1f, stance=%s",
            snapshot.fed_funds_rate or 0,
            snapshot.us_10y_yield or 0,
            snapshot.vix or 0,
            snapshot.fed_stance,
        )
        return snapshot

    # ------------------------------------------------------------------
    # Derived signal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_risk_appetite(vix: float | None, hy_spread: float | None) -> str:
        """Derive risk appetite from VIX and high yield spread.

        - VIX > 25 → risk-off
        - VIX < 15 → risk-on
        - HY spread > 5% reinforces risk-off
        """
        if vix is None:
            return "neutral"
        if vix > 25:
            return "risk-off"
        if vix < 15:
            return "risk-on"
        # Borderline — use HY spread as tiebreaker
        if hy_spread is not None and hy_spread > 5.0:
            return "risk-off"
        return "neutral"

    @staticmethod
    def _derive_fed_stance(
        fed_rate: float | None,
        cpi: float | None,
        unemployment: float | None,
    ) -> str:
        """Derive Fed stance from rate level vs inflation and employment.

        - rate > CPI → hawkish (tightening)
        - rate < CPI → dovish (accommodative)
        - otherwise neutral
        """
        if fed_rate is None or cpi is None:
            return "neutral"
        if fed_rate > cpi:
            return "hawkish"
        if fed_rate < cpi:
            return "dovish"
        return "neutral"
