"""Macro Data Pulse Agent — Sentinel Team member for macro data monitoring.

Monitors global macro data releases and detects data surprises.
Enhances the existing MacroCalendar with real-time release detection.

Per PRD v39.0 FR-GIT004.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from functools import lru_cache

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("intelligence.agents.macro_pulse")


@dataclass
class MacroDataPoint:
    """A macro economic data release."""

    indicator: str  # e.g. "cn_pmi", "us_cpi"
    name: str  # e.g. "中国PMI", "US CPI"
    region: str  # "CN" | "US" | "EU"
    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None
    surprise: float | None = None  # actual - forecast (std devs)
    released_at: str = ""
    is_surprise: bool = False  # |surprise| > threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "indicator": self.indicator,
            "name": self.name,
            "region": self.region,
            "actual": self.actual,
            "forecast": self.forecast,
            "previous": self.previous,
            "surprise": self.surprise,
            "released_at": self.released_at,
            "is_surprise": self.is_surprise,
        }


@dataclass
class YieldCurveSnapshot:
    """US Treasury yield curve snapshot."""

    us_10y: float | None = None
    us_2y: float | None = None
    spread: float | None = None  # 10Y - 2Y
    is_inverted: bool = False
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "us_10y": self.us_10y,
            "us_2y": self.us_2y,
            "spread": self.spread,
            "is_inverted": self.is_inverted,
            "timestamp": self.timestamp,
        }


@dataclass
class MacroPulseResult:
    """Result of a macro pulse check."""

    data_releases: list[MacroDataPoint] = field(default_factory=list)
    surprises: list[MacroDataPoint] = field(default_factory=list)
    yield_curve: YieldCurveSnapshot | None = None
    alerts: list[dict[str, Any]] = field(default_factory=list)


# China macro indicators via AKShare
_CN_INDICATORS: dict[str, dict[str, Any]] = {
    "cn_pmi": {
        "name": "中国制造业PMI",
        "func": "macro_china_pmi_yearly",
        "region": "CN",
        "surprise_threshold": 1.0,
    },
    "cn_cpi": {
        "name": "中国CPI",
        "func": "macro_china_cpi_yearly",
        "region": "CN",
        "surprise_threshold": 0.3,
    },
}


class MacroPulseAgent:
    """Sentinel team: macro data release monitoring and surprise detection.

    Monitors key macro indicators for data releases and generates
    alerts when actual values significantly deviate from forecasts.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or self._load_config()
        self._surprise_threshold = self._config.get("analyst", {}).get(
            "surprise_threshold",
            1.0,
        )
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl = 300  # 5 min
        logger.info("MacroPulseAgent initialized")

    @staticmethod
    def _load_config() -> dict[str, Any]:
        try:
            return load_config("global_intelligence")
        except FileNotFoundError:
            return {}

    def _get_cached(self, key: str) -> Any | None:
        if key in self._cache:
            ts, val = self._cache[key]
            if time.monotonic() - ts < self._cache_ttl:
                return val
        return None

    def _set_cached(self, key: str, val: Any) -> None:
        self._cache[key] = (time.monotonic(), val)

    def check_releases(self) -> MacroPulseResult:
        """Check for recent macro data releases and detect surprises.

        Returns:
            MacroPulseResult with releases, surprises, and yield curve.
        """
        result = MacroPulseResult()

        # Check China PMI/CPI (via AKShare)
        for indicator_id, indicator_cfg in _CN_INDICATORS.items():
            try:
                data_point = self._fetch_cn_indicator(indicator_id, indicator_cfg)
                if data_point:
                    result.data_releases.append(data_point)
                    if data_point.is_surprise:
                        result.surprises.append(data_point)
                        result.alerts.append(
                            {
                                "type": "macro_surprise",
                                "indicator": indicator_id,
                                "name": data_point.name,
                                "actual": data_point.actual,
                                "forecast": data_point.forecast,
                                "surprise": data_point.surprise,
                                "title": (
                                    f"{data_point.name}数据"
                                    f"{'超预期' if data_point.surprise and data_point.surprise > 0 else '不及预期'}"
                                ),
                                "severity": (
                                    "high"
                                    if abs(data_point.surprise or 0) > 2
                                    else "normal"
                                ),
                            }
                        )
            except Exception as exc:
                logger.warning("Failed to check %s: %s", indicator_id, exc)

        # Check yield curve
        try:
            yc = self._fetch_yield_curve()
            if yc:
                result.yield_curve = yc
                if yc.is_inverted:
                    result.alerts.append(
                        {
                            "type": "yield_curve_inversion",
                            "title": "美债收益率曲线倒挂",
                            "spread": yc.spread,
                            "severity": "high",
                        }
                    )
        except Exception as exc:
            logger.warning("Failed to check yield curve: %s", exc)

        logger.info(
            "Macro pulse: %d releases, %d surprises, %d alerts",
            len(result.data_releases),
            len(result.surprises),
            len(result.alerts),
        )
        return result

    def _fetch_cn_indicator(
        self,
        indicator_id: str,
        cfg: dict,
    ) -> MacroDataPoint | None:
        """Fetch latest value for a China macro indicator."""
        cached = self._get_cached(f"cn_{indicator_id}")
        if cached is not None:
            return cached

        try:
            import akshare as ak

            func_name = cfg.get("func", "")
            if not func_name or not hasattr(ak, func_name):
                return None

            func = getattr(ak, func_name)
            df = func()
            if df is None or df.empty:
                return None

            # Get latest row
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else None

            # Try to extract actual value (column names vary by indicator)
            actual = None
            for col in df.columns:
                if (
                    "今值" in str(col)
                    or "当月" in str(col)
                    or "value" in str(col).lower()
                ):
                    try:
                        actual = float(latest[col])
                    except (ValueError, TypeError):
                        pass
                    break

            if actual is None:
                # Try numeric columns
                numeric_cols = df.select_dtypes(
                    include=["float64", "int64"],
                ).columns
                if len(numeric_cols) > 0:
                    try:
                        actual = float(latest[numeric_cols[-1]])
                    except (ValueError, TypeError):
                        return None

            previous = None
            if prev is not None:
                for col in df.columns:
                    if "前值" in str(col) or "上月" in str(col):
                        try:
                            previous = float(prev[col])
                        except (ValueError, TypeError):
                            pass
                        break

            # Simple surprise detection (actual vs previous as proxy for forecast)
            surprise = None
            is_surprise = False
            if actual is not None and previous is not None and previous != 0:
                surprise = actual - previous
                threshold = cfg.get("surprise_threshold", 1.0)
                is_surprise = abs(surprise) > threshold

            data_point = MacroDataPoint(
                indicator=indicator_id,
                name=cfg.get("name", indicator_id),
                region=cfg.get("region", "CN"),
                actual=actual,
                previous=previous,
                surprise=round(surprise, 4) if surprise is not None else None,
                released_at=datetime.now(UTC).isoformat(),
                is_surprise=is_surprise,
            )

            self._set_cached(f"cn_{indicator_id}", data_point)
            return data_point

        except Exception as exc:
            logger.warning("Failed to fetch CN indicator %s: %s", indicator_id, exc)
            return None

    def _fetch_yield_curve(self) -> YieldCurveSnapshot | None:
        """Fetch US Treasury yield curve via GlobalMarketFetcher."""
        cached = self._get_cached("yield_curve")
        if cached is not None:
            return cached

        try:
            from src.data.global_market import GlobalMarketFetcher

            fetcher = GlobalMarketFetcher()
            yields = fetcher.fetch_bond_yields()

            if not yields:
                return None

            us_10y = yields.get("US_10Y")
            us_2y = yields.get("US_2Y")
            spread = None
            is_inverted = False

            if us_10y is not None and us_2y is not None:
                spread = round(us_10y - us_2y, 4)
                is_inverted = spread < 0

            snapshot = YieldCurveSnapshot(
                us_10y=us_10y,
                us_2y=us_2y,
                spread=spread,
                is_inverted=is_inverted,
                timestamp=datetime.now(UTC).isoformat(),
            )

            self._set_cached("yield_curve", snapshot)
            return snapshot

        except Exception as exc:
            logger.warning("Yield curve fetch failed: %s", exc)
            return None


# ---------------------------------------------------------------------------
# DI singleton
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_macro_pulse_agent() -> MacroPulseAgent:
    return MacroPulseAgent(
        config=load_config("global_intelligence"),
    )
