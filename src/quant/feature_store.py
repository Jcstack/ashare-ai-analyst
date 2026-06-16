"""In-memory feature store with TTL-based cache management.

Stores computed feature values (momentum, volatility, volume metrics)
per symbol with automatic expiry. Designed as a lightweight in-process
cache; Redis integration can be added later if needed.

Part of v15.0 Quant Core layer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("quant.feature_store")


@dataclass
class FeatureDefinition:
    """Definition of a computed feature.

    Attributes:
        name: Feature identifier (e.g. "rsi_14").
        category: Feature category (momentum, volatility, etc.).
        version: Feature version for cache key namespacing.
        description: Human-readable description.
        params: Parameters used to compute the feature.
    """

    name: str
    category: str
    version: str = "v1"
    description: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class FeatureValue:
    """A cached feature value with metadata.

    Attributes:
        definition: Feature definition.
        symbol: Stock symbol.
        value: Computed feature value (scalar or dict).
        computed_at: Unix timestamp when the feature was computed.
        expires_at: Unix timestamp when the cache entry expires.
    """

    definition: FeatureDefinition
    symbol: str
    value: Any
    computed_at: float = 0.0
    expires_at: float = 0.0


class FeatureStore:
    """In-memory feature cache with TTL management.

    Usage::

        store = FeatureStore()
        definition = FeatureDefinition(name="rsi_14", category="momentum")
        store.put("600519", definition, value=45.2)
        result = store.get("600519", "rsi_14")
        if result is not None:
            print(result.value)
    """

    def __init__(self) -> None:
        cfg = load_config("quant").get("feature_store", {})
        self.default_ttl = cfg.get("default_ttl_seconds", 3600)
        self.max_features_per_symbol = cfg.get("max_features_per_symbol", 50)
        self.version_prefix = cfg.get("version_prefix", "v1")
        self.categories: list[str] = cfg.get(
            "categories",
            ["momentum", "mean_reversion", "volatility", "volume", "technical"],
        )

        # Cache: key = "{symbol}:{feature_name}:{version}"
        self._cache: dict[str, FeatureValue] = {}

    def _cache_key(self, symbol: str, name: str, version: str | None = None) -> str:
        """Build cache key."""
        v = version or self.version_prefix
        return f"{symbol}:{name}:{v}"

    def put(
        self,
        symbol: str,
        definition: FeatureDefinition,
        value: Any,
        ttl: int | None = None,
    ) -> FeatureValue:
        """Store a feature value.

        Args:
            symbol: Stock symbol.
            definition: Feature definition.
            value: Computed value.
            ttl: Time-to-live in seconds (defaults to config default).

        Returns:
            The stored FeatureValue.
        """
        now = time.time()
        ttl_seconds = ttl if ttl is not None else self.default_ttl
        key = self._cache_key(symbol, definition.name, definition.version)

        # Enforce per-symbol limit
        symbol_prefix = f"{symbol}:"
        symbol_count = sum(1 for k in self._cache if k.startswith(symbol_prefix))
        if symbol_count >= self.max_features_per_symbol and key not in self._cache:
            self._evict_oldest(symbol)

        fv = FeatureValue(
            definition=definition,
            symbol=symbol,
            value=value,
            computed_at=now,
            expires_at=now + ttl_seconds,
        )
        self._cache[key] = fv
        logger.debug(
            "Stored feature %s for %s (TTL=%ds)", definition.name, symbol, ttl_seconds
        )
        return fv

    def get(
        self,
        symbol: str,
        name: str,
        version: str | None = None,
    ) -> FeatureValue | None:
        """Retrieve a feature value if it exists and hasn't expired.

        Args:
            symbol: Stock symbol.
            name: Feature name.
            version: Feature version (defaults to config version_prefix).

        Returns:
            FeatureValue if found and valid, None otherwise.
        """
        key = self._cache_key(symbol, name, version)
        fv = self._cache.get(key)
        if fv is None:
            return None
        if time.time() > fv.expires_at:
            del self._cache[key]
            return None
        return fv

    def get_all(self, symbol: str) -> list[FeatureValue]:
        """Get all non-expired features for a symbol.

        Args:
            symbol: Stock symbol.

        Returns:
            List of valid FeatureValues.
        """
        now = time.time()
        prefix = f"{symbol}:"
        result: list[FeatureValue] = []
        expired_keys: list[str] = []

        for key, fv in self._cache.items():
            if key.startswith(prefix):
                if now > fv.expires_at:
                    expired_keys.append(key)
                else:
                    result.append(fv)

        for key in expired_keys:
            del self._cache[key]

        return result

    def get_by_category(self, symbol: str, category: str) -> list[FeatureValue]:
        """Get all features for a symbol in a given category.

        Args:
            symbol: Stock symbol.
            category: Feature category (e.g. "momentum").

        Returns:
            List of matching FeatureValues.
        """
        all_features = self.get_all(symbol)
        return [fv for fv in all_features if fv.definition.category == category]

    def invalidate(self, symbol: str, name: str | None = None) -> int:
        """Remove cached features.

        Args:
            symbol: Stock symbol.
            name: Specific feature name, or None to invalidate all for symbol.

        Returns:
            Number of entries removed.
        """
        if name is not None:
            key = self._cache_key(symbol, name)
            if key in self._cache:
                del self._cache[key]
                return 1
            return 0

        prefix = f"{symbol}:"
        keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
        for key in keys_to_remove:
            del self._cache[key]
        return len(keys_to_remove)

    def cleanup_expired(self) -> int:
        """Remove all expired entries across all symbols.

        Returns:
            Number of entries removed.
        """
        now = time.time()
        expired = [k for k, v in self._cache.items() if now > v.expires_at]
        for key in expired:
            del self._cache[key]
        return len(expired)

    def stats(self) -> dict[str, Any]:
        """Return cache statistics.

        Returns:
            Dict with total entries, symbols count, and category breakdown.
        """
        now = time.time()
        valid = {k: v for k, v in self._cache.items() if now <= v.expires_at}
        symbols = set()
        categories: dict[str, int] = {}
        for fv in valid.values():
            symbols.add(fv.symbol)
            cat = fv.definition.category
            categories[cat] = categories.get(cat, 0) + 1

        return {
            "total_entries": len(valid),
            "total_expired": len(self._cache) - len(valid),
            "symbols": len(symbols),
            "categories": categories,
        }

    def _evict_oldest(self, symbol: str) -> None:
        """Evict the oldest feature for a symbol to make room."""
        prefix = f"{symbol}:"
        oldest_key: str | None = None
        oldest_time = float("inf")

        for key, fv in self._cache.items():
            if key.startswith(prefix) and fv.computed_at < oldest_time:
                oldest_time = fv.computed_at
                oldest_key = key

        if oldest_key is not None:
            del self._cache[oldest_key]
