"""Data lineage persistence service.

Stores immutable data snapshots and operation records in SQLite
for full traceability of how analysis conclusions were derived.

Part of v14.0 Institutional Contracts layer.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger
from src.web.schemas.lineage import DataSnapshot, LineageGraph, LineageNode

logger = get_logger("web.lineage_service")

_DB_PATH = Path("data/lineage.db")


class LineageService:
    """Manages data lineage records in SQLite.

    Args:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._ensure_db()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def snapshot_data(
        self,
        source: str,
        payload: Any,
        *,
        source_type: str = "market_data",
        symbol: str = "",
        ttl_seconds: int | None = None,
    ) -> DataSnapshot:
        """Create an immutable snapshot of data and persist it.

        Args:
            source: Name of the data source (e.g. "akshare", "sina_realtime").
            payload: The data to snapshot (must be JSON-serializable).
            source_type: Category of data source.
            symbol: Stock symbol if applicable.
            ttl_seconds: Cache TTL that was active when data was fetched.

        Returns:
            The persisted DataSnapshot with computed hash.
        """
        snapshot_id = str(uuid.uuid4())
        now = _now_iso()

        content_hash = DataSnapshot.compute_hash(payload)
        summary = DataSnapshot.summarize_payload(payload)
        payload_json = json.dumps(payload, default=str, ensure_ascii=False)
        payload_size = len(payload_json.encode("utf-8"))

        snapshot = DataSnapshot(
            id=snapshot_id,
            source=source,
            source_type=source_type,
            symbol=symbol,
            timestamp=now,
            content_hash=content_hash,
            payload_summary=summary,
            payload_size_bytes=payload_size,
            ttl_seconds=ttl_seconds,
        )

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO snapshots "
                "(id, source, source_type, symbol, timestamp, content_hash, "
                "payload_json, payload_summary, payload_size_bytes, ttl_seconds) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot_id,
                    source,
                    source_type,
                    symbol,
                    now,
                    content_hash,
                    payload_json,
                    summary,
                    payload_size,
                    ttl_seconds,
                ),
            )

        return snapshot

    def record_operation(
        self,
        operation: str,
        *,
        operation_type: str = "tool_call",
        input_snapshot_ids: list[str] | None = None,
        output_snapshot_id: str = "",
        agent_name: str = "master",
        thread_id: str = "",
        duration_ms: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> LineageNode:
        """Record a lineage operation (tool call, LLM inference, etc.).

        Args:
            operation: Name of the operation.
            operation_type: Category of operation.
            input_snapshot_ids: IDs of consumed snapshots.
            output_snapshot_id: ID of produced snapshot.
            agent_name: Agent that performed the operation.
            thread_id: Chat thread ID.
            duration_ms: Execution time in milliseconds.
            metadata: Extra operation-specific data.

        Returns:
            The persisted LineageNode.
        """
        node_id = str(uuid.uuid4())
        now = _now_iso()
        inputs = input_snapshot_ids or []
        meta = metadata or {}

        node = LineageNode(
            id=node_id,
            operation=operation,
            operation_type=operation_type,
            input_snapshot_ids=inputs,
            output_snapshot_id=output_snapshot_id,
            agent_name=agent_name,
            thread_id=thread_id,
            timestamp=now,
            duration_ms=duration_ms,
            metadata=meta,
        )

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO lineage_nodes "
                "(id, operation, operation_type, input_snapshot_ids, "
                "output_snapshot_id, agent_name, thread_id, timestamp, "
                "duration_ms, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    node_id,
                    operation,
                    operation_type,
                    json.dumps(inputs),
                    output_snapshot_id,
                    agent_name,
                    thread_id,
                    now,
                    duration_ms,
                    json.dumps(meta, default=str, ensure_ascii=False),
                ),
            )

        return node

    def get_snapshot(self, snapshot_id: str) -> DataSnapshot | None:
        """Retrieve a data snapshot by ID.

        Args:
            snapshot_id: Snapshot UUID.

        Returns:
            DataSnapshot or None if not found.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, source, source_type, symbol, timestamp, "
                "content_hash, payload_summary, payload_size_bytes, ttl_seconds "
                "FROM snapshots WHERE id = ?",
                (snapshot_id,),
            ).fetchone()

        if not row:
            return None

        return DataSnapshot(
            id=row[0],
            source=row[1],
            source_type=row[2],
            symbol=row[3],
            timestamp=row[4],
            content_hash=row[5],
            payload_summary=row[6],
            payload_size_bytes=row[7],
            ttl_seconds=row[8],
        )

    def get_snapshot_payload(self, snapshot_id: str) -> Any | None:
        """Retrieve the full JSON payload for a snapshot.

        Args:
            snapshot_id: Snapshot UUID.

        Returns:
            Deserialized payload or None.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM snapshots WHERE id = ?",
                (snapshot_id,),
            ).fetchone()

        if not row or not row[0]:
            return None

        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return None

    def get_lineage(self, thread_id: str, message_id: str = "") -> LineageGraph:
        """Build a lineage graph for a thread (optionally filtered by message).

        Args:
            thread_id: Chat thread ID.
            message_id: Optional message ID to scope the graph.

        Returns:
            LineageGraph with all related snapshots and nodes.
        """
        with self._connect() as conn:
            # Fetch lineage nodes for this thread
            if message_id:
                rows = conn.execute(
                    "SELECT id, operation, operation_type, input_snapshot_ids, "
                    "output_snapshot_id, agent_name, thread_id, timestamp, "
                    "duration_ms, metadata "
                    "FROM lineage_nodes "
                    "WHERE thread_id = ? AND metadata LIKE ? "
                    "ORDER BY timestamp",
                    (thread_id, f'%"message_id": "{message_id}"%'),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, operation, operation_type, input_snapshot_ids, "
                    "output_snapshot_id, agent_name, thread_id, timestamp, "
                    "duration_ms, metadata "
                    "FROM lineage_nodes WHERE thread_id = ? ORDER BY timestamp",
                    (thread_id,),
                ).fetchall()

        nodes: list[LineageNode] = []
        snapshot_ids: set[str] = set()

        for row in rows:
            input_ids = json.loads(row[3]) if row[3] else []
            meta = json.loads(row[9]) if row[9] else {}

            node = LineageNode(
                id=row[0],
                operation=row[1],
                operation_type=row[2],
                input_snapshot_ids=input_ids,
                output_snapshot_id=row[4],
                agent_name=row[5],
                thread_id=row[6],
                timestamp=row[7],
                duration_ms=row[8],
                metadata=meta,
            )
            nodes.append(node)
            snapshot_ids.update(input_ids)
            if row[4]:
                snapshot_ids.add(row[4])

        # Fetch all referenced snapshots
        snapshots: list[DataSnapshot] = []
        for sid in snapshot_ids:
            snap = self.get_snapshot(sid)
            if snap:
                snapshots.append(snap)

        root_id = nodes[0].id if nodes else ""
        leaf_id = nodes[-1].id if nodes else ""

        return LineageGraph(
            thread_id=thread_id,
            message_id=message_id,
            snapshots=snapshots,
            nodes=nodes,
            root_node_id=root_id,
            leaf_node_id=leaf_id,
        )

    def count_snapshots(self) -> int:
        """Count total snapshots in the database."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()
        return row[0] if row else 0

    def count_nodes(self) -> int:
        """Count total lineage nodes in the database."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM lineage_nodes").fetchone()
        return row[0] if row else 0

    def cleanup_old_records(self, max_age_days: int = 30) -> int:
        """Delete lineage records older than max_age_days.

        Args:
            max_age_days: Maximum age in days.

        Returns:
            Number of deleted records.
        """
        from datetime import timedelta

        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()

        try:
            with self._connect() as conn:
                c1 = conn.execute(
                    "DELETE FROM lineage_nodes WHERE timestamp < ?", (cutoff,)
                )
                c2 = conn.execute(
                    "DELETE FROM snapshots WHERE timestamp < ?", (cutoff,)
                )
                total = c1.rowcount + c2.rowcount
                if total > 0:
                    logger.info(
                        "Cleaned up %d old lineage records (older than %d days)",
                        total,
                        max_age_days,
                    )
                return total
        except Exception:
            logger.debug("Lineage cleanup failed", exc_info=True)
            return 0

    # ------------------------------------------------------------------
    # Database operations
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open a connection to the SQLite database."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_db(self) -> None:
        """Create tables if they don't exist."""
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'market_data',
                    symbol TEXT DEFAULT '',
                    timestamp TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    payload_json TEXT,
                    payload_summary TEXT DEFAULT '',
                    payload_size_bytes INTEGER DEFAULT 0,
                    ttl_seconds INTEGER
                );

                CREATE INDEX IF NOT EXISTS idx_snapshots_symbol
                    ON snapshots(symbol, timestamp);

                CREATE INDEX IF NOT EXISTS idx_snapshots_source
                    ON snapshots(source, timestamp);

                CREATE TABLE IF NOT EXISTS lineage_nodes (
                    id TEXT PRIMARY KEY,
                    operation TEXT NOT NULL,
                    operation_type TEXT NOT NULL DEFAULT 'tool_call',
                    input_snapshot_ids TEXT DEFAULT '[]',
                    output_snapshot_id TEXT DEFAULT '',
                    agent_name TEXT DEFAULT 'master',
                    thread_id TEXT DEFAULT '',
                    timestamp TEXT NOT NULL,
                    duration_ms REAL DEFAULT 0.0,
                    metadata TEXT DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_lineage_thread
                    ON lineage_nodes(thread_id, timestamp);
                """
            )


def _now_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()
