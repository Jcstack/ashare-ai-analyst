"""Sentinel configuration service.

Manages data source and notification channel settings
from config/sentinel.yaml.

Per PRD v3.2 FR-HS005 + FR-SS003.
"""

from __future__ import annotations

from typing import Any

from src.utils.config import load_config, save_config
from src.utils.logger import get_logger

logger = get_logger("web.sentinel_config_service")


class SentinelConfigService:
    """Manages sentinel.yaml configuration for data sources and notifications."""

    def __init__(self) -> None:
        self._config = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            return load_config("sentinel")
        except FileNotFoundError:
            logger.warning("config/sentinel.yaml not found; using defaults")
            return {"data_sources": {}, "notifications": {}}

    def get_config(self) -> dict[str, Any]:
        """Return the full sentinel configuration."""
        return {
            "data_sources": self._config.get("data_sources", {}),
            "notifications": self._config.get("notifications", {}),
        }

    def update_config(self, updates: dict[str, Any]) -> None:
        """Update sentinel config and save to disk.

        Args:
            updates: Partial config dict to merge.
        """
        if "data_sources" in updates:
            self._config["data_sources"] = updates["data_sources"]
        if "notifications" in updates:
            self._config["notifications"] = updates["notifications"]

        try:
            save_config("sentinel", self._config)
            logger.info("Sentinel config saved")
        except Exception as exc:
            logger.error("Failed to save sentinel config: %s", exc)
            raise

    def reload(self) -> None:
        """Reload config from disk."""
        self._config = self._load()
