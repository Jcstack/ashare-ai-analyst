"""Capital flow service — aggregates macro/sector/stock capital flow data.

Per PRD v26.0 FR-CF003: DI singleton service for capital flow API.
Extended in v26.0 Phase 4 with anomaly scanning and notification push (FR-CF017).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from src.analysis.capital_flow_scorer import CapitalFlowScorer
from src.data.macro_flow_fetcher import MacroFlowFetcher
from src.data.sector_flow_fetcher import SectorFlowFetcher
from src.utils.logger import get_logger

logger = get_logger("web.services.capital_flow")

NOTIFICATIONS_KEY = "notifications:alerts"
MAX_NOTIFICATIONS = 200


class CapitalFlowService:
    """Aggregates all capital flow data and scoring."""

    def __init__(
        self,
        macro_fetcher: MacroFlowFetcher,
        scorer: CapitalFlowScorer,
        sector_fetcher: SectorFlowFetcher | None = None,
    ) -> None:
        self._macro_fetcher = macro_fetcher
        self._scorer = scorer
        self._sector_fetcher = sector_fetcher or SectorFlowFetcher()

    def get_macro_overview(self) -> dict:
        """Get today's macro capital flow overview with score.

        Returns:
            Dict matching MacroFlowOverview schema.
        """
        snapshot = self._macro_fetcher.get_latest_snapshot()
        self._scorer.score_and_update(snapshot)

        def _direction(v: float) -> str:
            if v > 0:
                return "up"
            elif v < 0:
                return "down"
            return "flat"

        def _f(v: float) -> float:
            """Ensure native Python float; replace NaN/Inf with 0."""
            import math

            fv = float(v)
            if math.isnan(fv) or math.isinf(fv):
                return 0.0
            return round(fv, 2)

        channels = [
            {
                "channel": "northbound",
                "value": _f(snapshot.northbound_net),
                "direction": _direction(snapshot.northbound_net),
            },
            {
                "channel": "southbound",
                "value": _f(snapshot.southbound_net),
                "direction": _direction(snapshot.southbound_net),
            },
            {
                "channel": "margin",
                "value": _f(snapshot.margin_balance_change),
                "direction": _direction(snapshot.margin_balance_change),
            },
            {
                "channel": "etf",
                "value": _f(snapshot.etf_net_flow),
                "direction": _direction(snapshot.etf_net_flow),
            },
        ]

        return {
            "date": snapshot.date,
            "environment_score": float(snapshot.environment_score),
            "signal": snapshot.signal,
            "northbound_net": _f(snapshot.northbound_net),
            "southbound_net": _f(snapshot.southbound_net),
            "margin_balance": _f(snapshot.margin_balance),
            "margin_balance_change": _f(snapshot.margin_balance_change),
            "etf_net_flow": _f(snapshot.etf_net_flow),
            "channels": channels,
            "interpretation": self._interpret_macro(snapshot),
            "warnings": snapshot.warnings,
            "updated_at": snapshot.updated_at,
        }

    def get_macro_history(self, days: int = 30) -> dict:
        """Get macro capital flow history with daily scores.

        Returns:
            Dict matching MacroFlowHistoryResponse schema.
        """
        snapshots = self._macro_fetcher.get_macro_history(days=days)
        history = self._macro_fetcher.get_macro_history(days=max(days, 30))

        items = []
        for s in snapshots:
            score, signal = self._scorer.score_snapshot(s, history=history)
            items.append(
                {
                    "date": s.date,
                    "environment_score": float(score),
                    "signal": signal,
                    "northbound_net": float(round(s.northbound_net, 2)),
                    "southbound_net": float(round(s.southbound_net, 2)),
                    "margin_balance_change": float(round(s.margin_balance_change, 2)),
                    "etf_net_flow": float(round(s.etf_net_flow, 2)),
                }
            )

        return {"days": days, "items": items}

    # ------------------------------------------------------------------
    # Sector-level capital flow (Phase 2)
    # ------------------------------------------------------------------

    def get_sector_ranking(
        self, sector_type: str = "industry", period: str = "today"
    ) -> dict:
        """Get sector capital flow ranking.

        Args:
            sector_type: "industry" for 申万一级 or "concept" for concept boards.
            period: One of "today", "3d", "5d", "10d".

        Returns:
            Dict matching SectorFlowResponse schema.
        """
        if sector_type == "concept":
            df = self._sector_fetcher.fetch_concept_flow(period=period)
        else:
            df = self._sector_fetcher.fetch_industry_flow(period=period)

        items = []
        if not df.empty:
            for _, row in df.iterrows():
                items.append(
                    {
                        "sector_name": str(row.get("sector_name", "")),
                        "sector_type": sector_type,
                        "change_pct": round(float(row.get("change_pct", 0) or 0), 2),
                        "net_inflow": round(float(row.get("net_inflow", 0) or 0), 2),
                        "main_net_inflow": round(
                            float(row.get("main_net_inflow", 0) or 0), 2
                        ),
                        "turnover": round(float(row.get("turnover", 0) or 0), 2),
                    }
                )

        return {
            "type": sector_type,
            "period": period,
            "items": items,
            "interpretation": self._interpret_sectors(items, sector_type),
        }

    def get_heatmap_data(self) -> dict:
        """Get sector flow heatmap data.

        Returns:
            Dict matching HeatmapResponse schema.
        """
        items = self._sector_fetcher.fetch_heatmap_data()
        return {
            "items": items,
            "updated_at": datetime.now().isoformat(),
        }

    # ------------------------------------------------------------------
    # Interpretation helpers (rule-based, no LLM)
    # ------------------------------------------------------------------

    @staticmethod
    def _interpret_macro(snapshot: Any) -> str:
        """Generate a 1-2 sentence Chinese interpretation of macro flow."""
        score = snapshot.environment_score
        nb = snapshot.northbound_net
        sb = snapshot.southbound_net
        mg = snapshot.margin_balance_change
        etf = snapshot.etf_net_flow

        # Tone
        if score > 50:
            tone = "资金面强势偏多"
        elif score > 20:
            tone = "资金面温和偏多"
        elif score > -20:
            tone = "资金面中性"
        elif score > -50:
            tone = "资金面温和偏空"
        else:
            tone = "资金面强势偏空"

        # Channel observations — pick most notable
        parts: list[str] = []
        if abs(nb) >= 50:
            parts.append(
                f"北向资金大幅{'净买入' if nb > 0 else '净卖出'}{abs(nb):.0f}亿"
            )
        elif abs(nb) >= 20:
            parts.append(f"北向资金{'流入' if nb > 0 else '流出'}{abs(nb):.0f}亿")

        if abs(etf) >= 10:
            parts.append(f"ETF{'净申购' if etf > 0 else '净赎回'}{abs(etf):.0f}亿")

        if abs(mg) >= 30:
            parts.append(f"融资余额{'增加' if mg > 0 else '减少'}{abs(mg):.0f}亿")

        # Divergence check
        up_count = sum(1 for v in [nb, -sb, mg, etf] if v > 0)
        if up_count >= 3:
            suffix = "，多渠道资金共振做多"
        elif up_count <= 1:
            suffix = "，多渠道资金共振偏空"
        elif nb > 0 and etf < 0:
            suffix = "，外资流入但机构赎回，方向分歧"
        elif nb < 0 and etf > 0:
            suffix = "，外资流出但机构申购，内外分歧"
        else:
            suffix = ""

        detail = "，".join(parts) if parts else "各渠道变动平稳"
        return f"{tone}。{detail}{suffix}。"

    @staticmethod
    def _interpret_sectors(items: list[dict], sector_type: str) -> str:
        """Generate a 1-2 sentence Chinese interpretation of sector flow."""
        if not items:
            return ""

        type_label = "行业" if sector_type == "industry" else "概念"

        # Top inflow / outflow
        sorted_by_flow = sorted(
            items, key=lambda x: x.get("net_inflow", 0), reverse=True
        )
        top_in = [s for s in sorted_by_flow[:3] if s.get("net_inflow", 0) > 0]
        top_out = [s for s in sorted_by_flow[-3:] if s.get("net_inflow", 0) < 0]

        parts: list[str] = []
        if top_in:
            names = "、".join(s["sector_name"] for s in top_in)
            parts.append(f"资金流入{type_label}：{names}")
        if top_out:
            names = "、".join(s["sector_name"] for s in reversed(top_out))
            parts.append(f"资金流出{type_label}：{names}")

        if top_in and top_out:
            parts.append(
                f"资金从{top_out[-1]['sector_name']}等板块"
                f"转向{top_in[0]['sector_name']}等板块"
            )

        return "；".join(parts) + "。" if parts else ""

    # ------------------------------------------------------------------
    # Anomaly scanning and notification push (Phase 4 FR-CF017)
    # ------------------------------------------------------------------

    def scan_anomalies(self) -> dict[str, Any]:
        """Scan for capital flow anomalies and push notifications for high-severity events.

        Runs FlowAnomalyDetector for both macro and sector anomalies.
        High-severity events are pushed as notifications via Redis.

        Returns:
            Dict with scan results: total events, notifications pushed.
        """
        from src.analysis.flow_anomaly_detector import (
            FlowAnomalyDetector,
            FlowAnomalyEvent,
        )

        detector = FlowAnomalyDetector()
        events: list[FlowAnomalyEvent] = []

        # Macro anomalies: northbound flow
        try:
            snapshot = self._macro_fetcher.get_latest_snapshot()
            history = self._macro_fetcher.get_macro_history(days=30)
            nb_history = [s.northbound_net for s in history if s.northbound_net != 0]

            if snapshot.northbound_net != 0:
                macro_events = detector.detect_macro_anomalies(
                    snapshot.northbound_net, nb_history
                )
                events.extend(macro_events)
        except Exception as exc:
            logger.warning("Macro anomaly scan failed: %s", exc)

        # Sector anomalies
        try:
            df = self._sector_fetcher.fetch_industry_flow(period="today")
            if (
                not df.empty
                and "sector_name" in df.columns
                and "net_inflow" in df.columns
            ):
                sector_flows = dict(
                    zip(df["sector_name"].astype(str), df["net_inflow"].astype(float))
                )
                sector_history: dict[str, list[float]] = {}
                for period in ("3d", "5d", "10d"):
                    hist_df = self._sector_fetcher.fetch_industry_flow(period=period)
                    if not hist_df.empty and "sector_name" in hist_df.columns:
                        for _, row in hist_df.iterrows():
                            name = str(row.get("sector_name", ""))
                            val = float(row.get("net_inflow", 0) or 0)
                            sector_history.setdefault(name, []).append(val)

                if sector_flows and sector_history:
                    sector_events = detector.detect_sector_anomalies(
                        sector_flows, sector_history
                    )
                    events.extend(sector_events)
        except Exception as exc:
            logger.warning("Sector anomaly scan failed: %s", exc)

        # Push notifications for high-severity events
        notifications_pushed = 0
        high_events = [e for e in events if e.severity == "high"]

        if high_events:
            try:
                r = self._get_redis()
                if r is not None:
                    for event in high_events:
                        notification = {
                            "id": str(uuid.uuid4()),
                            "type": "capital_flow_anomaly",
                            "title": event.title,
                            "summary": event.summary,
                            "symbol": None,
                            "timestamp": datetime.now(UTC).isoformat(),
                            "read": False,
                            "action": "/market?tab=capital-flow",
                        }
                        r.lpush(
                            NOTIFICATIONS_KEY,
                            json.dumps(notification, ensure_ascii=False),
                        )
                        notifications_pushed += 1

                    r.ltrim(NOTIFICATIONS_KEY, 0, MAX_NOTIFICATIONS - 1)

                    # Also publish to the push channel for real-time delivery
                    if notifications_pushed > 0:
                        r.publish(
                            "notifications:push",
                            json.dumps(
                                {
                                    "type": "capital_flow_anomaly",
                                    "count": notifications_pushed,
                                },
                                ensure_ascii=False,
                            ),
                        )
            except Exception as exc:
                logger.warning("Failed to push capital flow notifications: %s", exc)

        logger.info(
            "Capital flow anomaly scan complete: %d events, %d notifications pushed",
            len(events),
            notifications_pushed,
        )
        return {
            "total_events": len(events),
            "high_severity": len(high_events),
            "notifications_pushed": notifications_pushed,
        }

    @staticmethod
    def _get_redis():
        """Get a Redis client for notification storage."""
        try:
            import redis

            from src.utils.config import load_config

            config = load_config("openclaw")
            broker = config.get("celery", {}).get("broker_url", "redis://redis:6379/0")
            return redis.from_url(broker, decode_responses=True)
        except Exception:
            return None
