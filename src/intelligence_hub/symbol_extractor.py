"""Extract A-share stock symbols from news text.

Populates InfoItem.related_symbols during the aggregation pipeline.
Two extraction strategies:
  1. Regex — matches 6-digit A-share codes in text (600xxx, 000xxx, 300xxx, 688xxx, …)
  2. Name lookup — matches stock short-names against a code→name dictionary.

The dictionary is lazily loaded from akshare on first use and cached in-process.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from src.intelligence_hub.models import InfoItem

logger = logging.getLogger(__name__)

# Regex for 6-digit A-share stock codes.
# Shanghai Main: 600xxx, 601xxx, 603xxx, 605xxx
# Shanghai STAR: 688xxx, 689xxx
# Shenzhen Main: 000xxx, 001xxx
# Shenzhen SME: 002xxx, 003xxx
# Shenzhen ChiNext: 300xxx, 301xxx
_ASHARE_CODE_RE = re.compile(
    r"(?<!\d)"
    r"("
    r"6(?:0[0-9]|8[89])\d{3}"  # Shanghai
    r"|"
    r"(?:00[0-3]|30[01])\d{3}"  # Shenzhen
    r")"
    r"(?!\d)"
)

# Common index codes that should NOT be treated as stock symbols.
_INDEX_CODES = frozenset(
    {
        "000001",  # 上证指数
        "399001",  # 深证成指
        "399006",  # 创业板指
        "000300",  # 沪深300
        "000016",  # 上证50
        "000905",  # 中证500
        "000688",  # 科创50
    }
)

# Minimum stock name length to avoid false positives.
_MIN_NAME_LENGTH = 2

# Local cache for akshare stock names (survives container restarts).
_CACHE_PATH = Path("data/stock_names_cache.json")


class SymbolExtractor:
    """Extracts A-share stock symbols from text content."""

    def __init__(
        self,
        extra_names: dict[str, str] | None = None,
        *,
        load_akshare: bool = True,
    ) -> None:
        """
        Args:
            extra_names: Additional code→name mapping (e.g. from stocks.yaml watchlist).
            load_akshare: Whether to try loading the full A-share name list
                          from akshare on first use.
        """
        self._extra_names = extra_names or {}
        self._load_akshare = load_akshare
        self._name_to_codes: dict[str, list[str]] | None = None
        self._all_names: dict[str, str] | None = None  # code→name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, title: str, summary: str = "") -> list[str]:
        """Return deduplicated stock codes found in the given text."""
        text = f"{title} {summary}"
        codes: set[str] = set()

        # Strategy 1: regex for stock codes
        for match in _ASHARE_CODE_RE.finditer(text):
            code = match.group(1)
            if code not in _INDEX_CODES:
                codes.add(code)

        # Strategy 2: stock name lookup
        name_map = self._get_name_to_codes()
        for name, code_list in name_map.items():
            if name in text:
                codes.update(code_list)

        return sorted(codes)

    def extract_batch(self, items: list[InfoItem]) -> None:
        """Populate related_symbols for a batch of items (mutates in place)."""
        for item in items:
            found = self.extract(item.title, item.summary)
            if found:
                # Merge with any existing symbols (avoid duplicates)
                existing = set(item.related_symbols)
                existing.update(found)
                item.related_symbols = sorted(existing)

    # ------------------------------------------------------------------
    # Name dictionary
    # ------------------------------------------------------------------

    def _get_name_to_codes(self) -> dict[str, list[str]]:
        """Lazy-build the name→codes reverse mapping."""
        if self._name_to_codes is not None:
            return self._name_to_codes

        all_names = self._load_stock_names()
        self._all_names = all_names

        # Build reverse map: name → [code, ...]
        name_to_codes: dict[str, list[str]] = {}
        for code, name in all_names.items():
            if len(name) < _MIN_NAME_LENGTH:
                continue
            name_to_codes.setdefault(name, []).append(code)

        self._name_to_codes = name_to_codes
        logger.info(
            "SymbolExtractor: loaded %d stock names (%d from akshare, %d extra)",
            len(name_to_codes),
            len(all_names) - len(self._extra_names),
            len(self._extra_names),
        )
        return self._name_to_codes

    def _load_stock_names(self) -> dict[str, str]:
        """Load stock code→name dictionary from akshare + extra config.

        On successful akshare load, writes a local JSON cache. If akshare
        fails, falls back to the cached file so Docker containers still
        have name-based extraction.
        """
        names: dict[str, str] = {}

        # Try akshare first
        if self._load_akshare:
            try:
                import akshare as ak

                df = ak.stock_info_a_code_name()
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        code = str(row.get("code", ""))
                        name = str(row.get("name", ""))
                        if code and name and len(name) >= _MIN_NAME_LENGTH:
                            names[code] = name
                    logger.info(
                        "SymbolExtractor: loaded %d names from akshare", len(names)
                    )
                    self._save_cache(names)
            except Exception as exc:
                logger.warning("SymbolExtractor: akshare load failed: %s", exc)
                # Fallback to local cache
                cached = self._load_cache()
                if cached:
                    names = cached
                    logger.info(
                        "SymbolExtractor: loaded %d names from local cache",
                        len(names),
                    )

        # Merge extra names (config/watchlist overrides)
        names.update(self._extra_names)
        return names

    @staticmethod
    def _save_cache(names: dict[str, str]) -> None:
        """Persist akshare stock names to a local JSON file."""
        try:
            _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _CACHE_PATH.write_text(
                json.dumps(names, ensure_ascii=False), encoding="utf-8"
            )
            logger.debug("SymbolExtractor: saved %d names to cache", len(names))
        except Exception as exc:
            logger.warning("SymbolExtractor: cache save failed: %s", exc)

    @staticmethod
    def _load_cache() -> dict[str, str] | None:
        """Load stock names from local JSON cache, or None if unavailable."""
        try:
            if _CACHE_PATH.exists():
                data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data:
                    return data
        except Exception as exc:
            logger.warning("SymbolExtractor: cache load failed: %s", exc)
        return None

    def get_stock_name(self, code: str) -> str | None:
        """Look up a stock name by code."""
        if self._all_names is None:
            self._get_name_to_codes()
        return (self._all_names or {}).get(code)

    @staticmethod
    def build_extra_names(config: dict[str, Any]) -> dict[str, str]:
        """Build a code→name mapping from stocks.yaml watchlist section."""
        names: dict[str, str] = {}
        for item in config.get("watchlist", []):
            symbol = str(item.get("symbol", ""))
            name = str(item.get("name", ""))
            if symbol and name:
                names[symbol] = name
        return names
