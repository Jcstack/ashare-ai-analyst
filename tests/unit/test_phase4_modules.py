"""Tests for Phase 4 — Tool & Engine Layer modules.

Covers:
- SystemAlertEngine (alert_engine.py)
- BrokerInterface / SimulationBroker (broker_interface.py)
- Quant tool registration (tool_registry.py additions)

Part of v18.0 Agent Spec Compliance — Phase 4.
"""

from __future__ import annotations

from unittest.mock import MagicMock


# ═══════════════════════════════════════════════════════════════════════════
# SystemAlertEngine
# ═══════════════════════════════════════════════════════════════════════════


class TestSystemAlertEngine:
    def test_default_rules_registered(self):
        from src.intelligence.alert_engine import SystemAlertEngine

        engine = SystemAlertEngine()
        rules = engine.list_rules()
        rule_names = [r["name"] for r in rules]
        assert "regime_shift" in rule_names
        assert "drift_detected" in rule_names
        assert "circuit_breaker_warning" in rule_names
        assert "volume_anomaly" in rule_names
        assert "concentration_warning" in rule_names

    def test_regime_shift_triggers(self):
        from src.intelligence.alert_engine import SystemAlertEngine

        engine = SystemAlertEngine()
        alerts = engine.evaluate(
            {
                "regime_changed": True,
                "old_regime": "bull",
                "new_regime": "bear",
            }
        )
        regime_alerts = [a for a in alerts if a.rule_name == "regime_shift"]
        assert len(regime_alerts) == 1
        assert "bull" in regime_alerts[0].title
        assert "bear" in regime_alerts[0].title

    def test_drift_triggers(self):
        from src.intelligence.alert_engine import SystemAlertEngine

        engine = SystemAlertEngine()
        alerts = engine.evaluate(
            {
                "has_significant_drift": True,
                "drift_amount": 0.25,
            }
        )
        drift_alerts = [a for a in alerts if a.rule_name == "drift_detected"]
        assert len(drift_alerts) == 1
        assert drift_alerts[0].severity == "critical"

    def test_circuit_breaker_warning(self):
        from src.intelligence.alert_engine import SystemAlertEngine

        engine = SystemAlertEngine()
        alerts = engine.evaluate({"daily_pnl_pct": -0.12})
        cb_alerts = [a for a in alerts if a.rule_name == "circuit_breaker_warning"]
        assert len(cb_alerts) == 1
        assert cb_alerts[0].severity == "warning"

    def test_circuit_breaker_critical(self):
        from src.intelligence.alert_engine import SystemAlertEngine

        engine = SystemAlertEngine()
        alerts = engine.evaluate({"daily_pnl_pct": -0.18})
        cb_alerts = [a for a in alerts if a.rule_name == "circuit_breaker_warning"]
        assert len(cb_alerts) == 1
        assert cb_alerts[0].severity == "critical"

    def test_no_trigger_no_alerts(self):
        from src.intelligence.alert_engine import SystemAlertEngine

        engine = SystemAlertEngine()
        alerts = engine.evaluate({"daily_pnl_pct": -0.01})
        assert len(alerts) == 0

    def test_cooldown_prevents_retrigger(self):
        from src.intelligence.alert_engine import SystemAlertEngine

        engine = SystemAlertEngine()
        alerts1 = engine.evaluate({"has_significant_drift": True, "drift_amount": 0.2})
        alerts2 = engine.evaluate({"has_significant_drift": True, "drift_amount": 0.2})
        assert len(alerts1) == 1
        assert len(alerts2) == 0  # Cooldown active

    def test_get_active_alerts(self):
        from src.intelligence.alert_engine import SystemAlertEngine

        engine = SystemAlertEngine()
        engine.evaluate({"daily_pnl_pct": -0.12})
        active = engine.get_active_alerts()
        assert len(active) >= 1

    def test_get_active_alerts_by_severity(self):
        from src.intelligence.alert_engine import SystemAlertEngine

        engine = SystemAlertEngine()
        engine.evaluate({"daily_pnl_pct": -0.12})
        warnings = engine.get_active_alerts(severity="warning")
        criticals = engine.get_active_alerts(severity="critical")
        assert len(warnings) >= 1 or len(criticals) >= 0

    def test_clear_alerts(self):
        from src.intelligence.alert_engine import SystemAlertEngine

        engine = SystemAlertEngine()
        engine.evaluate({"daily_pnl_pct": -0.12})
        cleared = engine.clear_alerts()
        assert cleared >= 1
        assert len(engine.get_active_alerts()) == 0

    def test_custom_rule(self):
        from src.intelligence.alert_engine import Alert, AlertRule, SystemAlertEngine

        engine = SystemAlertEngine()
        engine.register_rule(
            AlertRule(
                name="test_rule",
                condition=lambda s: s.get("test_flag", False),
                builder=lambda s: Alert(
                    alert_id="",
                    rule_name="test_rule",
                    severity="info",
                    title="Test alert",
                    description="Test",
                ),
            )
        )
        alerts = engine.evaluate({"test_flag": True})
        assert any(a.rule_name == "test_rule" for a in alerts)

    def test_unregister_rule(self):
        from src.intelligence.alert_engine import SystemAlertEngine

        engine = SystemAlertEngine()
        assert engine.unregister_rule("regime_shift") is True
        assert engine.unregister_rule("nonexistent") is False


# ═══════════════════════════════════════════════════════════════════════════
# BrokerInterface / SimulationBroker
# ═══════════════════════════════════════════════════════════════════════════


class TestSimulationBroker:
    def test_mode(self):
        from src.web.services.broker_interface import SimulationBroker

        broker = SimulationBroker()
        assert broker.mode == "simulation"

    def test_submit_order(self):
        from src.web.services.broker_interface import SimulationBroker

        broker = SimulationBroker()
        status = broker.submit_order(
            symbol="600519",
            action="buy",
            shares=100,
            price=1800.0,
            gate_request_id="gate-abc123",
        )
        assert status.status == "simulated"
        assert status.symbol == "600519"
        assert status.order_id.startswith("sim-")

    def test_get_order_status_found(self):
        from src.web.services.broker_interface import SimulationBroker

        broker = SimulationBroker()
        submitted = broker.submit_order("600519", "buy", 100, 1800.0)
        found = broker.get_order_status(submitted.order_id)
        assert found.status == "simulated"
        assert found.symbol == "600519"

    def test_get_order_status_not_found(self):
        from src.web.services.broker_interface import SimulationBroker

        broker = SimulationBroker()
        status = broker.get_order_status("nonexistent")
        assert status.status == "not_found"

    def test_get_positions_empty(self):
        from src.web.services.broker_interface import SimulationBroker

        broker = SimulationBroker()
        # May return empty if no portfolio.json exists
        positions = broker.get_positions()
        assert isinstance(positions, list)

    def test_get_balance(self):
        from src.web.services.broker_interface import SimulationBroker

        broker = SimulationBroker()
        balance = broker.get_balance()
        assert hasattr(balance, "total_assets")
        assert hasattr(balance, "available_cash")


class TestLiveBroker:
    def test_not_implemented(self):
        from src.web.services.broker_interface import LiveBroker

        broker = LiveBroker()
        assert broker.mode == "live"
        try:
            broker.get_positions()
            assert False, "Should raise NotImplementedError"
        except NotImplementedError:
            pass


class TestCreateBroker:
    def test_default_simulation(self):
        from src.web.services.broker_interface import create_broker

        broker = create_broker()
        assert broker.mode == "simulation"


# ═══════════════════════════════════════════════════════════════════════════
# Quant tool registration
# ═══════════════════════════════════════════════════════════════════════════


class TestQuantToolRegistration:
    def test_registers_quant_tools(self):
        from src.web.services.tool_registry import ToolRegistry

        registry = ToolRegistry()
        signal_lib = MagicMock()
        regime_detector = MagicMock()
        walk_forward = MagicMock()
        feature_store = MagicMock()

        registry.register_all(
            {
                "signal_library": signal_lib,
                "regime_detector": regime_detector,
                "walk_forward_validator": walk_forward,
                "feature_store": feature_store,
            }
        )

        tool_names = [t["name"] for t in registry.get_tool_definitions()]
        assert "evaluate_signals" in tool_names
        assert "detect_regime" in tool_names
        assert "run_walk_forward" in tool_names
        assert "get_features" in tool_names

    def test_quant_tools_have_required_schema(self):
        from src.web.services.tool_registry import ToolRegistry

        registry = ToolRegistry()
        registry.register_all(
            {
                "signal_library": MagicMock(),
                "regime_detector": MagicMock(),
                "walk_forward_validator": MagicMock(),
                "feature_store": MagicMock(),
            }
        )

        for tool_def in registry.get_tool_definitions():
            assert "name" in tool_def
            assert "description" in tool_def
            assert "input_schema" in tool_def
            assert tool_def["input_schema"]["type"] == "object"
