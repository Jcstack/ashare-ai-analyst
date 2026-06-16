"""System-level alert engine — configurable rules for cross-cutting alerts.

Higher-level than src/analysis/alerts.py (stock-specific technical alerts).
Handles regime shifts, model drift, circuit breaker warnings, and custom
rules from any source.

Part of v18.0 Agent Spec Compliance — Phase 4.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from src.utils.logger import get_logger

logger = get_logger("intelligence.alert_engine")


@dataclass
class Alert:
    """A triggered alert."""

    alert_id: str
    rule_name: str
    severity: str  # info, warning, critical
    title: str
    description: str
    symbol: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        if not self.alert_id:
            self.alert_id = f"alert-{uuid.uuid4().hex[:8]}"


@dataclass
class AlertRule:
    """A registered alert rule.

    Args:
        name: Unique rule name.
        condition: Callable(snapshot) -> bool. Returns True if alert triggers.
        builder: Callable(snapshot) -> Alert. Builds the alert when triggered.
        severity: Default severity level.
        cooldown_seconds: Minimum time between repeated triggers for same rule.
        enabled: Whether the rule is active.
    """

    name: str
    condition: Callable[[dict[str, Any]], bool]
    builder: Callable[[dict[str, Any]], Alert]
    severity: str = "warning"
    cooldown_seconds: int = 300
    enabled: bool = True


class SystemAlertEngine:
    """Configurable rule-based alert engine for system-level events.

    Supports rule registration, evaluation against market snapshots,
    cooldown tracking, and active alert retrieval.

    Usage::

        engine = SystemAlertEngine()
        engine.register_rule(AlertRule(
            name="regime_shift",
            condition=lambda s: s.get("regime_changed", False),
            builder=lambda s: Alert(...),
        ))
        alerts = engine.evaluate(snapshot)
    """

    def __init__(self) -> None:
        self._rules: dict[str, AlertRule] = {}
        self._active_alerts: list[Alert] = []
        self._last_triggered: dict[str, float] = {}
        self._max_active = 100
        self._register_defaults()

    def register_rule(self, rule: AlertRule) -> None:
        """Register a new alert rule."""
        self._rules[rule.name] = rule
        logger.info("Registered alert rule: %s", rule.name)

    def unregister_rule(self, name: str) -> bool:
        """Remove a registered rule."""
        return self._rules.pop(name, None) is not None

    def evaluate(self, market_snapshot: dict[str, Any]) -> list[Alert]:
        """Evaluate all enabled rules against the market snapshot.

        Returns list of newly triggered alerts (respecting cooldowns).
        """
        now = time.time()
        triggered: list[Alert] = []

        for rule in self._rules.values():
            if not rule.enabled:
                continue

            # Check cooldown
            last = self._last_triggered.get(rule.name, 0.0)
            if now - last < rule.cooldown_seconds:
                continue

            try:
                if rule.condition(market_snapshot):
                    alert = rule.builder(market_snapshot)
                    triggered.append(alert)
                    self._last_triggered[rule.name] = now
                    logger.info("Alert triggered: %s — %s", rule.name, alert.title)
            except Exception as exc:
                logger.error("Alert rule %s failed: %s", rule.name, exc)

        # Add to active alerts (capped)
        self._active_alerts.extend(triggered)
        if len(self._active_alerts) > self._max_active:
            self._active_alerts = self._active_alerts[-self._max_active :]

        return triggered

    def get_active_alerts(
        self,
        symbol: str | None = None,
        severity: str | None = None,
    ) -> list[Alert]:
        """Get currently active alerts, optionally filtered."""
        results = self._active_alerts
        if symbol:
            results = [a for a in results if a.symbol == symbol]
        if severity:
            results = [a for a in results if a.severity == severity]
        return results

    def clear_alerts(self, rule_name: str | None = None) -> int:
        """Clear active alerts, optionally by rule name."""
        if rule_name:
            before = len(self._active_alerts)
            self._active_alerts = [
                a for a in self._active_alerts if a.rule_name != rule_name
            ]
            return before - len(self._active_alerts)
        count = len(self._active_alerts)
        self._active_alerts.clear()
        return count

    def list_rules(self) -> list[dict[str, Any]]:
        """List all registered rules."""
        return [
            {
                "name": r.name,
                "severity": r.severity,
                "enabled": r.enabled,
                "cooldown_seconds": r.cooldown_seconds,
            }
            for r in self._rules.values()
        ]

    def _register_defaults(self) -> None:
        """Register predefined alert rules."""
        self.register_rule(
            AlertRule(
                name="regime_shift",
                condition=lambda s: s.get("regime_changed", False),
                builder=lambda s: Alert(
                    alert_id="",
                    rule_name="regime_shift",
                    severity="warning",
                    title=f"市场 regime 切换: {s.get('old_regime', '?')} → {s.get('new_regime', '?')}",
                    description="市场 regime 发生切换，策略适应度可能改变",
                    data={
                        "old_regime": s.get("old_regime"),
                        "new_regime": s.get("new_regime"),
                    },
                ),
                cooldown_seconds=3600,
            )
        )

        self.register_rule(
            AlertRule(
                name="drift_detected",
                condition=lambda s: s.get("has_significant_drift", False),
                builder=lambda s: Alert(
                    alert_id="",
                    rule_name="drift_detected",
                    severity="critical",
                    title="预测模型漂移检测到",
                    description=f"模型准确率下降 {s.get('drift_amount', 0):.1%}",
                    data={"drift_amount": s.get("drift_amount")},
                ),
                cooldown_seconds=7200,
            )
        )

        self.register_rule(
            AlertRule(
                name="circuit_breaker_warning",
                condition=lambda s: abs(s.get("daily_pnl_pct", 0)) > 0.10,
                builder=lambda s: Alert(
                    alert_id="",
                    rule_name="circuit_breaker_warning",
                    severity="critical"
                    if abs(s.get("daily_pnl_pct", 0)) > 0.15
                    else "warning",
                    title=f"组合日亏损预警: {s.get('daily_pnl_pct', 0):.1%}",
                    description="组合日内亏损接近或超过熔断阈值",
                    data={"daily_pnl_pct": s.get("daily_pnl_pct")},
                ),
                cooldown_seconds=1800,
            )
        )

        self.register_rule(
            AlertRule(
                name="volume_anomaly",
                condition=lambda s: s.get("volume_ratio", 1.0) > 3.0,
                builder=lambda s: Alert(
                    alert_id="",
                    rule_name="volume_anomaly",
                    severity="warning",
                    title=f"异常放量: {s.get('symbol', '?')} ({s.get('volume_ratio', 0):.1f}x)",
                    description=f"成交量是20日均量的 {s.get('volume_ratio', 0):.1f} 倍",
                    symbol=s.get("symbol"),
                    data={"volume_ratio": s.get("volume_ratio")},
                ),
                cooldown_seconds=600,
            )
        )

        self.register_rule(
            AlertRule(
                name="concentration_warning",
                condition=lambda s: any(
                    w > 0.30 for w in (s.get("position_weights") or {}).values()
                ),
                builder=lambda s: Alert(
                    alert_id="",
                    rule_name="concentration_warning",
                    severity="warning",
                    title="持仓集中度过高",
                    description="存在单只股票仓位超过 30% 的限制",
                    data={"weights": s.get("position_weights")},
                ),
                cooldown_seconds=3600,
            )
        )
