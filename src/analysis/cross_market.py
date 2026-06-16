"""Cross-market correlation analyzer.

Per PRD v3.2 FR-GM004: analyze relationships between A-share holdings and
global markets (US/HK peers, commodities, indices).  Uses snapshot data from
GlobalMarketFetcher and mapping config from cross_market_map.yaml.
"""

import time
from typing import Any

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("analysis.cross_market")


class CrossMarketAnalyzer:
    """Assess cross-market impact on A-share stocks.

    Loads ``config/cross_market_map.yaml`` for stock→peer mappings, fetches
    peer performance via ``GlobalMarketFetcher``, and calculates per-stock
    cross-market impact scores.

    Args:
        global_fetcher: Optional pre-configured GlobalMarketFetcher instance.
    """

    def __init__(self, global_fetcher: Any = None) -> None:
        self._config = self._load_config()
        self._mappings: dict[str, dict] = self._config.get("mappings", {})
        self._default_peers: dict[str, list[str]] = self._config.get(
            "default_sector_peers", {}
        )
        self._global_fetcher = global_fetcher
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl: float = 1800.0  # 30min

    @staticmethod
    def _load_config() -> dict:
        try:
            return load_config("cross_market_map")
        except FileNotFoundError:
            logger.warning("cross_market_map.yaml not found; using empty config")
            return {}

    def get_mapping(self, symbol: str) -> dict[str, Any]:
        """Get cross-market mapping for a stock.

        Falls back to default sector peers if no explicit mapping.

        Args:
            symbol: 6-digit stock code.

        Returns:
            Mapping dict with us_peers, hk_peers, commodities, tags.
        """
        mapping = self._mappings.get(symbol)
        if mapping:
            return mapping

        # Fallback: empty mapping
        return {
            "us_peers": [],
            "hk_peers": [],
            "commodities": [],
            "tags": [],
        }

    def get_peer_symbols(self, symbol: str) -> list[str]:
        """Get all yfinance-compatible peer symbols for a stock.

        Args:
            symbol: 6-digit A-share stock code.

        Returns:
            List of yfinance ticker symbols.
        """
        mapping = self.get_mapping(symbol)
        peers: list[str] = []
        peers.extend(mapping.get("us_peers", []))
        peers.extend(mapping.get("hk_peers", []))
        peers.extend(mapping.get("commodities", []))
        return peers

    def get_default_peers_for_tag(self, tag: str) -> list[str]:
        """Get default sector peers by tag.

        Args:
            tag: Sector tag (e.g., 'entertainment', 'new_energy').

        Returns:
            List of peer symbols.
        """
        return self._default_peers.get(tag, [])

    def assess_cross_market_impact(
        self,
        symbol: str,
        *,
        global_snapshot: dict[str, Any] | None = None,
        peer_data: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Comprehensive cross-market impact assessment for a stock.

        Args:
            symbol: 6-digit A-share stock code.
            global_snapshot: Global market snapshot (indices/commodities/currencies).
            peer_data: Pre-fetched peer ticker data {symbol: {price, change, pct_change}}.

        Returns:
            Impact assessment dict with per-category analysis and overall score.
        """
        cache_key = f"impact_{symbol}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        mapping = self.get_mapping(symbol)
        tags = mapping.get("tags", [])

        # Fetch peer data if not provided and global_fetcher is available
        if peer_data is None and self._global_fetcher is not None:
            peer_data = self._fetch_peer_data(symbol, mapping)
        elif peer_data is None:
            peer_data = {}

        # US market impact
        us_peers = mapping.get("us_peers", [])
        us_analysis = self._analyze_peer_group(us_peers, peer_data, "us")

        # HK market impact
        hk_peers = mapping.get("hk_peers", [])
        hk_analysis = self._analyze_peer_group(hk_peers, peer_data, "hk")

        # Commodity impact
        commodities = mapping.get("commodities", [])
        commodity_analysis = self._analyze_peer_group(
            commodities, peer_data, "commodity"
        )

        # Index impact from global snapshot
        index_analysis = self._analyze_global_indices(global_snapshot)

        # Calculate combined impact score
        weights = {
            "us": 0.35 if us_peers else 0.0,
            "hk": 0.15 if hk_peers else 0.0,
            "commodity": 0.20 if commodities else 0.0,
            "index": 0.30,
        }
        # Redistribute weights for missing categories
        total_weight = sum(weights.values())
        if total_weight > 0:
            for key in weights:
                weights[key] /= total_weight

        scores = {
            "us": us_analysis.get("impact_score", 0.0),
            "hk": hk_analysis.get("impact_score", 0.0),
            "commodity": commodity_analysis.get("impact_score", 0.0),
            "index": index_analysis.get("impact_score", 0.0),
        }

        combined_score = sum(weights[k] * scores[k] for k in weights)
        direction = (
            "positive"
            if combined_score > 0.1
            else "negative"
            if combined_score < -0.1
            else "neutral"
        )

        result = {
            "symbol": symbol,
            "tags": tags,
            "us_market": us_analysis,
            "hk_market": hk_analysis,
            "commodity_exposure": commodity_analysis,
            "global_indices": index_analysis,
            "combined_impact_score": round(combined_score, 3),
            "impact_direction": direction,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        self._set_cached(cache_key, result)
        return result

    def assess_batch(
        self,
        symbols: list[str],
        *,
        global_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Batch assess cross-market impact for multiple stocks.

        Args:
            symbols: List of stock codes.
            global_snapshot: Shared global market snapshot.

        Returns:
            Dict mapping symbol → impact assessment.
        """
        # Collect all peer symbols to batch-fetch
        all_peers: set[str] = set()
        for sym in symbols:
            all_peers.update(self.get_peer_symbols(sym))

        peer_data = {}
        if all_peers and self._global_fetcher is not None:
            peer_data = self._global_fetcher._fetch_tickers(list(all_peers))

        results = {}
        for sym in symbols:
            results[sym] = self.assess_cross_market_impact(
                sym,
                global_snapshot=global_snapshot,
                peer_data=peer_data,
            )
        return results

    def _fetch_peer_data(
        self, symbol: str, mapping: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        """Fetch peer ticker data via GlobalMarketFetcher."""
        peers = self.get_peer_symbols(symbol)
        tags = mapping.get("tags", [])

        # Also include default sector peers for tags
        for tag in tags:
            for peer in self.get_default_peers_for_tag(tag):
                if peer not in peers:
                    peers.append(peer)

        if not peers or self._global_fetcher is None:
            return {}

        try:
            return self._global_fetcher._fetch_tickers(peers)
        except Exception as exc:
            logger.warning("Failed to fetch peer data for %s: %s", symbol, exc)
            return {}

    @staticmethod
    def _analyze_peer_group(
        peer_symbols: list[str],
        peer_data: dict[str, dict[str, Any]],
        category: str,
    ) -> dict[str, Any]:
        """Analyze impact from a group of peer tickers.

        Args:
            peer_symbols: List of yfinance symbols.
            peer_data: Fetched data for peers.
            category: Category label ('us', 'hk', 'commodity').

        Returns:
            Analysis dict with trend, peers list, and impact_score.
        """
        if not peer_symbols:
            return {
                "trend": "neutral",
                "peers": [],
                "impact_score": 0.0,
                "summary": f"无{category}关联标的",
            }

        peer_results = []
        total_pct = 0.0
        count = 0

        for sym in peer_symbols:
            data = peer_data.get(sym, {})
            pct = data.get("pct_change", 0.0)
            if data:
                peer_results.append(
                    {
                        "symbol": sym,
                        "price": data.get("price"),
                        "pct_change": pct,
                    }
                )
                if pct is not None:
                    total_pct += pct
                    count += 1

        avg_pct = total_pct / count if count > 0 else 0.0

        if avg_pct > 0.5:
            trend = "positive"
        elif avg_pct < -0.5:
            trend = "negative"
        else:
            trend = "neutral"

        # Impact score: normalized avg_pct to roughly -1 ~ +1 range
        impact_score = max(-1.0, min(1.0, avg_pct / 5.0))

        return {
            "trend": trend,
            "peers": peer_results,
            "impact_score": round(impact_score, 3),
            "avg_pct_change": round(avg_pct, 2),
        }

    @staticmethod
    def _analyze_global_indices(
        snapshot: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Analyze global index trends from snapshot.

        Args:
            snapshot: Global market snapshot with indices.

        Returns:
            Analysis dict with trend and impact_score.
        """
        if not snapshot:
            return {
                "trend": "neutral",
                "summary": "无全球指数数据",
                "impact_score": 0.0,
            }

        indices = snapshot.get("indices", [])
        if not indices:
            return {
                "trend": "neutral",
                "summary": "无全球指数数据",
                "impact_score": 0.0,
            }

        total_pct = 0.0
        count = 0
        summary_parts = []

        for idx in indices:
            pct = idx.get("pct_change")
            if pct is not None:
                total_pct += pct
                count += 1
                name = idx.get("name", idx.get("symbol", ""))
                summary_parts.append(f"{name}: {pct:+.2f}%")

        avg_pct = total_pct / count if count > 0 else 0.0

        if avg_pct > 0.3:
            trend = "positive"
        elif avg_pct < -0.3:
            trend = "negative"
        else:
            trend = "neutral"

        return {
            "trend": trend,
            "summary": " | ".join(summary_parts[:6]),
            "impact_score": round(max(-1.0, min(1.0, avg_pct / 3.0)), 3),
            "avg_pct_change": round(avg_pct, 2),
        }

    def _get_cached(self, key: str) -> Any | None:
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                return data
        return None

    def _set_cached(self, key: str, data: Any) -> None:
        self._cache[key] = (time.time(), data)
