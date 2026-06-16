"""Black Swan Detector — identifies extreme market anomalies requiring immediate action.

Per PRD v34.0 FR-GI003: Multi-indicator joint anomaly detection.

Monitors global market data for abnormal moves and publishes S10_BLACK_SWAN
signals when multiple thresholds are breached simultaneously.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.utils.config import load_config

logger = logging.getLogger(__name__)

# Default thresholds per PRD v34.0
DEFAULT_THRESHOLDS = {
    "vix": {"extreme": 30.0, "elevated": 25.0},
    "index_drop_pct": {"extreme": -3.0, "elevated": -2.0},
    "usd_index_pct": {"extreme": 1.5, "elevated": 1.0},
    "oil_pct": {"extreme": 5.0, "elevated": 3.0},
    "gold_pct": {"extreme": 3.0, "elevated": 2.0},
    "northbound_outflow_yi": {"extreme": -100.0, "elevated": -50.0},
    "limit_down_ratio": {"extreme": 3.0},  # limit_down > limit_up * ratio
}

# How many ELEVATED signals needed to escalate to EXTREME
MULTI_INDICATOR_ESCALATION = 3


@dataclass
class BlackSwanAlert:
    """A detected black swan or extreme market event."""

    alert_id: str
    level: str  # "EXTREME" | "ELEVATED"
    timestamp: datetime
    triggered_indicators: list[IndicatorBreach]
    summary: str
    recommended_action: str
    is_multi_indicator: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "level": self.level,
            "timestamp": self.timestamp.isoformat(),
            "triggered_indicators": [i.to_dict() for i in self.triggered_indicators],
            "summary": self.summary,
            "recommended_action": self.recommended_action,
            "is_multi_indicator": self.is_multi_indicator,
        }


@dataclass
class IndicatorBreach:
    """A single indicator that breached its threshold."""

    indicator: str  # e.g. "vix", "oil_pct"
    display_name: str
    current_value: float
    threshold: float
    level: str  # "EXTREME" | "ELEVATED"
    direction: str  # "above" | "below"

    def to_dict(self) -> dict[str, Any]:
        return {
            "indicator": self.indicator,
            "display_name": self.display_name,
            "current_value": self.current_value,
            "threshold": self.threshold,
            "level": self.level,
            "direction": self.direction,
        }


class BlackSwanDetector:
    """Detects extreme market events from global market data.

    Uses multi-indicator analysis: individual extreme thresholds plus
    escalation when >= N elevated indicators fire simultaneously.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or self._load_config()
        self._thresholds = self._config.get("thresholds", DEFAULT_THRESHOLDS)
        self._escalation_count = self._config.get(
            "multi_indicator_escalation", MULTI_INDICATOR_ESCALATION
        )
        self._cooldown_seconds = self._config.get("cooldown_seconds", 1800)
        self._cooldown_cache: dict[str, float] = {}
        logger.info("BlackSwanDetector initialized")

    @staticmethod
    def _load_config() -> dict[str, Any]:
        try:
            return load_config("black_swan")
        except FileNotFoundError:
            return {}

    def _is_cooled_down(self, key: str) -> bool:
        last = self._cooldown_cache.get(key)
        if last is None:
            return True
        return (time.monotonic() - last) >= self._cooldown_seconds

    def _set_cooldown(self, key: str) -> None:
        self._cooldown_cache[key] = time.monotonic()

    def scan(self, market_data: dict[str, Any]) -> list[BlackSwanAlert]:
        """Scan market data for black swan events.

        Args:
            market_data: Dict with keys like:
                - vix: float (VIX level)
                - index_changes: dict[str, float] (index name -> pct change)
                - usd_index_pct: float (DXY daily change %)
                - oil_pct: float (oil daily change %)
                - gold_pct: float (gold daily change %)
                - northbound_flow_yi: float (northbound net flow in 亿)
                - limit_up_count: int
                - limit_down_count: int

        Returns:
            List of BlackSwanAlert, empty if no anomalies.
        """
        breaches: list[IndicatorBreach] = []

        # 1. VIX check
        vix = market_data.get("vix")
        if vix is not None:
            vix_cfg = self._thresholds.get("vix", {})
            if vix >= vix_cfg.get("extreme", 30.0):
                breaches.append(
                    IndicatorBreach(
                        indicator="vix",
                        display_name="VIX恐慌指数",
                        current_value=vix,
                        threshold=vix_cfg["extreme"],
                        level="EXTREME",
                        direction="above",
                    )
                )
            elif vix >= vix_cfg.get("elevated", 25.0):
                breaches.append(
                    IndicatorBreach(
                        indicator="vix",
                        display_name="VIX恐慌指数",
                        current_value=vix,
                        threshold=vix_cfg["elevated"],
                        level="ELEVATED",
                        direction="above",
                    )
                )

        # 2. Index drops
        idx_cfg = self._thresholds.get("index_drop_pct", {})
        for idx_name, pct in market_data.get("index_changes", {}).items():
            if pct <= idx_cfg.get("extreme", -3.0):
                breaches.append(
                    IndicatorBreach(
                        indicator=f"index:{idx_name}",
                        display_name=f"{idx_name}暴跌",
                        current_value=pct,
                        threshold=idx_cfg["extreme"],
                        level="EXTREME",
                        direction="below",
                    )
                )
            elif pct <= idx_cfg.get("elevated", -2.0):
                breaches.append(
                    IndicatorBreach(
                        indicator=f"index:{idx_name}",
                        display_name=f"{idx_name}大跌",
                        current_value=pct,
                        threshold=idx_cfg["elevated"],
                        level="ELEVATED",
                        direction="below",
                    )
                )

        # 3. USD index
        usd_pct = market_data.get("usd_index_pct")
        if usd_pct is not None:
            usd_cfg = self._thresholds.get("usd_index_pct", {})
            if abs(usd_pct) >= usd_cfg.get("extreme", 1.5):
                direction = "走强" if usd_pct > 0 else "走弱"
                breaches.append(
                    IndicatorBreach(
                        indicator="usd_index",
                        display_name=f"美元指数{direction}",
                        current_value=usd_pct,
                        threshold=usd_cfg["extreme"],
                        level="ELEVATED",
                        direction="above" if usd_pct > 0 else "below",
                    )
                )
            elif abs(usd_pct) >= usd_cfg.get("elevated", 1.0):
                direction = "走强" if usd_pct > 0 else "走弱"
                breaches.append(
                    IndicatorBreach(
                        indicator="usd_index",
                        display_name=f"美元指数{direction}",
                        current_value=usd_pct,
                        threshold=usd_cfg["elevated"],
                        level="ELEVATED",
                        direction="above" if usd_pct > 0 else "below",
                    )
                )

        # 4. Oil
        oil_pct = market_data.get("oil_pct")
        if oil_pct is not None:
            oil_cfg = self._thresholds.get("oil_pct", {})
            if abs(oil_pct) >= oil_cfg.get("extreme", 5.0):
                breaches.append(
                    IndicatorBreach(
                        indicator="oil",
                        display_name="原油异动",
                        current_value=oil_pct,
                        threshold=oil_cfg["extreme"],
                        level="EXTREME",
                        direction="above" if oil_pct > 0 else "below",
                    )
                )
            elif abs(oil_pct) >= oil_cfg.get("elevated", 3.0):
                breaches.append(
                    IndicatorBreach(
                        indicator="oil",
                        display_name="原油波动",
                        current_value=oil_pct,
                        threshold=oil_cfg["elevated"],
                        level="ELEVATED",
                        direction="above" if oil_pct > 0 else "below",
                    )
                )

        # 5. Gold
        gold_pct = market_data.get("gold_pct")
        if gold_pct is not None:
            gold_cfg = self._thresholds.get("gold_pct", {})
            if abs(gold_pct) >= gold_cfg.get("extreme", 3.0):
                breaches.append(
                    IndicatorBreach(
                        indicator="gold",
                        display_name="黄金异动",
                        current_value=gold_pct,
                        threshold=gold_cfg["extreme"],
                        level="EXTREME",
                        direction="above" if gold_pct > 0 else "below",
                    )
                )
            elif abs(gold_pct) >= gold_cfg.get("elevated", 2.0):
                breaches.append(
                    IndicatorBreach(
                        indicator="gold",
                        display_name="黄金波动",
                        current_value=gold_pct,
                        threshold=gold_cfg["elevated"],
                        level="ELEVATED",
                        direction="above" if gold_pct > 0 else "below",
                    )
                )

        # 6. Northbound (southward) capital flow
        nb_flow = market_data.get("northbound_flow_yi")
        if nb_flow is not None:
            nb_cfg = self._thresholds.get("northbound_outflow_yi", {})
            if nb_flow <= nb_cfg.get("extreme", -100.0):
                breaches.append(
                    IndicatorBreach(
                        indicator="northbound",
                        display_name="北向资金大幅流出",
                        current_value=nb_flow,
                        threshold=nb_cfg["extreme"],
                        level="EXTREME",
                        direction="below",
                    )
                )
            elif nb_flow <= nb_cfg.get("elevated", -50.0):
                breaches.append(
                    IndicatorBreach(
                        indicator="northbound",
                        display_name="北向资金流出",
                        current_value=nb_flow,
                        threshold=nb_cfg["elevated"],
                        level="ELEVATED",
                        direction="below",
                    )
                )

        # 7. Limit down ratio
        ld = market_data.get("limit_down_count", 0)
        lu = market_data.get("limit_up_count", 1)
        if lu > 0 and ld > 0:
            ld_cfg = self._thresholds.get("limit_down_ratio", {})
            ratio = ld / lu
            if ratio >= ld_cfg.get("extreme", 3.0):
                breaches.append(
                    IndicatorBreach(
                        indicator="limit_down_ratio",
                        display_name="跌停/涨停比异常",
                        current_value=ratio,
                        threshold=ld_cfg["extreme"],
                        level="EXTREME",
                        direction="above",
                    )
                )

        if not breaches:
            return []

        return self._build_alerts(breaches)

    def _build_alerts(self, breaches: list[IndicatorBreach]) -> list[BlackSwanAlert]:
        """Build alert objects from breaches, applying multi-indicator escalation."""
        alerts: list[BlackSwanAlert] = []

        extreme_breaches = [b for b in breaches if b.level == "EXTREME"]
        elevated_breaches = [b for b in breaches if b.level == "ELEVATED"]

        # Individual EXTREME alerts
        if extreme_breaches:
            cooldown_key = "extreme:" + ",".join(
                sorted(b.indicator for b in extreme_breaches)
            )
            if self._is_cooled_down(cooldown_key):
                indicators_text = "、".join(b.display_name for b in extreme_breaches)
                alert = BlackSwanAlert(
                    alert_id=str(uuid.uuid4()),
                    level="EXTREME",
                    timestamp=datetime.now(UTC),
                    triggered_indicators=extreme_breaches,
                    summary=f"极端市场事件: {indicators_text}",
                    recommended_action="立即评估全部持仓风险，考虑减仓或对冲",
                )
                alerts.append(alert)
                self._set_cooldown(cooldown_key)

        # Multi-indicator escalation
        if len(elevated_breaches) >= self._escalation_count:
            cooldown_key = "multi_elevated"
            if self._is_cooled_down(cooldown_key):
                indicators_text = "、".join(b.display_name for b in elevated_breaches)
                alert = BlackSwanAlert(
                    alert_id=str(uuid.uuid4()),
                    level="EXTREME",
                    timestamp=datetime.now(UTC),
                    triggered_indicators=elevated_breaches,
                    summary=f"多指标联动异常({len(elevated_breaches)}项): {indicators_text}",
                    recommended_action="多个风险指标同时触发，建议减仓观望，等待市场企稳",
                    is_multi_indicator=True,
                )
                alerts.append(alert)
                self._set_cooldown(cooldown_key)
        elif elevated_breaches and not extreme_breaches:
            # Single ELEVATED — just log, don't alert
            indicators_text = "、".join(b.display_name for b in elevated_breaches)
            logger.info(
                "Elevated indicators (below escalation threshold): %s", indicators_text
            )

        return alerts

    def build_scan_input_from_snapshot(
        self, snapshot: dict[str, Any]
    ) -> dict[str, Any]:
        """Convert a GlobalMarketFetcher snapshot to scan() input format.

        Helper to bridge between GlobalMarketFetcher.fetch_global_snapshot()
        and this detector's scan() method.
        """
        result: dict[str, Any] = {}

        # VIX
        for item in snapshot.get("volatility", []):
            if "VIX" in item.get("symbol", ""):
                result["vix"] = item.get("price")

        # Commodities
        for item in snapshot.get("commodities", []):
            sym = item.get("symbol", "")
            pct = item.get("pct_change")
            if "GC=F" in sym:
                result["gold_pct"] = pct
            elif "CL=F" in sym:
                result["oil_pct"] = pct

        # Currencies — DXY
        for item in snapshot.get("currencies", []):
            sym = item.get("symbol", "")
            if "DX-Y" in sym:
                result["usd_index_pct"] = item.get("pct_change")

        # Index changes
        index_changes = {}
        for item in snapshot.get("indices", []):
            name = item.get("name", item.get("symbol", ""))
            pct = item.get("pct_change")
            if pct is not None:
                index_changes[name] = pct
        if index_changes:
            result["index_changes"] = index_changes

        return result
