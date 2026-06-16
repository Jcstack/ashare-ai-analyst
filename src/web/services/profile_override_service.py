"""Association profile override service.

Persists user customizations for stock association profiles to a JSON file
in data/processed/. Uses file-based storage (not Redis) so that data
survives Redis FLUSHALL during container restarts.

Per plan: profile overrides allow users to add/remove concepts, peers,
keywords, and override the industry tag for any stock.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from src.utils.config import get_data_dir
from src.utils.logger import get_logger

logger = get_logger("web.profile_override_service")

_FILE_NAME = "profile_overrides.json"


class ProfileOverrideService:
    """CRUD service for per-symbol association profile overrides.

    Data is stored in ``data/processed/profile_overrides.json``.
    Each key is a stock symbol, and the value is the override dict.
    """

    def __init__(self) -> None:
        self._path = self._resolve_path()
        self._cache: dict[str, Any] = self._load()

    @staticmethod
    def _resolve_path() -> Path:
        return get_data_dir("processed") / _FILE_NAME

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load profile overrides: %s", exc)
        return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Backup before overwrite
        if self._path.exists():
            backup = self._path.with_suffix(".json.bak")
            try:
                backup.write_bytes(self._path.read_bytes())
            except OSError:
                pass
        self._path.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_override(self, symbol: str) -> dict[str, Any] | None:
        """Get the override for a symbol, or None if not customized."""
        return self._cache.get(symbol)

    def set_override(self, symbol: str, overrides: dict[str, Any]) -> dict[str, Any]:
        """Merge overrides for a symbol and persist.

        Accepted keys:
        - added_concepts: list[{code, name}]
        - removed_concept_codes: list[str]
        - added_peers: list[{symbol, market, tags}]
        - removed_peer_symbols: list[str]
        - added_keywords: list[str]
        - removed_keywords: list[str]
        - industry_override: str | None

        Returns the full override dict for the symbol after merging.
        """
        existing = self._cache.get(symbol, {})

        allowed_keys = {
            "added_concepts",
            "removed_concept_codes",
            "added_peers",
            "removed_peer_symbols",
            "added_keywords",
            "removed_keywords",
            "industry_override",
        }

        for key in allowed_keys:
            if key in overrides:
                existing[key] = overrides[key]

        existing["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._cache[symbol] = existing
        self._save()
        return existing

    def delete_override(self, symbol: str) -> bool:
        """Remove all overrides for a symbol. Returns True if existed."""
        if symbol in self._cache:
            del self._cache[symbol]
            self._save()
            return True
        return False

    def list_overrides(self) -> dict[str, Any]:
        """Return all overrides (admin/debug)."""
        return dict(self._cache)
