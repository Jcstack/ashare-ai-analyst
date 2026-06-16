"""Tests for CompetitorBenchmark."""

from __future__ import annotations

import pytest

from src.intelligence.competitor_benchmark import (
    CompetitorBenchmark,
    PeerComparison,
)


@pytest.fixture
def bench():
    return CompetitorBenchmark()


class TestFindPeers:
    def test_known_symbol_returns_peers(self, bench):
        peers = bench.find_peers("600519")
        assert len(peers) >= 2
        # Should not include self
        assert all(p["symbol"] != "600519" for p in peers)
        # All peers belong to same sector
        assert all(p["sector"] == "消费" for p in peers)

    def test_unknown_symbol_returns_empty(self, bench):
        peers = bench.find_peers("999999")
        assert peers == []

    def test_name_based_sector_resolution(self, bench):
        """Name containing a sector keyword should resolve."""
        peers = bench.find_peers("999999", name="黄金ETF")
        # Should find peers in 黄金 sector
        assert len(peers) >= 1
        assert all(p["sector"] == "黄金" for p in peers)


class TestCompare:
    def test_known_stock_returns_comparison(self, bench):
        result = bench.compare("600519", "贵州茅台", current_price=1800.0)
        assert result is not None
        assert isinstance(result, PeerComparison)
        assert result.symbol == "600519"
        assert result.sector == "消费"
        assert result.peer_count >= 3
        assert 1 <= result.rank_in_peers <= result.peer_count
        assert result.metrics["current_price"] == 1800.0

    def test_unknown_stock_returns_none(self, bench):
        result = bench.compare("999999", "不存在的股票")
        assert result is None

    def test_leader_has_strengths(self, bench):
        result = bench.compare("600519", "贵州茅台")
        assert result is not None
        assert any("龙头" in s for s in result.strengths)

    def test_non_leader_has_weakness(self, bench):
        # 603369 今世缘 is not in _STOCK_TRAITS, so not a leader
        result = bench.compare("603369", "今世缘")
        assert result is not None
        assert any("非板块龙头" in w for w in result.weaknesses)

    def test_sector_cycle_in_metrics(self, bench):
        result = bench.compare("601398", "工商银行")
        assert result is not None
        assert result.metrics["sector_cycle"] == "顺周期"
        assert result.metrics["policy_sensitive"] is True

    def test_no_price_omits_price_metric(self, bench):
        result = bench.compare("600036", "招商银行")
        assert result is not None
        assert "current_price" not in result.metrics


class TestToDict:
    def test_to_dict_keys(self, bench):
        result = bench.compare("600489", "中金黄金")
        assert result is not None
        d = result.to_dict()
        expected_keys = {
            "symbol",
            "name",
            "sector",
            "metrics",
            "rank_in_peers",
            "peer_count",
            "strengths",
            "weaknesses",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_returns_new_lists(self, bench):
        result = bench.compare("600489", "中金黄金")
        assert result is not None
        d = result.to_dict()
        # Mutating the returned list should not affect the original
        d["strengths"].append("test")
        assert "test" not in result.strengths


class TestRanking:
    def test_leader_ranks_higher(self, bench):
        leader = bench.compare("600519", "贵州茅台")
        follower = bench.compare("603369", "今世缘")
        assert leader is not None
        assert follower is not None
        # Leader should have a better (lower) rank
        assert leader.rank_in_peers < follower.rank_in_peers
