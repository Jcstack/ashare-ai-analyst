"""Unit tests for the temporal Knowledge Graph (PRD v50.0 SS 6.4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.intelligence.knowledge_graph import KnowledgeGraph


@pytest.fixture()
def kg() -> KnowledgeGraph:
    """Return a fresh KnowledgeGraph instance."""
    return KnowledgeGraph()


# ------------------------------------------------------------------
# Node operations
# ------------------------------------------------------------------


class TestAddStock:
    def test_basic_add(self, kg: KnowledgeGraph) -> None:
        kg.add_stock("600519", name="贵州茅台", sector="白酒")
        stats = kg.stats()
        assert stats["nodes_by_type"]["stock"] == 1

    def test_add_stock_with_sector_creates_edge(self, kg: KnowledgeGraph) -> None:
        kg.add_sector("白酒", name="白酒")
        kg.add_stock("600519", name="贵州茅台", sector="白酒")
        stocks = kg.get_sector_stocks("白酒")
        assert "600519" in stocks

    def test_update_existing_stock(self, kg: KnowledgeGraph) -> None:
        kg.add_stock("600519", name="贵州茅台")
        kg.add_stock("600519", name="贵州茅台 (updated)")
        stats = kg.stats()
        assert stats["nodes_by_type"]["stock"] == 1


class TestAddEvent:
    def test_basic_event(self, kg: KnowledgeGraph) -> None:
        kg.add_event("evt-001", title="降准", event_type="policy", severity=0.8)
        events = kg.get_active_events()
        assert len(events) == 1
        assert events[0]["title"] == "降准"

    def test_expired_event_not_active(self, kg: KnowledgeGraph) -> None:
        past = datetime.now(UTC) - timedelta(hours=48)
        kg.add_event(
            "evt-old",
            title="Old",
            event_type="news",
            severity=0.3,
            valid_until=past,
        )
        assert len(kg.get_active_events()) == 0


class TestAddThesis:
    def test_thesis_links_to_stock(self, kg: KnowledgeGraph) -> None:
        kg.add_stock("000001", name="平安银行")
        kg.add_thesis(
            thesis_id="th-001",
            symbol="000001",
            narrative="银行板块修复",
            confidence=0.75,
        )
        stats = kg.stats()
        assert stats["nodes_by_type"]["thesis"] == 1
        assert "thesis_for" in stats["edges_by_relation"]


# ------------------------------------------------------------------
# Edge operations
# ------------------------------------------------------------------


class TestAddEdge:
    def test_affected_by(self, kg: KnowledgeGraph) -> None:
        kg.add_stock("600519")
        kg.add_event("evt-001", title="降准", event_type="policy", severity=0.8)
        kg.add_edge("600519", "evt-001", relation="affected_by", confidence=0.7)
        affected = kg.get_affected_stocks("evt-001")
        assert len(affected) == 1
        assert affected[0]["symbol"] == "600519"

    def test_supports_edge(self, kg: KnowledgeGraph) -> None:
        kg.add_thesis("th-001", symbol="000001", narrative="test", confidence=0.6)
        kg.add_event("evt-001", title="证据1", event_type="news", severity=0.5)
        kg.add_edge("evt-001", "th-001", relation="supports", confidence=0.8)
        evidence = kg.get_thesis_evidence("th-001")
        assert len(evidence) == 1
        assert evidence[0]["evidence_id"] == "evt-001"


class TestCorrelatedStocks:
    def test_correlation_query(self, kg: KnowledgeGraph) -> None:
        kg.add_stock("600519")
        kg.add_stock("000858")
        kg.add_edge("600519", "000858", relation="correlated_with", confidence=0.85)
        correlated = kg.get_correlated_stocks("600519", min_correlation=0.5)
        assert len(correlated) == 1
        assert correlated[0]["symbol"] == "000858"
        assert correlated[0]["correlation"] == pytest.approx(0.85)

    def test_below_threshold_excluded(self, kg: KnowledgeGraph) -> None:
        kg.add_stock("600519")
        kg.add_stock("000858")
        kg.add_edge("600519", "000858", relation="correlated_with", confidence=0.3)
        assert len(kg.get_correlated_stocks("600519", min_correlation=0.5)) == 0


# ------------------------------------------------------------------
# get_stock_events
# ------------------------------------------------------------------


class TestGetStockEvents:
    def test_recent_events(self, kg: KnowledgeGraph) -> None:
        kg.add_stock("600519")
        kg.add_event("evt-001", title="利好", event_type="news", severity=0.6)
        kg.add_edge("600519", "evt-001", relation="affected_by", confidence=0.7)
        events = kg.get_stock_events("600519", hours=24)
        assert len(events) == 1
        assert events[0]["event_id"] == "evt-001"

    def test_missing_stock_returns_empty(self, kg: KnowledgeGraph) -> None:
        assert kg.get_stock_events("NONEXISTENT") == []


# ------------------------------------------------------------------
# Maintenance: prune_expired
# ------------------------------------------------------------------


class TestPruneExpired:
    def test_removes_expired_edges(self, kg: KnowledgeGraph) -> None:
        kg.add_stock("600519")
        kg.add_event("evt-001", title="X", event_type="news", severity=0.5)
        past = datetime.now(UTC) - timedelta(hours=1)
        kg.add_edge(
            "600519",
            "evt-001",
            relation="affected_by",
            confidence=0.7,
            valid_until=past,
        )
        removed = kg.prune_expired()
        assert removed == 1
        assert kg.stats()["total_edges"] == 0

    def test_keeps_valid_edges(self, kg: KnowledgeGraph) -> None:
        kg.add_stock("600519")
        kg.add_event("evt-001", title="X", event_type="news", severity=0.5)
        future = datetime.now(UTC) + timedelta(hours=24)
        kg.add_edge(
            "600519",
            "evt-001",
            relation="affected_by",
            confidence=0.7,
            valid_until=future,
        )
        removed = kg.prune_expired()
        assert removed == 0
        assert kg.stats()["total_edges"] == 1

    def test_keeps_permanent_edges(self, kg: KnowledgeGraph) -> None:
        kg.add_stock("600519")
        kg.add_sector("白酒", name="白酒")
        kg.add_edge(
            "600519",
            "白酒",
            relation="belongs_to",
            confidence=1.0,
            valid_until=None,
        )
        removed = kg.prune_expired()
        assert removed == 0


# ------------------------------------------------------------------
# Maintenance: decay_edges
# ------------------------------------------------------------------


class TestDecayEdges:
    def test_decays_confidence(self, kg: KnowledgeGraph) -> None:
        kg.add_stock("600519")
        kg.add_event("evt-001", title="X", event_type="news", severity=0.5)
        # Backdate valid_from to 5 days ago, decay 0.1/day => 0.5 lost
        past = datetime.now(UTC) - timedelta(days=5)
        kg.add_edge(
            "600519",
            "evt-001",
            relation="affected_by",
            confidence=1.0,
            valid_from=past,
            decay_rate=0.1,
        )
        affected = kg.decay_edges()
        assert affected == 1
        # After decay: 1.0 - 0.1*5 = 0.5
        edge_data = kg._graph.edges["600519", "evt-001"]
        assert edge_data["confidence"] == pytest.approx(0.5, abs=0.05)

    def test_removes_below_threshold(self, kg: KnowledgeGraph) -> None:
        kg.add_stock("600519")
        kg.add_event("evt-001", title="X", event_type="news", severity=0.5)
        # Backdate 20 days ago, decay 0.1/day => 1.0 - 2.0 = 0 => removed
        past = datetime.now(UTC) - timedelta(days=20)
        kg.add_edge(
            "600519",
            "evt-001",
            relation="affected_by",
            confidence=1.0,
            valid_from=past,
            decay_rate=0.1,
        )
        affected = kg.decay_edges()
        assert affected == 1
        assert kg.stats()["total_edges"] == 0

    def test_no_decay_for_zero_rate(self, kg: KnowledgeGraph) -> None:
        kg.add_stock("600519")
        kg.add_sector("白酒", name="白酒")
        past = datetime.now(UTC) - timedelta(days=100)
        kg.add_edge(
            "600519",
            "白酒",
            relation="belongs_to",
            confidence=1.0,
            valid_from=past,
            decay_rate=0.0,
        )
        affected = kg.decay_edges()
        assert affected == 0
        assert kg.stats()["total_edges"] == 1


# ------------------------------------------------------------------
# Serialization & stats
# ------------------------------------------------------------------


class TestStats:
    def test_empty_graph(self, kg: KnowledgeGraph) -> None:
        stats = kg.stats()
        assert stats["total_nodes"] == 0
        assert stats["total_edges"] == 0

    def test_counts_by_type(self, kg: KnowledgeGraph) -> None:
        kg.add_stock("600519", name="贵州茅台")
        kg.add_stock("000858", name="五粮液")
        kg.add_sector("白酒", name="白酒")
        kg.add_event("evt-001", title="X", event_type="news", severity=0.5)
        stats = kg.stats()
        assert stats["nodes_by_type"]["stock"] == 2
        assert stats["nodes_by_type"]["sector"] == 1
        assert stats["nodes_by_type"]["event"] == 1
        assert stats["total_nodes"] == 4


class TestToDict:
    def test_serialization(self, kg: KnowledgeGraph) -> None:
        kg.add_stock("600519", name="贵州茅台")
        kg.add_event("evt-001", title="X", event_type="news", severity=0.5)
        kg.add_edge("600519", "evt-001", relation="affected_by", confidence=0.7)
        result = kg.to_dict()
        assert len(result["nodes"]) == 2
        assert len(result["edges"]) == 1
        assert "stats" in result
