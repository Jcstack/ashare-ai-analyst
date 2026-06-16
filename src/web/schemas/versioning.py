"""Versioned schema base classes and confidence metadata.

Provides VersionedSchema as a drop-in BaseModel replacement that carries
a schema version stamp, and ConfidenceMetadata for structured trust
assessment of AI-generated analysis outputs.

Part of v14.0 Institutional Contracts layer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Schema versioning
# ---------------------------------------------------------------------------


class SchemaVersion(BaseModel):
    """Semantic version for a schema definition."""

    major: int = 1
    minor: int = 0
    patch: int = 0

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def from_string(cls, version_str: str) -> SchemaVersion:
        """Parse a 'major.minor.patch' string into a SchemaVersion."""
        parts = version_str.split(".")
        return cls(
            major=int(parts[0]) if len(parts) > 0 else 1,
            minor=int(parts[1]) if len(parts) > 1 else 0,
            patch=int(parts[2]) if len(parts) > 2 else 0,
        )


TrustZone = Literal["HIGH", "MEDIUM", "LOW", "UNTRUSTED"]


class ConfidenceMetadata(BaseModel):
    """Structured metadata describing the reliability of an analysis output.

    Attributes:
        key_assumptions: Assumptions the analysis depends on.
        failure_modes: Scenarios that would invalidate the conclusion.
        data_gaps: Missing or incomplete data sources.
        trust_zone: Computed trust level based on confidence + data quality.
        confidence_score: Numeric confidence (0.0-1.0).
        validation_rules_passed: List of validation rule IDs that passed.
        validation_rules_failed: List of validation rule IDs that failed.
    """

    key_assumptions: list[str] = Field(default_factory=list)
    failure_modes: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    trust_zone: TrustZone = "MEDIUM"
    confidence_score: float = 0.5
    validation_rules_passed: list[str] = Field(default_factory=list)
    validation_rules_failed: list[str] = Field(default_factory=list)


class VersionedSchema(BaseModel):
    """Base class for all versioned schemas.

    Adds a ``_schema_version`` field with a default value so existing
    code that instantiates subclasses without providing a version
    continues to work.  The version travels with serialized payloads
    for forward/backward compatibility detection.

    Usage::

        class MyModel(VersionedSchema):
            _schema_version: str = "1.0.0"
            name: str
            value: float

    The ``confidence_metadata`` field is optional and only populated
    for analysis outputs that carry trust assessments.
    """

    _schema_version: str = "1.0.0"
    confidence_metadata: ConfidenceMetadata | None = None


# ---------------------------------------------------------------------------
# Trust zone computation
# ---------------------------------------------------------------------------


def compute_trust_zone(
    confidence_score: float,
    data_quality_score: int = 100,
    validation_pass_rate: float = 1.0,
) -> TrustZone:
    """Determine the trust zone from confidence, data quality, and validation.

    Args:
        confidence_score: LLM confidence (0.0-1.0).
        data_quality_score: Data quality (0-100).
        validation_pass_rate: Fraction of validation rules passed (0.0-1.0).

    Returns:
        A TrustZone literal.
    """
    # Normalize data quality to 0-1
    dq = max(0.0, min(1.0, data_quality_score / 100.0))

    # Weighted composite: 40% confidence + 30% data quality + 30% validation
    composite = 0.4 * confidence_score + 0.3 * dq + 0.3 * validation_pass_rate

    if composite >= 0.75:
        return "HIGH"
    if composite >= 0.50:
        return "MEDIUM"
    if composite >= 0.25:
        return "LOW"
    return "UNTRUSTED"


def build_confidence_metadata(
    confidence_score: float,
    data_quality_score: int = 100,
    key_assumptions: list[str] | None = None,
    failure_modes: list[str] | None = None,
    data_gaps: list[str] | None = None,
    rules_passed: list[str] | None = None,
    rules_failed: list[str] | None = None,
) -> ConfidenceMetadata:
    """Construct a ConfidenceMetadata with auto-computed trust zone.

    Args:
        confidence_score: Numeric confidence (0.0-1.0).
        data_quality_score: Data quality score (0-100).
        key_assumptions: Assumptions the analysis depends on.
        failure_modes: Scenarios that would invalidate conclusions.
        data_gaps: Missing data sources.
        rules_passed: IDs of validation rules that passed.
        rules_failed: IDs of validation rules that failed.

    Returns:
        Fully populated ConfidenceMetadata.
    """
    passed = rules_passed or []
    failed = rules_failed or []
    total = len(passed) + len(failed)
    pass_rate = len(passed) / total if total > 0 else 1.0

    trust_zone = compute_trust_zone(confidence_score, data_quality_score, pass_rate)

    return ConfidenceMetadata(
        key_assumptions=key_assumptions or [],
        failure_modes=failure_modes or [],
        data_gaps=data_gaps or [],
        trust_zone=trust_zone,
        confidence_score=confidence_score,
        validation_rules_passed=passed,
        validation_rules_failed=failed,
    )
