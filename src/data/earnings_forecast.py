"""Earnings forecast (业绩预告) fetcher via EastMoney datacenter API.

Earnings forecasts are among the most market-moving events in A-shares.
Types: 预增(big increase), 预减(big decrease), 扭亏(turnaround),
首亏(first loss), 续亏(continued loss), 续盈(continued profit),
略增(slight increase), 略减(slight decrease).

Data source: datacenter-web.eastmoney.com (direct API).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from src.data.circuit_breaker import CircuitBreaker
from src.data.eastmoney_datacenter import EastMoneyDatacenter
from src.utils.logger import get_logger

logger = get_logger("data.earnings_forecast")

__all__ = ["EarningsForecast", "EarningsForecastFetcher"]

_CACHE_TTL = 3600  # 1 hour — forecasts released sporadically

# Positive vs negative forecast types
_POSITIVE_TYPES = {"预增", "扭亏", "续盈", "略增"}
_NEGATIVE_TYPES = {"预减", "首亏", "续亏", "略减"}
_SURPRISE_TYPES = {"预增", "扭亏", "首亏", "预减"}  # most market-moving


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        f = float(val)
        return default if f != f else f
    except (TypeError, ValueError):
        return default


@dataclass
class EarningsForecast:
    """A single earnings forecast record (业绩预告)."""

    symbol: str
    name: str
    report_period: str  # e.g., "2026-03-31" (Q1)
    forecast_type: str  # 预增|预减|扭亏|首亏|续亏|续盈|略增|略减
    forecast_pnl_lower_wan: float  # 预计净利润下限 (万元)
    forecast_pnl_upper_wan: float  # 预计净利润上限 (万元)
    yoy_change_lower_pct: float  # 同比变化下限 %
    yoy_change_upper_pct: float  # 同比变化上限 %
    reason: str  # company's explanation
    publish_date: str
    is_surprise: bool  # high market impact type

    @property
    def is_positive(self) -> bool:
        return self.forecast_type in _POSITIVE_TYPES

    @property
    def yoy_midpoint(self) -> float:
        return (self.yoy_change_lower_pct + self.yoy_change_upper_pct) / 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "period": self.report_period,
            "type": self.forecast_type,
            "pnl_lower_wan": self.forecast_pnl_lower_wan,
            "pnl_upper_wan": self.forecast_pnl_upper_wan,
            "yoy_lower": self.yoy_change_lower_pct,
            "yoy_upper": self.yoy_change_upper_pct,
            "yoy_mid": self.yoy_midpoint,
            "reason": self.reason,
            "date": self.publish_date,
            "surprise": self.is_surprise,
            "positive": self.is_positive,
        }


class EarningsForecastFetcher:
    """Fetch earnings forecast (业绩预告) data from EastMoney datacenter.

    Usage::

        fetcher = EarningsForecastFetcher()
        latest = await fetcher.fetch_latest_season()
        surprises = fetcher.detect_surprises_sync()
    """

    _REPORT_NAME = "RPT_PUBLIC_OP_NEWPREDICT"
    _SORT_COLUMN = "NOTICE_DATE"

    def __init__(self) -> None:
        self._dc = EastMoneyDatacenter()
        self._cache: dict[str, tuple[float, Any]] = {}
        self._circuit = CircuitBreaker(
            "earnings_forecast", failure_threshold=3, recovery_timeout=300.0
        )

    def _get_cache(self, key: str) -> Any | None:
        if key in self._cache:
            expire_ts, val = self._cache[key]
            if time.time() < expire_ts:
                return val
        return None

    def _set_cache(self, key: str, val: Any) -> None:
        self._cache[key] = (time.time() + _CACHE_TTL, val)

    def _parse_date(self, raw: Any) -> str:
        if not raw:
            return ""
        try:
            s = str(raw)
            if "T" in s:
                return s.split("T")[0]
            return s[:10]
        except (ValueError, TypeError):
            return ""

    def _parse_row(self, row: dict[str, Any]) -> EarningsForecast | None:
        symbol = str(row.get("SECURITY_CODE", ""))
        if not symbol or len(symbol) != 6:
            return None

        name = str(row.get("SECURITY_NAME_ABBR", ""))
        report_period = self._parse_date(row.get("REPORT_DATE"))
        publish_date = self._parse_date(row.get("NOTICE_DATE"))

        # PREDICT_TYPE has the Chinese text: 预增/预减/扭亏/首亏/续亏/续盈/略增/略减
        forecast_type = str(row.get("PREDICT_TYPE", ""))
        if not forecast_type or forecast_type == "None":
            forecast_type = str(row.get("PREDICT_FINANCE_CODE", ""))

        pnl_lower = _safe_float(
            row.get("PREDICT_AMT_LOWER", row.get("PREDICT_AMOUNT_LOWER"))
        )
        pnl_upper = _safe_float(
            row.get("PREDICT_AMT_UPPER", row.get("PREDICT_AMOUNT_UPPER"))
        )
        # Convert to 万 if needed
        if pnl_lower > 1_000_000 or pnl_lower < -1_000_000:
            pnl_lower = pnl_lower / 10_000
        if pnl_upper > 1_000_000 or pnl_upper < -1_000_000:
            pnl_upper = pnl_upper / 10_000

        yoy_lower = _safe_float(row.get("ADD_AMP_LOWER"))
        yoy_upper = _safe_float(row.get("ADD_AMP_UPPER"))

        reason = str(row.get("CHANGE_REASON_EXPLAIN", ""))
        is_surprise = forecast_type in _SURPRISE_TYPES

        return EarningsForecast(
            symbol=symbol,
            name=name,
            report_period=report_period,
            forecast_type=forecast_type,
            forecast_pnl_lower_wan=pnl_lower,
            forecast_pnl_upper_wan=pnl_upper,
            yoy_change_lower_pct=yoy_lower,
            yoy_change_upper_pct=yoy_upper,
            reason=reason,
            publish_date=publish_date,
            is_surprise=is_surprise,
        )

    def fetch_latest_season_sync(self) -> list[EarningsForecast]:
        """Fetch latest season's earnings forecasts."""
        cache_key = "latest_season"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        if self._circuit.state == "open":
            return []

        try:
            # Only fetch recent forecasts (last 90 days)
            from datetime import datetime, timedelta

            cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

            df = self._dc.query_all_pages(
                self._REPORT_NAME,
                max_pages=5,
                page_size=50,
                sort_columns=self._SORT_COLUMN,
                sort_types="-1",
                filter_str=f"(NOTICE_DATE>='{cutoff}')",
            )

            results: list[EarningsForecast] = []
            if not df.empty:
                for _, row in df.iterrows():
                    entry = self._parse_row(row.to_dict())
                    if entry:
                        results.append(entry)

            self._circuit._on_success()
            self._set_cache(cache_key, results)
            logger.info("Fetched %d earnings forecasts", len(results))
            return results

        except Exception as exc:
            logger.warning("Earnings forecast fetch failed: %s", exc)
            self._circuit._on_failure()
            return []

    def fetch_for_symbol_sync(self, symbol: str) -> list[EarningsForecast]:
        """Fetch earnings forecasts for a specific stock."""
        cache_key = f"symbol_{symbol}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        if self._circuit.state == "open":
            return []

        filter_str = f'(SECURITY_CODE="{symbol}")'

        try:
            df = self._dc.query(
                self._REPORT_NAME,
                page_size=20,
                sort_columns=self._SORT_COLUMN,
                sort_types="-1",
                filter_str=filter_str,
            )

            results: list[EarningsForecast] = []
            if not df.empty:
                for _, row in df.iterrows():
                    entry = self._parse_row(row.to_dict())
                    if entry:
                        results.append(entry)

            self._circuit._on_success()
            self._set_cache(cache_key, results)
            return results

        except Exception as exc:
            logger.warning("Earnings forecast for %s failed: %s", symbol, exc)
            self._circuit._on_failure()
            return []

    def detect_surprises_sync(self) -> list[EarningsForecast]:
        """Filter for surprise forecasts (most market-moving types).

        Returns forecasts of type: 预增, 扭亏, 首亏, 预减.
        """
        all_forecasts = self.fetch_latest_season_sync()
        return [f for f in all_forecasts if f.is_surprise]

    # -- Async wrappers -------------------------------------------------------

    async def fetch_latest_season(self) -> list[EarningsForecast]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.fetch_latest_season_sync)

    async def fetch_for_symbol(self, symbol: str) -> list[EarningsForecast]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.fetch_for_symbol_sync, symbol)

    async def detect_surprises(self) -> list[EarningsForecast]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.detect_surprises_sync)
