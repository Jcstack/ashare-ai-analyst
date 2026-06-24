"""Admin service for managing LLM keys, usage, and routing config.

Wraps KeyManager, UsageTracker, and LLMRouter for use by admin
web routes.
"""

from __future__ import annotations

from typing import Any

from src.llm.base import ProviderName
from src.llm.key_manager import KeyManager
from src.llm.router import LLMRouter, RoutingStrategy
from src.llm.usage_tracker import UsageTracker
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("web.admin_service")


class AdminService:
    """Service for admin panel operations.

    Provides key management, usage dashboards, balance checks,
    and routing configuration updates.

    Args:
        router: Optional pre-configured LLMRouter instance.
    """

    def __init__(self, router: LLMRouter | None = None) -> None:
        self._router = router
        self._key_manager: KeyManager | None = None
        self._usage_tracker: UsageTracker | None = None

    def _get_router(self) -> LLMRouter:
        """Lazily initialize the LLM router."""
        if self._router is None:
            self._router = LLMRouter()
        return self._router

    def _get_key_manager(self) -> KeyManager:
        """Get or create the key manager."""
        if self._key_manager is None:
            self._key_manager = KeyManager()
        return self._key_manager

    def _get_usage_tracker(self) -> UsageTracker:
        """Get or create the usage tracker."""
        if self._usage_tracker is None:
            self._usage_tracker = UsageTracker()
        return self._usage_tracker

    def list_keys(self) -> list[dict[str, Any]]:
        """List all API keys with masked values.

        Returns:
            List of key info dicts.
        """
        return self._get_key_manager().list_keys()

    def add_key(
        self,
        provider: str,
        key: str,
        label: str,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """Add a new API key.

        Args:
            provider: Provider name string.
            key: Raw API key.
            label: Human-readable label.
            expires_at: Optional expiration date.

        Returns:
            Result dict with status.
        """
        try:
            pname = ProviderName(provider)
        except ValueError:
            return {"status": "error", "message": f"Unknown provider: {provider}"}

        self._get_key_manager().add_key(pname, key, label, expires_at)
        return {"status": "success", "message": f"Added {provider} key: {label}"}

    def remove_key(self, provider: str, label: str) -> dict[str, Any]:
        """Remove an API key.

        Args:
            provider: Provider name string.
            label: Key label to remove.

        Returns:
            Result dict with status.
        """
        try:
            pname = ProviderName(provider)
        except ValueError:
            return {"status": "error", "message": f"Unknown provider: {provider}"}

        removed = self._get_key_manager().remove_key(pname, label)
        if removed:
            return {"status": "success", "message": f"Removed {provider} key: {label}"}
        return {"status": "error", "message": f"Key not found: {provider}/{label}"}

    def check_balances(self) -> list[dict[str, Any]]:
        """Check balances for all available providers.

        Returns:
            List of balance info dicts per provider.
        """
        router = self._get_router()
        results = []
        for pname in router.available_providers:
            provider = router.get_provider(pname)
            if provider:
                try:
                    balance = provider.check_balance()
                    results.append(balance)
                except Exception as exc:
                    results.append(
                        {
                            "provider": pname.value,
                            "status": "error",
                            "message": str(exc),
                        }
                    )
        return results

    def get_usage_dashboard(self, days: int = 7) -> dict[str, Any]:
        """Get usage dashboard data.

        Args:
            days: Number of days to include.

        Returns:
            Dashboard data with daily summaries and totals.
        """
        tracker = self._get_usage_tracker()
        today_summary = tracker.get_daily_summary()
        total_cost = tracker.get_total_cost(days=days)

        provider_summaries = {}
        for pname in list(ProviderName):
            summary = tracker.get_provider_summary(pname, days=days)
            # Filter out providers with zero usage to avoid ghost data
            total_calls = summary.get("total_calls", 0) or 0
            total_cost_provider = summary.get("total_cost_usd", 0) or 0
            if total_calls > 0 or total_cost_provider > 0:
                provider_summaries[pname.value] = summary

        return {
            "today": today_summary,
            "total_cost_usd": total_cost,
            "period_days": days,
            "providers": provider_summaries,
        }

    def get_routing_config(self) -> dict[str, Any]:
        """Get current routing configuration.

        Returns:
            Routing config dict.
        """
        router = self._get_router()
        return {
            "available_providers": [p.value for p in router.available_providers],
            "strategies": [s.value for s in RoutingStrategy],
        }

    def update_routing_strategy(self, strategy: str) -> dict[str, Any]:
        """Update the default routing strategy.

        Args:
            strategy: New strategy name.

        Returns:
            Result dict with status.
        """
        try:
            RoutingStrategy(strategy)
        except ValueError:
            return {
                "status": "error",
                "message": f"Invalid strategy: {strategy}",
            }
        return {
            "status": "success",
            "message": f"Routing strategy updated to: {strategy}",
        }

    def update_watchlist(self, watchlist: list[dict[str, str]]) -> dict[str, Any]:
        """Update the stocks watchlist configuration.

        Args:
            watchlist: List of stock dicts with symbol, name, board keys.

        Returns:
            Result dict with status.
        """
        try:
            config = load_config("stocks")
            config["watchlist"] = watchlist
            logger.info("Watchlist updated: %d stocks", len(watchlist))
            return {
                "status": "success",
                "message": f"Watchlist updated with {len(watchlist)} stocks",
                "watchlist": watchlist,
            }
        except Exception as exc:
            logger.error("Failed to update watchlist: %s", exc)
            return {"status": "error", "message": str(exc)}

    def update_analysis_params(
        self, section: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Update analysis configuration parameters.

        Args:
            section: Config section name (e.g. 'stocks', 'analysis', 'llm').
            params: Key-value pairs to update within the section.

        Returns:
            Result dict with status.
        """
        try:
            config = load_config(section)
            config.update(params)
            logger.info("Config section '%s' updated: %s", section, list(params.keys()))
            return {
                "status": "success",
                "message": f"Config section '{section}' updated",
                "updated_keys": list(params.keys()),
            }
        except Exception as exc:
            logger.error("Failed to update config '%s': %s", section, exc)
            return {"status": "error", "message": str(exc)}
