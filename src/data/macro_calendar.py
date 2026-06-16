"""Macro economic calendar data fetcher.

Provides latest economic indicator releases (CPI, PMI, GDP, LPR, PPI)
with actual vs. forecast comparison for surprise detection.

Data sources: AKShare (macro_china_*, macro_usa_*).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.data.circuit_breaker import CircuitBreaker
from src.utils.logger import get_logger

logger = get_logger("data.macro_calendar")


@dataclass
class MacroRelease:
    """A single macro economic data release."""

    indicator: str
    country: str
    date: str
    actual: float | None
    forecast: float | None
    previous: float | None
    surprise: float | None  # actual - forecast
    importance: str  # "high" | "medium" | "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "indicator": self.indicator,
            "country": self.country,
            "date": self.date,
            "actual": self.actual,
            "forecast": self.forecast,
            "previous": self.previous,
            "surprise": self.surprise,
            "importance": self.importance,
        }


# Indicator configs: (akshare_func, indicator_name, country, importance)
_CHINA_INDICATORS = [
    ("macro_china_cpi_yearly", "CPI年率", "CN", "high"),
    ("macro_china_ppi_yearly", "PPI年率", "CN", "medium"),
    ("macro_china_gdp_yearly", "GDP年率", "CN", "high"),
    ("macro_china_pmi_yearly", "PMI", "CN", "high"),
    ("macro_china_non_man_pmi", "非制造业PMI", "CN", "medium"),
]

_USA_INDICATORS = [
    ("macro_usa_cpi_yoy", "CPI同比", "US", "high"),
    ("macro_usa_core_pce_price", "核心PCE", "US", "high"),
    ("macro_usa_adp_employment", "ADP就业", "US", "medium"),
]


class MacroCalendarFetcher:
    """Fetch latest macro economic releases with surprise detection."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, list[MacroRelease]]] = {}
        self._cache_ttl: float = 3600.0  # 1 hour — macro data is slow-moving
        self._circuit = CircuitBreaker(
            "akshare_macro", failure_threshold=3, recovery_timeout=300.0
        )
        logger.info("MacroCalendarFetcher initialized")

    def _get_cached(self, key: str) -> list[MacroRelease] | None:
        if key in self._cache:
            ts, data = self._cache[key]
            if time.monotonic() - ts < self._cache_ttl:
                return data
        return None

    def _fetch_indicator(
        self,
        func_name: str,
        indicator_name: str,
        country: str,
        importance: str,
        n_latest: int = 3,
    ) -> list[MacroRelease]:
        """Fetch latest N releases for one indicator."""
        try:
            import akshare as ak

            func = getattr(ak, func_name, None)
            if func is None:
                logger.warning("AKShare function %s not found", func_name)
                return []

            df = func()
            if df is None or df.empty:
                return []

            releases: list[MacroRelease] = []

            # Handle two formats:
            # Format A: 商品/日期/今值/预测值/前值 (CPI, GDP, PPI yearly)
            if "今值" in df.columns and "日期" in df.columns:
                df = df.sort_values("日期", ascending=False).head(n_latest)
                for _, row in df.iterrows():
                    actual = _safe_float(row.get("今值"))
                    forecast = _safe_float(row.get("预测值"))
                    previous = _safe_float(row.get("前值"))
                    surprise = (
                        round(actual - forecast, 2)
                        if actual is not None and forecast is not None
                        else None
                    )
                    releases.append(
                        MacroRelease(
                            indicator=indicator_name,
                            country=country,
                            date=str(row["日期"])[:10],
                            actual=actual,
                            forecast=forecast,
                            previous=previous,
                            surprise=surprise,
                            importance=importance,
                        )
                    )

            # Format B: 月份/指数 columns (PMI)
            elif "月份" in df.columns:
                df = df.head(n_latest)
                index_col = [
                    c for c in df.columns if "指数" in c and "同比" not in c
                ]
                if index_col:
                    for _, row in df.iterrows():
                        actual = _safe_float(row.get(index_col[0]))
                        releases.append(
                            MacroRelease(
                                indicator=indicator_name,
                                country=country,
                                date=str(row["月份"]),
                                actual=actual,
                                forecast=None,
                                previous=None,
                                surprise=None,
                                importance=importance,
                            )
                        )

            return releases

        except Exception as e:
            logger.warning("Failed to fetch %s: %s", func_name, e)
            return []

    def fetch_china_calendar(self, n_latest: int = 3) -> list[MacroRelease]:
        """Fetch latest Chinese macro releases."""
        cached = self._get_cached("china")
        if cached is not None:
            return cached

        if self._circuit.state == "open":
            logger.debug("macro_calendar circuit breaker open — skipping")
            return []

        releases: list[MacroRelease] = []
        for func_name, name, country, importance in _CHINA_INDICATORS:
            try:
                items = self._fetch_indicator(
                    func_name, name, country, importance, n_latest
                )
                releases.extend(items)
            except Exception as e:
                logger.warning("Failed %s: %s", func_name, e)
                self._circuit._on_failure()

        if releases:
            self._circuit._on_success()

        self._cache["china"] = (time.monotonic(), releases)
        return releases

    def fetch_us_calendar(self, n_latest: int = 3) -> list[MacroRelease]:
        """Fetch latest US macro releases."""
        cached = self._get_cached("us")
        if cached is not None:
            return cached

        if self._circuit.state == "open":
            return []

        releases: list[MacroRelease] = []
        for func_name, name, country, importance in _USA_INDICATORS:
            try:
                items = self._fetch_indicator(
                    func_name, name, country, importance, n_latest
                )
                releases.extend(items)
            except Exception as e:
                logger.warning("Failed %s: %s", func_name, e)
                self._circuit._on_failure()

        if releases:
            self._circuit._on_success()

        self._cache["us"] = (time.monotonic(), releases)
        return releases

    def fetch_all(self, n_latest: int = 3) -> dict[str, Any]:
        """Fetch all macro calendar data."""
        china = self.fetch_china_calendar(n_latest)
        us = self.fetch_us_calendar(n_latest)

        # Find surprises (actual significantly different from forecast)
        surprises = [
            r
            for r in china + us
            if r.surprise is not None and abs(r.surprise) > 0.1
        ]
        surprises.sort(key=lambda r: abs(r.surprise or 0), reverse=True)

        return {
            "china": [r.to_dict() for r in china],
            "us": [r.to_dict() for r in us],
            "surprises": [r.to_dict() for r in surprises[:5]],
            "total_releases": len(china) + len(us),
        }

    def fetch_lpr(self) -> list[dict[str, Any]]:
        """Fetch latest LPR (Loan Prime Rate) decisions."""
        cached = self._get_cached("lpr")
        if cached is not None:
            return [r.to_dict() for r in cached]

        try:
            import akshare as ak

            df = ak.macro_china_lpr()
            if df is None or df.empty:
                return []

            df = df.sort_values("TRADE_DATE", ascending=False).head(6)
            releases: list[MacroRelease] = []
            for _, row in df.iterrows():
                lpr1y = _safe_float(row.get("LPR1Y"))
                lpr5y = _safe_float(row.get("LPR5Y"))
                if lpr1y is not None:
                    releases.append(
                        MacroRelease(
                            indicator="LPR 1Y",
                            country="CN",
                            date=str(row["TRADE_DATE"])[:10],
                            actual=lpr1y,
                            forecast=None,
                            previous=None,
                            surprise=None,
                            importance="high",
                        )
                    )
                if lpr5y is not None:
                    releases.append(
                        MacroRelease(
                            indicator="LPR 5Y",
                            country="CN",
                            date=str(row["TRADE_DATE"])[:10],
                            actual=lpr5y,
                            forecast=None,
                            previous=None,
                            surprise=None,
                            importance="high",
                        )
                    )

            self._cache["lpr"] = (time.monotonic(), releases)
            return [r.to_dict() for r in releases]

        except Exception as e:
            logger.warning("Failed to fetch LPR: %s", e)
            return []


def _safe_float(val: Any) -> float | None:
    """Convert value to float, returning None for NaN/None/invalid."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if pd.isna(f) else round(f, 2)
    except (ValueError, TypeError):
        return None
