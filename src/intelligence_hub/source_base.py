"""Abstract base class for Intelligence Hub information sources.

Part of v21.0 Intelligence Hub.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.intelligence_hub.models import InfoItem


class InformationSource(ABC):
    """Base class for all information sources."""

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        self.source_id = source_id
        self.config = config
        self.display_name = config.get("display_name", source_id)
        self.default_category = config.get("default_category", "market")
        self.enabled = config.get("enabled", True)

    @abstractmethod
    def fetch(self) -> list[InfoItem]:
        """Fetch information items from this source.

        Returns:
            List of InfoItem from this source.
        """
