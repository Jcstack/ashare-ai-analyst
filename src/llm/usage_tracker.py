"""LLM API usage tracking and cost reporting.

Records per-call usage to daily JSON files under
``data/processed/llm_usage/`` for cost analysis and monitoring.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from src.llm.base import LLMResponse, ProviderName
from src.utils.config import get_data_dir
from src.utils.logger import get_logger

logger = get_logger("llm.usage_tracker")


@dataclass
class UsageRecord:
    """A single LLM usage record.

    Attributes:
        provider: LLM provider name.
        model: Model identifier.
        input_tokens: Input tokens consumed.
        output_tokens: Output tokens generated.
        cost_usd: Estimated cost in USD.
        latency_ms: Response latency in milliseconds.
        symbol: Stock symbol analyzed (if applicable).
        analysis_type: Type of analysis performed.
        timestamp: ISO timestamp of the call.
    """

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    symbol: str = ""
    analysis_type: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class UsageTracker:
    """Tracks and persists LLM API usage to daily JSON files.

    Usage records are appended to daily files at
    ``data/processed/llm_usage/YYYY-MM-DD.json``.
    """

    def __init__(self) -> None:
        self._usage_dir = get_data_dir("processed") / "llm_usage"
        self._usage_dir.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        response: LLMResponse,
        symbol: str = "",
        analysis_type: str = "",
    ) -> UsageRecord:
        """Record an LLM API call.

        Args:
            response: The LLMResponse from the provider.
            symbol: Stock symbol analyzed (if applicable).
            analysis_type: Type of analysis performed.

        Returns:
            The created UsageRecord.
        """
        rec = UsageRecord(
            provider=response.provider.value,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms,
            symbol=symbol,
            analysis_type=analysis_type,
        )
        self._append_record(rec)
        return rec

    def get_daily_summary(self, day: date | None = None) -> dict[str, Any]:
        """Get aggregated usage summary for a specific day.

        Args:
            day: Date to summarize (defaults to today).

        Returns:
            Dict with total_calls, total_tokens, total_cost, and
            per-provider breakdown.
        """
        day = day or date.today()
        records = self._load_day(day)

        if not records:
            return {
                "date": day.isoformat(),
                "total_calls": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_cost_usd": 0.0,
                "providers": {},
            }

        providers: dict[str, dict[str, Any]] = {}
        total_input = 0
        total_output = 0
        total_cost = 0.0

        for rec in records:
            total_input += rec["input_tokens"]
            total_output += rec["output_tokens"]
            total_cost += rec["cost_usd"]

            p = rec["provider"]
            if p not in providers:
                providers[p] = {
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                }
            providers[p]["calls"] += 1
            providers[p]["input_tokens"] += rec["input_tokens"]
            providers[p]["output_tokens"] += rec["output_tokens"]
            providers[p]["cost_usd"] += rec["cost_usd"]

        return {
            "date": day.isoformat(),
            "total_calls": len(records),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_cost_usd": round(total_cost, 6),
            "providers": providers,
        }

    def get_provider_summary(
        self, provider: ProviderName, days: int = 7
    ) -> dict[str, Any]:
        """Get usage summary for a provider over recent days.

        Args:
            provider: Provider to summarize.
            days: Number of recent days to include.

        Returns:
            Dict with per-day breakdown for the provider.
        """
        from datetime import timedelta

        today = date.today()
        daily_stats: list[dict[str, Any]] = []
        total_cost = 0.0
        total_calls = 0

        for i in range(days):
            day = today - timedelta(days=i)
            records = self._load_day(day)
            provider_records = [r for r in records if r["provider"] == provider.value]
            day_cost = sum(r["cost_usd"] for r in provider_records)
            total_cost += day_cost
            total_calls += len(provider_records)
            daily_stats.append(
                {
                    "date": day.isoformat(),
                    "calls": len(provider_records),
                    "cost_usd": round(day_cost, 6),
                }
            )

        return {
            "provider": provider.value,
            "days": days,
            "total_calls": total_calls,
            "total_cost_usd": round(total_cost, 6),
            "daily": daily_stats,
        }

    def get_total_cost(self, days: int = 30) -> float:
        """Get total cost across all providers over recent days.

        Args:
            days: Number of recent days to sum.

        Returns:
            Total cost in USD.
        """
        from datetime import timedelta

        today = date.today()
        total = 0.0
        for i in range(days):
            day = today - timedelta(days=i)
            records = self._load_day(day)
            total += sum(r["cost_usd"] for r in records)
        return round(total, 6)

    def _append_record(self, rec: UsageRecord) -> None:
        """Append a record to today's JSON file."""
        today = date.today()
        file_path = self._usage_dir / f"{today.isoformat()}.json"

        records: list[dict[str, Any]] = []
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    records = json.load(f)
            except (json.JSONDecodeError, OSError):
                records = []

        records.append(asdict(rec))

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

    def _load_day(self, day: date) -> list[dict[str, Any]]:
        """Load records for a specific day.

        Args:
            day: Date to load.

        Returns:
            List of record dicts, or empty list if no file.
        """
        file_path = self._usage_dir / f"{day.isoformat()}.json"
        if not file_path.exists():
            return []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
