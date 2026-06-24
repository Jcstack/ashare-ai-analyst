"""Knowledge Graph — temporal entity-relationship world model.

Per PRD v50.0 SS 6.4: lightweight NetworkX graph storing stocks, sectors,
events, theses, and their relationships with temporal validity.

Used by intelligence pipeline (write), signal engine (read), and
portfolio manager (read).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import networkx as nx
from networkx.readwrite import json_graph

from src.utils.logger import get_logger

logger = get_logger("intelligence.knowledge_graph")

_DEFAULT_DB_PATH = "data/knowledge_graph.db"

# Default temporal validity by node type
_DEFAULT_VALIDITY: dict[str, timedelta | None] = {
    "event": timedelta(hours=24),
    "thesis": timedelta(days=5),
    "sector": None,  # permanent
    "stock": None,  # permanent
    "policy": timedelta(days=30),
    "person": None,  # permanent
}


class KnowledgeGraph:
    """Temporal knowledge graph with automatic edge decay.

    Nodes have a ``node_type`` attribute: stock, sector, event, policy,
    person, thesis.  Edges have temporal attributes: valid_from,
    valid_until, decay_rate, confidence.
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._graph = nx.DiGraph()
        self._lock = threading.Lock()
        self._db_path = db_path
        self._dirty = False
        self._write_count = 0
        self._load_from_db()

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

    def add_stock(self, symbol: str, name: str = "", sector: str = "") -> None:
        """Add or update a stock node."""
        with self._lock:
            self._graph.add_node(
                symbol,
                node_type="stock",
                name=name,
                sector=sector,
                updated_at=datetime.now(UTC).isoformat(),
            )
            if sector:
                self._ensure_edge(
                    symbol,
                    sector,
                    relation="belongs_to",
                    confidence=1.0,
                )
            self._persist()

    def add_sector(self, sector_id: str, name: str) -> None:
        """Add or update a sector node."""
        with self._lock:
            self._graph.add_node(
                sector_id,
                node_type="sector",
                name=name,
                updated_at=datetime.now(UTC).isoformat(),
            )
            self._persist()

    def add_event(
        self,
        event_id: str,
        title: str,
        event_type: str,
        severity: float,
        valid_until: datetime | None = None,
    ) -> None:
        """Add an event node with temporal validity."""
        now = datetime.now(UTC)
        if valid_until is None:
            valid_until = now + _DEFAULT_VALIDITY["event"]  # type: ignore[operator]
        with self._lock:
            self._graph.add_node(
                event_id,
                node_type="event",
                title=title,
                event_type=event_type,
                severity=severity,
                created_at=now.isoformat(),
                valid_until=valid_until.isoformat(),
                updated_at=now.isoformat(),
            )
            self._persist()

    def add_thesis(
        self,
        thesis_id: str,
        symbol: str,
        narrative: str,
        confidence: float,
        expires_at: datetime | None = None,
    ) -> None:
        """Add a thesis node linked to its stock."""
        now = datetime.now(UTC)
        if expires_at is None:
            expires_at = now + _DEFAULT_VALIDITY["thesis"]  # type: ignore[operator]
        with self._lock:
            self._graph.add_node(
                thesis_id,
                node_type="thesis",
                narrative=narrative,
                confidence=confidence,
                created_at=now.isoformat(),
                expires_at=expires_at.isoformat(),
                updated_at=now.isoformat(),
            )
            # Link thesis to its stock
            self._ensure_edge(
                thesis_id,
                symbol,
                relation="thesis_for",
                confidence=confidence,
            )
            self._persist()

    def add_policy(
        self,
        policy_id: str,
        title: str,
        severity: float = 0.5,
        valid_until: datetime | None = None,
    ) -> None:
        """Add a policy node with temporal validity."""
        now = datetime.now(UTC)
        if valid_until is None:
            valid_until = now + _DEFAULT_VALIDITY["policy"]  # type: ignore[operator]
        with self._lock:
            self._graph.add_node(
                policy_id,
                node_type="policy",
                title=title,
                severity=severity,
                created_at=now.isoformat(),
                valid_until=valid_until.isoformat(),
                updated_at=now.isoformat(),
            )
            self._persist()

    def add_person(self, person_id: str, name: str, role: str = "") -> None:
        """Add a person node (key holder / hot money operator)."""
        with self._lock:
            self._graph.add_node(
                person_id,
                node_type="person",
                name=name,
                role=role,
                updated_at=datetime.now(UTC).isoformat(),
            )
            self._persist()

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    def add_edge(
        self,
        source: str,
        target: str,
        relation: str,
        confidence: float = 1.0,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        decay_rate: float = 0.0,
        **metadata: Any,
    ) -> None:
        """Add a typed, temporal edge.

        Args:
            source: Source node id.
            target: Target node id.
            relation: Edge type (e.g. ``affected_by``, ``belongs_to``).
            confidence: Edge confidence in [0, 1].
            valid_from: Start of temporal validity (default: now).
            valid_until: End of temporal validity (default: None = permanent).
            decay_rate: Confidence decay per day since valid_from.
            **metadata: Arbitrary extra edge attributes.
        """
        now = datetime.now(UTC)
        if valid_from is None:
            valid_from = now

        with self._lock:
            self._graph.add_edge(
                source,
                target,
                relation=relation,
                confidence=confidence,
                valid_from=valid_from.isoformat(),
                valid_until=valid_until.isoformat() if valid_until else None,
                decay_rate=decay_rate,
                created_at=now.isoformat(),
                **metadata,
            )
            self._persist()

    # ------------------------------------------------------------------
    # Query operations
    # ------------------------------------------------------------------

    def get_affected_stocks(self, event_id: str) -> list[dict[str, Any]]:
        """Get stocks affected by an event (via ``affected_by`` edges)."""
        results: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        with self._lock:
            # affected_by goes from stock -> event, so we look at predecessors
            if event_id not in self._graph:
                return results
            for pred in self._graph.predecessors(event_id):
                edge = self._graph.edges[pred, event_id]
                if edge.get("relation") != "affected_by":
                    continue
                if not self._is_edge_valid(edge, now):
                    continue
                node_data = dict(self._graph.nodes[pred])
                if node_data.get("node_type") != "stock":
                    continue
                results.append(
                    {
                        "symbol": pred,
                        "confidence": self._effective_confidence(edge, now),
                        **node_data,
                    }
                )
        return results

    def get_stock_events(self, symbol: str, hours: int = 24) -> list[dict[str, Any]]:
        """Get recent events affecting a stock."""
        results: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=hours)
        with self._lock:
            if symbol not in self._graph:
                return results
            for succ in self._graph.successors(symbol):
                edge = self._graph.edges[symbol, succ]
                if edge.get("relation") != "affected_by":
                    continue
                node_data = dict(self._graph.nodes[succ])
                if node_data.get("node_type") != "event":
                    continue
                # Check recency
                created = node_data.get("created_at", "")
                if created:
                    try:
                        created_dt = datetime.fromisoformat(created)
                        if created_dt < cutoff:
                            continue
                    except (ValueError, TypeError):
                        pass
                results.append(
                    {
                        "event_id": succ,
                        "confidence": self._effective_confidence(edge, now),
                        **node_data,
                    }
                )
        return results

    def get_sector_stocks(self, sector: str) -> list[str]:
        """Get all stocks in a sector."""
        stocks: list[str] = []
        with self._lock:
            if sector not in self._graph:
                return stocks
            for pred in self._graph.predecessors(sector):
                edge = self._graph.edges[pred, sector]
                if edge.get("relation") != "belongs_to":
                    continue
                node_data = self._graph.nodes[pred]
                if node_data.get("node_type") == "stock":
                    stocks.append(pred)
        return stocks

    def get_correlated_stocks(
        self, symbol: str, min_correlation: float = 0.5
    ) -> list[dict[str, Any]]:
        """Get stocks correlated with given symbol."""
        results: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        with self._lock:
            if symbol not in self._graph:
                return results
            # Check both directions for correlated_with
            for neighbor in list(self._graph.successors(symbol)) + list(
                self._graph.predecessors(symbol)
            ):
                # Get the edge in whichever direction it exists
                if self._graph.has_edge(symbol, neighbor):
                    edge = self._graph.edges[symbol, neighbor]
                elif self._graph.has_edge(neighbor, symbol):
                    edge = self._graph.edges[neighbor, symbol]
                else:
                    continue

                if edge.get("relation") != "correlated_with":
                    continue
                if not self._is_edge_valid(edge, now):
                    continue
                eff_conf = self._effective_confidence(edge, now)
                if eff_conf < min_correlation:
                    continue
                node_data = dict(self._graph.nodes.get(neighbor, {}))
                if node_data.get("node_type") != "stock":
                    continue
                results.append(
                    {
                        "symbol": neighbor,
                        "correlation": eff_conf,
                        **node_data,
                    }
                )
        return results

    def get_thesis_evidence(self, thesis_id: str) -> list[dict[str, Any]]:
        """Get all evidence supporting or contradicting a thesis."""
        results: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        with self._lock:
            if thesis_id not in self._graph:
                return results
            for pred in self._graph.predecessors(thesis_id):
                edge = self._graph.edges[pred, thesis_id]
                if edge.get("relation") != "supports":
                    continue
                if not self._is_edge_valid(edge, now):
                    continue
                node_data = dict(self._graph.nodes[pred])
                results.append(
                    {
                        "evidence_id": pred,
                        "confidence": self._effective_confidence(edge, now),
                        **node_data,
                    }
                )
        return results

    def get_active_events(self) -> list[dict[str, Any]]:
        """Get all events whose valid_until hasn't passed."""
        results: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        with self._lock:
            for node_id, data in self._graph.nodes(data=True):
                if data.get("node_type") != "event":
                    continue
                valid_until = data.get("valid_until")
                if valid_until:
                    try:
                        if datetime.fromisoformat(valid_until) < now:
                            continue
                    except (ValueError, TypeError):
                        pass
                results.append({"event_id": node_id, **data})
        return results

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def prune_expired(self) -> int:
        """Remove edges past their valid_until. Return count removed."""
        now = datetime.now(UTC)
        to_remove: list[tuple[str, str]] = []
        with self._lock:
            for u, v, data in self._graph.edges(data=True):
                if not self._is_edge_valid(data, now):
                    to_remove.append((u, v))
            for u, v in to_remove:
                self._graph.remove_edge(u, v)
        if to_remove:
            logger.info("Pruned %d expired edges", len(to_remove))
        return len(to_remove)

    def decay_edges(self) -> int:
        """Apply decay_rate to edge confidence. Remove if confidence < 0.1."""
        now = datetime.now(UTC)
        to_remove: list[tuple[str, str]] = []
        decayed = 0
        with self._lock:
            for u, v, data in self._graph.edges(data=True):
                rate = data.get("decay_rate", 0.0)
                if rate <= 0:
                    continue
                eff = self._effective_confidence(data, now)
                if eff < 0.1:
                    to_remove.append((u, v))
                else:
                    data["confidence"] = eff
                    decayed += 1
            for u, v in to_remove:
                self._graph.remove_edge(u, v)
        total = decayed + len(to_remove)
        if total:
            logger.info(
                "Decay pass: %d updated, %d removed (below 0.1)",
                decayed,
                len(to_remove),
            )
        return total

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize graph state for API response."""
        with self._lock:
            nodes = []
            for node_id, data in self._graph.nodes(data=True):
                nodes.append({"id": node_id, **data})
            edges = []
            for u, v, data in self._graph.edges(data=True):
                edges.append({"source": u, "target": v, **data})
        return {
            "nodes": nodes,
            "edges": edges,
            "stats": self.stats(),
        }

    def stats(self) -> dict[str, Any]:
        """Return graph statistics (node counts by type, edge counts by relation)."""
        node_counts: dict[str, int] = {}
        edge_counts: dict[str, int] = {}
        with self._lock:
            for _, data in self._graph.nodes(data=True):
                nt = data.get("node_type", "unknown")
                node_counts[nt] = node_counts.get(nt, 0) + 1
            for _, _, data in self._graph.edges(data=True):
                rel = data.get("relation", "unknown")
                edge_counts[rel] = edge_counts.get(rel, 0) + 1
        return {
            "total_nodes": self._graph.number_of_nodes(),
            "total_edges": self._graph.number_of_edges(),
            "nodes_by_type": node_counts,
            "edges_by_relation": edge_counts,
        }

    # ------------------------------------------------------------------
    # Persistence (SQLite-backed)
    # ------------------------------------------------------------------

    def _load_from_db(self) -> None:
        """Load graph from SQLite on startup."""
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS kg_state "
                "(id INTEGER PRIMARY KEY CHECK(id=1), graph_json TEXT)"
            )
            row = conn.execute("SELECT graph_json FROM kg_state WHERE id=1").fetchone()
            conn.close()
            if row and row[0]:
                data = json.loads(row[0])
                self._graph = json_graph.node_link_graph(data, directed=True)
                logger.info(
                    "KG loaded from db: %d nodes, %d edges",
                    self._graph.number_of_nodes(),
                    self._graph.number_of_edges(),
                )
        except Exception as exc:
            logger.debug("KG db load skipped: %s", exc)

    def _persist(self) -> None:
        """Persist graph to SQLite. Called after write operations."""
        self._dirty = True
        self._write_count += 1
        # Batch persist: only write every 5 changes to reduce I/O
        if self._write_count % 5 != 0:
            return
        self._flush()

    def _flush(self) -> None:
        """Force write to SQLite."""
        if not self._dirty:
            return
        try:
            data = json_graph.node_link_data(self._graph)
            graph_json = json.dumps(data, ensure_ascii=False, default=str)
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "INSERT OR REPLACE INTO kg_state (id, graph_json) VALUES (1, ?)",
                (graph_json,),
            )
            conn.commit()
            conn.close()
            self._dirty = False
        except Exception as exc:
            logger.warning("KG persist failed: %s", exc)

    def flush(self) -> None:
        """Public flush — call at end of pipeline cycle."""
        with self._lock:
            self._flush()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_edge(
        self,
        source: str,
        target: str,
        relation: str,
        confidence: float = 1.0,
    ) -> None:
        """Add edge if not already present. Must be called under _lock."""
        now = datetime.now(UTC)
        if not self._graph.has_edge(source, target):
            self._graph.add_edge(
                source,
                target,
                relation=relation,
                confidence=confidence,
                valid_from=now.isoformat(),
                valid_until=None,
                decay_rate=0.0,
                created_at=now.isoformat(),
            )

    @staticmethod
    def _is_edge_valid(data: dict[str, Any], now: datetime) -> bool:
        """Check if an edge is still temporally valid."""
        valid_until = data.get("valid_until")
        if valid_until is None:
            return True
        try:
            return datetime.fromisoformat(valid_until) >= now
        except (ValueError, TypeError):
            return True

    @staticmethod
    def _effective_confidence(data: dict[str, Any], now: datetime) -> float:
        """Compute decayed confidence based on elapsed time and decay_rate."""
        base = data.get("confidence", 1.0)
        rate = data.get("decay_rate", 0.0)
        if rate <= 0:
            return base
        valid_from = data.get("valid_from")
        if not valid_from:
            return base
        try:
            start = datetime.fromisoformat(valid_from)
            elapsed_days = (now - start).total_seconds() / 86400
            decayed = base - rate * elapsed_days
            return max(0.0, decayed)
        except (ValueError, TypeError):
            return base
