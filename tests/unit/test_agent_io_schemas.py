"""Tests for agent I/O Pydantic schemas.

Verifies that all 12 agent schemas enforce mandatory output fields
and accept valid payloads.

Part of v18.0 Agent Spec Compliance — Phase 2.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.web.schemas.agent_io import (
    AGENT_SCHEMAS,
    AgentInputBase,
    AgentOutputBase,
    AnalystInput,
    AnalystOutput,
    BacktestOutput,
    CorrelationOutput,
    DataLineageRef,
    DataQAInput,
    DataQAOutput,
    ExecPlanOutput,
    MonitorInput,
    MonitorOutput,
    OrchestratorInput,
    OrchestratorOutput,
    PortfolioOutput,
    RegimeOutput,
    ReportOutput,
    RiskOutput,
    SentimentOutput,
    register_all_schemas,
)
from src.web.schemas.registry import SchemaRegistry


# ── Base models ───────────────────────────────────────────────


class TestAgentInputBase:
    def test_defaults(self):
        inp = AgentInputBase()
        assert inp.schema_version == "1.0.0"
        assert inp.request_id == ""
        assert inp.timestamp == ""

    def test_custom(self):
        inp = AgentInputBase(
            schema_version="2.0.0",
            request_id="req-123",
            timestamp="2026-01-01T00:00:00Z",
        )
        assert inp.schema_version == "2.0.0"
        assert inp.request_id == "req-123"


class TestAgentOutputBase:
    def test_defaults(self):
        out = AgentOutputBase()
        assert out.confidence_score == 0.5
        assert out.key_assumptions == []
        assert out.failure_modes == []
        assert out.data_lineage == []
        assert out.data_gaps == []

    def test_mandatory_fields_present(self):
        """All 5 mandatory fields must be accessible."""
        out = AgentOutputBase(
            confidence_score=0.8,
            key_assumptions=["trend continues"],
            failure_modes=["sudden reversal"],
            data_lineage=[
                DataLineageRef(
                    snapshot_id="snap-1",
                    source="akshare",
                    source_type="market_data",
                    timestamp="2026-01-01T00:00:00Z",
                )
            ],
            data_gaps=["missing volume data"],
        )
        assert out.confidence_score == 0.8
        assert len(out.key_assumptions) == 1
        assert len(out.failure_modes) == 1
        assert len(out.data_lineage) == 1
        assert len(out.data_gaps) == 1

    def test_confidence_score_bounds(self):
        """confidence_score must be in [0, 1]."""
        with pytest.raises(ValidationError):
            AgentOutputBase(confidence_score=1.5)

        with pytest.raises(ValidationError):
            AgentOutputBase(confidence_score=-0.1)

    def test_confidence_score_edge_values(self):
        out0 = AgentOutputBase(confidence_score=0.0)
        assert out0.confidence_score == 0.0
        out1 = AgentOutputBase(confidence_score=1.0)
        assert out1.confidence_score == 1.0


class TestDataLineageRef:
    def test_defaults(self):
        ref = DataLineageRef()
        assert ref.snapshot_id == ""
        assert ref.source == ""

    def test_full(self):
        ref = DataLineageRef(
            snapshot_id="snap-abc",
            source="akshare",
            source_type="market_data",
            timestamp="2026-01-01T10:00:00Z",
        )
        assert ref.snapshot_id == "snap-abc"


# ── Per-agent schema tests ───────────────────────────────────


class TestDataQASchemas:
    def test_input(self):
        inp = DataQAInput(symbol="600519")
        assert inp.symbol == "600519"

    def test_output(self):
        out = DataQAOutput(
            data_quality_score=85,
            is_sufficient=True,
            confidence_score=0.9,
        )
        assert out.data_quality_score == 85
        assert out.is_sufficient is True

    def test_quality_score_bounds(self):
        with pytest.raises(ValidationError):
            DataQAOutput(data_quality_score=101)
        with pytest.raises(ValidationError):
            DataQAOutput(data_quality_score=-1)


class TestAnalystSchemas:
    def test_input(self):
        inp = AnalystInput(symbol="600519", data_quality_score=90)
        assert inp.symbol == "600519"

    def test_output(self):
        out = AnalystOutput(
            signal="buy",
            dimensions=[{"name": "trend", "score": 0.8}],
            confidence_score=0.75,
            key_assumptions=["volume supports breakout"],
        )
        assert out.signal == "buy"
        assert len(out.dimensions) == 1


class TestBacktestSchemas:
    def test_output(self):
        out = BacktestOutput(
            overfit_warning=True,
            confidence_score=0.6,
        )
        assert out.overfit_warning is True


class TestRiskSchemas:
    def test_output(self):
        out = RiskOutput(
            risk_level="high",
            risk_approved=False,
            confidence_score=0.7,
            warnings=["concentration risk"],
        )
        assert out.risk_level == "high"
        assert out.risk_approved is False


class TestSentimentSchemas:
    def test_output(self):
        out = SentimentOutput(
            sentiment_score=0.6,
            sentiment_signal="bullish",
            confidence_score=0.65,
        )
        assert out.sentiment_score == 0.6

    def test_sentiment_score_bounds(self):
        with pytest.raises(ValidationError):
            SentimentOutput(sentiment_score=1.5)
        with pytest.raises(ValidationError):
            SentimentOutput(sentiment_score=-1.5)


class TestRegimeSchemas:
    def test_output(self):
        out = RegimeOutput(
            current_regime="bull",
            regime_confidence=0.8,
            confidence_score=0.75,
        )
        assert out.current_regime == "bull"


class TestCorrelationSchemas:
    def test_output(self):
        out = CorrelationOutput(
            diversification_score=0.7,
            confidence_score=0.8,
        )
        assert out.diversification_score == 0.7

    def test_diversification_bounds(self):
        with pytest.raises(ValidationError):
            CorrelationOutput(diversification_score=1.5)


class TestPortfolioSchemas:
    def test_output(self):
        out = PortfolioOutput(
            suggested_shares=500,
            suggested_weight=0.15,
            confidence_score=0.7,
        )
        assert out.suggested_shares == 500


class TestExecPlanSchemas:
    def test_output(self):
        out = ExecPlanOutput(
            gate_request_id="gate-abc",
            confidence_score=0.9,
        )
        assert out.gate_request_id == "gate-abc"


class TestMonitorSchemas:
    def test_input(self):
        inp = MonitorInput(window_days=60)
        assert inp.window_days == 60

    def test_output(self):
        out = MonitorOutput(
            flagged_symbols=["600519", "000001"],
            confidence_score=0.85,
        )
        assert len(out.flagged_symbols) == 2


class TestReportSchemas:
    def test_output(self):
        out = ReportOutput(
            report_markdown="# Report",
            executive_summary="All good",
            scenarios=[{"name": "bull", "probability": 0.4}],
            confidence_score=0.7,
        )
        assert len(out.scenarios) == 1


class TestOrchestratorSchemas:
    def test_input(self):
        inp = OrchestratorInput(user_message="analyze 600519")
        assert inp.user_message == "analyze 600519"

    def test_output(self):
        out = OrchestratorOutput(
            pipeline_name="stock_analysis",
            steps_executed=5,
            confidence_score=0.75,
        )
        assert out.pipeline_name == "stock_analysis"


# ── Schema map and auto-registration ─────────────────────────


class TestSchemaMap:
    def test_all_12_agents_in_map(self):
        expected = {
            "data_qa",
            "analyst",
            "backtest",
            "risk",
            "sentiment",
            "regime",
            "correlation",
            "portfolio",
            "exec_plan",
            "monitor",
            "report",
            "orchestrator",
        }
        assert set(AGENT_SCHEMAS.keys()) == expected

    def test_each_entry_has_three_elements(self):
        for name, entry in AGENT_SCHEMAS.items():
            assert len(entry) == 3, f"{name} should have (input, output, version)"
            inp, out, ver = entry
            assert issubclass(inp, AgentInputBase)
            assert issubclass(out, AgentOutputBase)
            assert isinstance(ver, str)

    def test_register_all(self):
        reg = SchemaRegistry()
        register_all_schemas(reg)
        schemas = reg.list_schemas()
        assert len(schemas) == 12
        assert "analyst" in schemas
        assert "risk" in schemas


# ── Cross-schema validation via registry ──────────────────────


class TestCrossSchemaValidation:
    def test_analyst_output_validates(self):
        reg = SchemaRegistry()
        register_all_schemas(reg)

        result = reg.validate_output(
            "analyst",
            {
                "signal": "buy",
                "confidence_score": 0.8,
                "key_assumptions": ["trend"],
                "failure_modes": ["reversal"],
                "data_lineage": [],
                "data_gaps": [],
            },
        )
        assert result.passed is True

    def test_analyst_output_bad_confidence(self):
        reg = SchemaRegistry()
        register_all_schemas(reg)

        result = reg.validate_output(
            "analyst",
            {
                "signal": "buy",
                "confidence_score": 2.0,
            },
        )
        assert result.passed is False

    def test_data_qa_input_validates(self):
        reg = SchemaRegistry()
        register_all_schemas(reg)

        result = reg.validate_input("data_qa", {"symbol": "600519"})
        assert result.passed is True
