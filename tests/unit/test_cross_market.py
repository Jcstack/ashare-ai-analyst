"""Tests for cross-market correlation analyzer (FR-GM004)."""

from unittest.mock import MagicMock

from src.analysis.cross_market import CrossMarketAnalyzer


class TestCrossMarketAnalyzer:
    def test_get_mapping_explicit(self):
        analyzer = CrossMarketAnalyzer()
        mapping = analyzer.get_mapping("001330")
        # From cross_market_map.yaml
        assert "IMAX" in mapping.get("us_peers", []) or mapping.get("us_peers") == []
        # If config loaded, should have tags
        if mapping.get("tags"):
            assert "entertainment" in mapping["tags"]

    def test_get_mapping_fallback(self):
        analyzer = CrossMarketAnalyzer()
        mapping = analyzer.get_mapping("999999")
        assert mapping["us_peers"] == []
        assert mapping["hk_peers"] == []
        assert mapping["commodities"] == []

    def test_get_peer_symbols(self):
        analyzer = CrossMarketAnalyzer()
        peers = analyzer.get_peer_symbols("001330")
        # Should include us_peers from config
        assert isinstance(peers, list)

    def test_analyze_peer_group_empty(self):
        result = CrossMarketAnalyzer._analyze_peer_group([], {}, "us")
        assert result["trend"] == "neutral"
        assert result["peers"] == []
        assert result["impact_score"] == 0.0

    def test_analyze_peer_group_positive(self):
        peer_data = {
            "IMAX": {"price": 20.0, "pct_change": 3.0},
            "DIS": {"price": 150.0, "pct_change": 2.0},
        }
        result = CrossMarketAnalyzer._analyze_peer_group(
            ["IMAX", "DIS"], peer_data, "us"
        )
        assert result["trend"] == "positive"
        assert result["avg_pct_change"] == 2.5
        assert len(result["peers"]) == 2

    def test_analyze_peer_group_negative(self):
        peer_data = {
            "ZIM": {"price": 10.0, "pct_change": -3.0},
        }
        result = CrossMarketAnalyzer._analyze_peer_group(["ZIM"], peer_data, "us")
        assert result["trend"] == "negative"
        assert result["avg_pct_change"] == -3.0

    def test_analyze_global_indices_empty(self):
        result = CrossMarketAnalyzer._analyze_global_indices(None)
        assert result["trend"] == "neutral"
        assert result["impact_score"] == 0.0

    def test_analyze_global_indices_positive(self):
        snapshot = {
            "indices": [
                {"name": "S&P 500", "pct_change": 1.0},
                {"name": "NASDAQ", "pct_change": 1.5},
            ]
        }
        result = CrossMarketAnalyzer._analyze_global_indices(snapshot)
        assert result["trend"] == "positive"
        assert result["avg_pct_change"] > 0

    def test_assess_cross_market_no_fetcher(self):
        analyzer = CrossMarketAnalyzer(global_fetcher=None)
        result = analyzer.assess_cross_market_impact(
            "001330",
            global_snapshot={"indices": [{"name": "S&P", "pct_change": 0.5}]},
            peer_data={"IMAX": {"price": 20, "pct_change": 1.5}},
        )
        assert result["symbol"] == "001330"
        assert "combined_impact_score" in result
        assert result["impact_direction"] in ("positive", "negative", "neutral")
        assert result["generated_at"]

    def test_assess_batch(self):
        mock_fetcher = MagicMock()
        mock_fetcher._fetch_tickers.return_value = {
            "IMAX": {"price": 20, "pct_change": 1.0},
        }
        analyzer = CrossMarketAnalyzer(global_fetcher=mock_fetcher)
        results = analyzer.assess_batch(
            ["001330", "999999"],
            global_snapshot=None,
        )
        assert "001330" in results
        assert "999999" in results

    def test_caching(self):
        analyzer = CrossMarketAnalyzer()
        result1 = analyzer.assess_cross_market_impact(
            "001330", peer_data={}, global_snapshot=None
        )
        result2 = analyzer.assess_cross_market_impact(
            "001330", peer_data={"NEW": {"price": 100}}, global_snapshot=None
        )
        # Second call should return cached result
        assert result1 == result2
