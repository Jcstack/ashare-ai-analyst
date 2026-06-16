"""Tests for the SchemaRegistry.

Part of v18.0 Agent Spec Compliance — Phase 2.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.web.schemas.registry import SchemaRegistry, SchemaValidationResult


# ── Test models ───────────────────────────────────────────────


class SimpleInput(BaseModel):
    symbol: str
    request_id: str = ""


class SimpleOutput(BaseModel):
    signal: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    key_assumptions: list[str] = Field(default_factory=list)


class StrictOutput(BaseModel):
    """Requires all fields."""

    risk_level: str
    var_result: dict


# ── Registration ──────────────────────────────────────────────


class TestRegistration:
    def test_register_and_list(self):
        reg = SchemaRegistry()
        reg.register("analyst", "1.0.0", SimpleInput, SimpleOutput)

        schemas = reg.list_schemas()
        assert "analyst" in schemas
        assert schemas["analyst"].version == "1.0.0"

    def test_has_schema(self):
        reg = SchemaRegistry()
        assert reg.has_schema("analyst") is False
        reg.register("analyst", "1.0.0", SimpleInput, SimpleOutput)
        assert reg.has_schema("analyst") is True

    def test_get_schema(self):
        reg = SchemaRegistry()
        reg.register("risk", "2.0.0", SimpleInput, StrictOutput)
        info = reg.get_schema("risk")
        assert info is not None
        assert info.version == "2.0.0"
        assert info.input_model is SimpleInput
        assert info.output_model is StrictOutput

    def test_get_schema_missing(self):
        reg = SchemaRegistry()
        assert reg.get_schema("nonexistent") is None

    def test_overwrite_registration(self):
        reg = SchemaRegistry()
        reg.register("analyst", "1.0.0", SimpleInput, SimpleOutput)
        reg.register("analyst", "2.0.0", SimpleInput, StrictOutput)

        info = reg.get_schema("analyst")
        assert info is not None
        assert info.version == "2.0.0"
        assert info.output_model is StrictOutput


# ── Input validation ──────────────────────────────────────────


class TestInputValidation:
    def test_valid_input(self):
        reg = SchemaRegistry()
        reg.register("analyst", "1.0.0", SimpleInput, SimpleOutput)

        result = reg.validate_input("analyst", {"symbol": "600519"})
        assert result.passed is True
        assert result.errors == []
        assert result.direction == "input"

    def test_invalid_input_missing_required(self):
        reg = SchemaRegistry()
        reg.register("analyst", "1.0.0", SimpleInput, SimpleOutput)

        result = reg.validate_input("analyst", {})
        assert result.passed is False
        assert len(result.errors) > 0
        assert result.agent_name == "analyst"

    def test_unregistered_agent_passes(self):
        """No schema registered = pass by default (graceful degradation)."""
        reg = SchemaRegistry()
        result = reg.validate_input("unknown_agent", {"anything": True})
        assert result.passed is True


# ── Output validation ─────────────────────────────────────────


class TestOutputValidation:
    def test_valid_output(self):
        reg = SchemaRegistry()
        reg.register("analyst", "1.0.0", SimpleInput, SimpleOutput)

        result = reg.validate_output(
            "analyst",
            {
                "signal": "buy",
                "confidence_score": 0.85,
                "key_assumptions": ["trend continuation"],
            },
        )
        assert result.passed is True

    def test_invalid_output_missing_field(self):
        reg = SchemaRegistry()
        reg.register("risk", "1.0.0", SimpleInput, StrictOutput)

        result = reg.validate_output("risk", {"risk_level": "high"})
        assert result.passed is False
        assert any("var_result" in e for e in result.errors)

    def test_invalid_output_wrong_type(self):
        reg = SchemaRegistry()
        reg.register("analyst", "1.0.0", SimpleInput, SimpleOutput)

        result = reg.validate_output(
            "analyst",
            {
                "signal": "buy",
                "confidence_score": 1.5,  # > 1.0, should fail
            },
        )
        assert result.passed is False

    def test_output_with_defaults(self):
        """Output with only required field + defaults should pass."""
        reg = SchemaRegistry()
        reg.register("analyst", "1.0.0", SimpleInput, SimpleOutput)

        result = reg.validate_output(
            "analyst",
            {
                "signal": "watch",
                "confidence_score": 0.5,
            },
        )
        assert result.passed is True


# ── SchemaValidationResult ────────────────────────────────────


class TestSchemaValidationResult:
    def test_default_passed(self):
        r = SchemaValidationResult(passed=True)
        assert r.passed is True
        assert r.errors == []

    def test_failed_with_errors(self):
        r = SchemaValidationResult(
            passed=False,
            errors=["symbol: field required", "confidence_score: > 1.0"],
            agent_name="analyst",
            direction="output",
        )
        assert r.passed is False
        assert len(r.errors) == 2
        assert r.agent_name == "analyst"
