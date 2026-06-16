"""Capital flow anomaly detector.

Detects statistically significant deviations in macro and sector flows.

Per PRD v26.0 FR-CF009.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("analysis.flow_anomaly")


@dataclass
class FlowAnomalyEvent:
    event_type: str  # "macro_surge" | "sector_anomaly" | "stock_divergence"
    title: str
    summary: str
    severity: str  # "high" | "medium" | "low"
    related_symbols: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    detected_at: str = field(default_factory=lambda: datetime.now().isoformat())


class FlowAnomalyDetector:
    def __init__(self) -> None:
        try:
            cfg = load_config("capital_flow")
        except Exception:
            cfg = {}
        cf_cfg = cfg.get("capital_flow", {})
        self._nb_threshold = cf_cfg.get("notification", {}).get(
            "northbound_threshold", 80
        )
        self._std_threshold = cf_cfg.get("sector", {}).get("anomaly_std_threshold", 2.0)

    def detect_macro_anomalies(
        self,
        northbound_net: float,
        northbound_history: list[float],
    ) -> list[FlowAnomalyEvent]:
        """Detect macro-level capital flow anomalies.

        Args:
            northbound_net: Today's northbound net buy (亿元).
            northbound_history: Recent 30-day history of daily northbound net buy.

        Returns:
            List of anomaly events.
        """
        events: list[FlowAnomalyEvent] = []

        # Absolute threshold check
        if abs(northbound_net) >= self._nb_threshold:
            direction = "净买入" if northbound_net > 0 else "净卖出"
            events.append(
                FlowAnomalyEvent(
                    event_type="macro_surge",
                    title=f"北向资金大幅{direction}",
                    summary=(
                        f"北向资金单日{direction}{abs(northbound_net):.1f}亿元，"
                        f"超过{self._nb_threshold}亿阈值"
                    ),
                    severity="high",
                    data={
                        "northbound_net": northbound_net,
                        "threshold": self._nb_threshold,
                    },
                )
            )

        # Statistical anomaly check
        if len(northbound_history) >= 10:
            # Convert to native float — numpy float64 breaks statistics.stdev on Py3.13
            nb_native = [float(x) for x in northbound_history]
            mean = statistics.mean(nb_native)
            std = statistics.stdev(nb_native)
            if std > 0:
                z_score = (northbound_net - mean) / std
                if abs(z_score) >= self._std_threshold:
                    direction = "流入" if northbound_net > mean else "流出"
                    events.append(
                        FlowAnomalyEvent(
                            event_type="macro_surge",
                            title="北向资金统计异动",
                            summary=(
                                f"北向资金偏离均值{z_score:.1f}倍标准差，"
                                f"显著{direction}异常"
                            ),
                            severity="high" if abs(z_score) >= 3.0 else "medium",
                            data={
                                "z_score": round(z_score, 2),
                                "mean": round(mean, 2),
                                "std": round(std, 2),
                            },
                        )
                    )

        return events

    def detect_sector_anomalies(
        self,
        sector_flows: dict[str, float],
        sector_history: dict[str, list[float]],
    ) -> list[FlowAnomalyEvent]:
        """Detect sector-level capital flow anomalies.

        Args:
            sector_flows: {sector_name: today_net_inflow} in 亿元.
            sector_history: {sector_name: [daily_net_inflow...]} recent 30 days.

        Returns:
            List of anomaly events.
        """
        events: list[FlowAnomalyEvent] = []

        for name, today_flow in sector_flows.items():
            history = sector_history.get(name, [])
            if len(history) < 10:
                continue

            # Convert to native float — numpy float64 breaks statistics.stdev on Py3.13
            history_native = [float(x) for x in history]
            mean = statistics.mean(history_native)
            std = statistics.stdev(history_native)
            if std <= 0:
                continue

            z_score = (today_flow - mean) / std
            if abs(z_score) >= self._std_threshold:
                direction = "涌入" if today_flow > mean else "流出"
                events.append(
                    FlowAnomalyEvent(
                        event_type="sector_anomaly",
                        title=f"{name}板块资金异常{direction}",
                        summary=(
                            f"{name}板块净{'流入' if today_flow > 0 else '流出'}"
                            f"{abs(today_flow):.1f}亿元，"
                            f"偏离均值{z_score:.1f}倍标准差"
                        ),
                        severity="high" if abs(z_score) >= 3.0 else "medium",
                        data={
                            "sector": name,
                            "flow": round(today_flow, 2),
                            "z_score": round(z_score, 2),
                        },
                    )
                )

        # Sort by z-score magnitude
        events.sort(key=lambda e: abs(e.data.get("z_score", 0)), reverse=True)
        return events
