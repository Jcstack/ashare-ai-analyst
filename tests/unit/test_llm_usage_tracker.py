"""Unit tests for src/llm/usage_tracker.py — UsageTracker.

Tests recording, daily summaries, provider summaries, and total cost.
"""

from datetime import date

import pytest

from src.llm.base import LLMResponse, ProviderName
from src.llm.usage_tracker import UsageRecord, UsageTracker


@pytest.fixture
def tracker(tmp_path, monkeypatch):
    """Create a UsageTracker with temp directory."""
    usage_dir = tmp_path / "processed" / "llm_usage"
    usage_dir.mkdir(parents=True)

    # Monkey-patch get_data_dir to return tmp_path
    monkeypatch.setattr(
        "src.llm.usage_tracker.get_data_dir",
        lambda subdir="": tmp_path / subdir if subdir else tmp_path,
    )
    return UsageTracker()


@pytest.fixture
def sample_response():
    """Create a sample LLMResponse for recording."""
    return LLMResponse(
        text="test",
        provider=ProviderName.ANTHROPIC,
        model="claude-sonnet-4-5-20250929",
        input_tokens=100,
        output_tokens=200,
        latency_ms=500.0,
        cost_usd=0.0033,
    )


class TestUsageTracker:
    """Tests for UsageTracker."""

    def test_record_creates_file(self, tracker, sample_response):
        rec = tracker.record(sample_response, symbol="000001")
        assert isinstance(rec, UsageRecord)
        assert rec.provider == "anthropic"
        assert rec.symbol == "000001"

    def test_record_appends_to_file(self, tracker, sample_response):
        tracker.record(sample_response, symbol="000001")
        tracker.record(sample_response, symbol="600519")

        summary = tracker.get_daily_summary()
        assert summary["total_calls"] == 2

    def test_daily_summary(self, tracker, sample_response):
        tracker.record(sample_response, symbol="000001")
        summary = tracker.get_daily_summary()

        assert summary["date"] == date.today().isoformat()
        assert summary["total_calls"] == 1
        assert summary["total_input_tokens"] == 100
        assert summary["total_output_tokens"] == 200
        assert summary["total_cost_usd"] > 0
        assert "anthropic" in summary["providers"]

    def test_empty_daily_summary(self, tracker):
        summary = tracker.get_daily_summary()
        assert summary["total_calls"] == 0
        assert summary["total_cost_usd"] == 0.0

    def test_provider_summary(self, tracker, sample_response):
        tracker.record(sample_response)
        summary = tracker.get_provider_summary(ProviderName.ANTHROPIC, days=1)

        assert summary["provider"] == "anthropic"
        assert summary["total_calls"] == 1
        assert summary["total_cost_usd"] > 0

    def test_total_cost(self, tracker, sample_response):
        tracker.record(sample_response)
        tracker.record(sample_response)

        total = tracker.get_total_cost(days=1)
        assert total == pytest.approx(0.0066, abs=0.0001)

    def test_total_cost_no_data(self, tracker):
        total = tracker.get_total_cost(days=7)
        assert total == 0.0


class TestUsageRecord:
    """Tests for UsageRecord dataclass."""

    def test_defaults(self):
        rec = UsageRecord(
            provider="openai",
            model="gpt-4o",
            input_tokens=50,
            output_tokens=100,
            cost_usd=0.001,
            latency_ms=200.0,
        )
        assert rec.symbol == ""
        assert rec.analysis_type == ""
        assert rec.timestamp  # auto-generated
