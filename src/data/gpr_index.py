"""GPR (Geopolitical Risk) Index fetcher.

The GPR index is constructed by counting articles from major newspapers
related to geopolitical tensions, threats, and acts. Published by Matteo
Iacoviello (Federal Reserve Board) — academically rigorous and free.

Data source: https://www.matteoiacoviello.com/gpr_files/
"""

from __future__ import annotations

import asyncio
import io
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.data.circuit_breaker import CircuitBreaker
from src.data.http_client import create_session
from src.utils.logger import get_logger

logger = get_logger("data.gpr_index")

__all__ = ["GprReading", "GprIndexFetcher"]

_CACHE_TTL = 86400  # 24 hours — daily data
_DATA_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls"


@dataclass
class GprReading:
    """A single GPR index reading."""

    date: str  # YYYY-MM-DD
    gpr_index: float  # overall geopolitical risk
    gpr_threat: float  # threat component (verbal threats, warnings)
    gpr_act: float  # actual event component (wars, terrorist acts)
    percentile: float  # where this reading falls historically (0-100)
    trend: str  # rising/falling/stable (vs 30-day MA)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "gpr": self.gpr_index,
            "threat": self.gpr_threat,
            "act": self.gpr_act,
            "percentile": self.percentile,
            "trend": self.trend,
        }


class GprIndexFetcher:
    """Fetch GPR index data from Iacoviello's website.

    Usage::

        fetcher = GprIndexFetcher()
        latest = await fetcher.fetch_latest()
        if latest and fetcher.is_elevated(latest):
            print("Geopolitical risk is elevated!")
    """

    def __init__(self) -> None:
        self._session = create_session(timeout=(10.0, 30.0), retries=2)
        self._cache: dict[str, tuple[float, Any]] = {}
        self._circuit = CircuitBreaker(
            "gpr_index", failure_threshold=3, recovery_timeout=3600.0
        )
        self._df: pd.DataFrame | None = None

    def _get_cache(self, key: str) -> Any | None:
        if key in self._cache:
            expire_ts, val = self._cache[key]
            if time.time() < expire_ts:
                return val
        return None

    def _set_cache(self, key: str, val: Any) -> None:
        self._cache[key] = (time.time() + _CACHE_TTL, val)

    def _download_data_sync(self) -> pd.DataFrame:
        """Download and parse the GPR daily data file."""
        if self._circuit.state == "open":
            return pd.DataFrame()

        try:
            resp = self._session.get(_DATA_URL)
            resp.raise_for_status()
            df = pd.read_excel(io.BytesIO(resp.content))

            # Known columns: date (datetime), GPRD (index), GPRD_ACT, GPRD_THREAT
            result = pd.DataFrame()

            if "date" in df.columns:
                result["date"] = pd.to_datetime(df["date"], errors="coerce")
            elif "DAY" in df.columns:
                result["date"] = pd.to_datetime(
                    df["DAY"].astype(str), format="%Y%m%d", errors="coerce"
                )
            else:
                logger.warning("GPR data: no date column found")
                return pd.DataFrame()

            gpr_col = "GPRD" if "GPRD" in df.columns else "gpr"
            result["gpr"] = pd.to_numeric(df.get(gpr_col, 0), errors="coerce")
            result["threat"] = pd.to_numeric(df.get("GPRD_THREAT", 0), errors="coerce")
            result["act"] = pd.to_numeric(df.get("GPRD_ACT", 0), errors="coerce")

            # Drop rows with NaT dates or NaN GPR (metadata rows at top)
            result = result.dropna(subset=["date", "gpr"]).sort_values("date")
            result = result[result["gpr"] > 0].reset_index(drop=True)

            self._circuit._on_success()
            self._df = result
            logger.info("GPR data downloaded: %d daily readings", len(result))
            return result

        except Exception as exc:
            logger.warning("GPR data download failed: %s", exc)
            self._circuit._on_failure()
            return pd.DataFrame()

    def _get_df(self) -> pd.DataFrame:
        """Get cached dataframe or download."""
        cached = self._get_cache("df")
        if cached is not None and not cached.empty:
            return cached

        df = self._download_data_sync()
        if not df.empty:
            self._set_cache("df", df)
        return df

    def _compute_percentile(self, value: float, series: pd.Series) -> float:
        """Compute where a value falls in the historical distribution."""
        if series.empty:
            return 50.0
        return float((series < value).sum() / len(series) * 100)

    def _compute_trend(self, df: pd.DataFrame, ma_window: int = 30) -> str:
        """Compute trend vs moving average."""
        if len(df) < ma_window + 1:
            return "stable"
        ma = df["gpr"].iloc[-ma_window:].mean()
        latest = df["gpr"].iloc[-1]
        delta_pct = (latest - ma) / ma * 100 if ma > 0 else 0
        if delta_pct > 10:
            return "rising"
        elif delta_pct < -10:
            return "falling"
        return "stable"

    def fetch_latest_sync(self) -> GprReading | None:
        """Fetch the most recent GPR reading."""
        df = self._get_df()
        if df.empty:
            return None

        row = df.iloc[-1]
        percentile = self._compute_percentile(row["gpr"], df["gpr"])
        trend = self._compute_trend(df)

        return GprReading(
            date=row["date"].strftime("%Y-%m-%d"),
            gpr_index=round(float(row["gpr"]), 2),
            gpr_threat=round(float(row.get("threat", 0)), 2),
            gpr_act=round(float(row.get("act", 0)), 2),
            percentile=round(percentile, 1),
            trend=trend,
        )

    def fetch_history_sync(self, days: int = 90) -> list[GprReading]:
        """Fetch historical GPR readings."""
        df = self._get_df()
        if df.empty:
            return []

        recent = df.tail(days)
        results = []
        for _, row in recent.iterrows():
            pct = self._compute_percentile(row["gpr"], df["gpr"])
            results.append(
                GprReading(
                    date=row["date"].strftime("%Y-%m-%d"),
                    gpr_index=round(float(row["gpr"]), 2),
                    gpr_threat=round(float(row.get("threat", 0)), 2),
                    gpr_act=round(float(row.get("act", 0)), 2),
                    percentile=round(pct, 1),
                    trend="stable",
                )
            )
        return results

    @staticmethod
    def is_elevated(reading: GprReading) -> bool:
        """Check if risk is elevated (above 80th percentile)."""
        return reading.percentile > 80.0

    async def fetch_latest(self) -> GprReading | None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.fetch_latest_sync)

    async def fetch_history(self, days: int = 90) -> list[GprReading]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.fetch_history_sync, days)
