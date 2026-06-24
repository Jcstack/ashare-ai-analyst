"""Persistent event store for event-driven analysis.

Stores detected events (corporate, geopolitical, policy, market) in
SQLite for backtesting, causal chain analysis, and trend detection.
Events that were previously ephemeral (flow through pipeline once and
forgotten) are now persisted with lifecycle tracking.

Schema lives in data/intelligence.db alongside event_state_tracker.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("intelligence.event_store")

__all__ = ["Event", "EventStore"]

_DB_PATH = "data/intelligence.db"


@dataclass
class Event:
    """A persistent event record."""

    event_id: str
    event_type: str  # corporate|geopolitical|policy|market
    title: str
    description: str = ""
    source: str = ""  # cninfo|gdelt|acled|rss|polymarket
    first_seen: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)
    stage: str = "emerging"  # emerging|fermenting|peak|fading|resolved
    severity: float = 0.0  # 0-1
    related_symbols: list[str] = field(default_factory=list)
    related_sectors: list[str] = field(default_factory=list)
    causal_parent_id: str | None = None
    market_impact: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "type": self.event_type,
            "title": self.title,
            "source": self.source,
            "stage": self.stage,
            "severity": self.severity,
            "symbols": self.related_symbols,
            "sectors": self.related_sectors,
            "parent": self.causal_parent_id,
        }


class EventStore:
    """SQLite-backed persistent event store.

    Thread-safe via per-thread connections.

    Usage::

        store = EventStore()
        store.upsert_event(Event(
            event_id="ann_601318_2026",
            event_type="corporate",
            title="中国平安发布重组方案",
            source="cninfo",
            severity=0.8,
            related_symbols=["601318"],
        ))

        active = store.get_active_events(event_type="corporate")
    """

    def __init__(self, db_path: str = _DB_PATH) -> None:
        self._db_path = db_path
        self._local = threading.local()
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _ensure_schema(self) -> None:
        conn = self._get_conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                source TEXT DEFAULT '',
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                stage TEXT DEFAULT 'emerging',
                severity REAL DEFAULT 0.0,
                related_symbols TEXT DEFAULT '[]',
                related_sectors TEXT DEFAULT '[]',
                causal_parent_id TEXT,
                market_impact TEXT DEFAULT '{}',
                metadata TEXT DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_events_type
                ON events(event_type);
            CREATE INDEX IF NOT EXISTS idx_events_stage
                ON events(stage);
            CREATE INDEX IF NOT EXISTS idx_events_first_seen
                ON events(first_seen DESC);
            """
        )
        conn.commit()

    def upsert_event(self, event: Event) -> str:
        """Insert or update an event.

        Returns the event_id.
        """
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO events (
                event_id, event_type, title, description, source,
                first_seen, last_updated, stage, severity,
                related_symbols, related_sectors,
                causal_parent_id, market_impact, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                title = excluded.title,
                description = excluded.description,
                last_updated = excluded.last_updated,
                stage = excluded.stage,
                severity = excluded.severity,
                related_symbols = excluded.related_symbols,
                related_sectors = excluded.related_sectors,
                causal_parent_id = excluded.causal_parent_id,
                market_impact = excluded.market_impact,
                metadata = excluded.metadata
            """,
            (
                event.event_id,
                event.event_type,
                event.title,
                event.description,
                event.source,
                event.first_seen.isoformat(),
                event.last_updated.isoformat(),
                event.stage,
                event.severity,
                json.dumps(event.related_symbols, ensure_ascii=False),
                json.dumps(event.related_sectors, ensure_ascii=False),
                event.causal_parent_id,
                json.dumps(event.market_impact, ensure_ascii=False),
                json.dumps(event.metadata, ensure_ascii=False),
            ),
        )
        conn.commit()
        return event.event_id

    def get_event(self, event_id: str) -> Event | None:
        """Get a single event by ID."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM events WHERE event_id = ?", (event_id,)
        ).fetchone()
        return self._row_to_event(row) if row else None

    def get_active_events(
        self,
        event_type: str | None = None,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[Event]:
        """Get active (non-resolved) events.

        Args:
            event_type: Filter by type.
            symbol: Filter by related symbol (JSON LIKE match).
            limit: Maximum results.
        """
        conn = self._get_conn()
        query = "SELECT * FROM events WHERE stage != 'resolved'"
        params: list[Any] = []

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)

        if symbol:
            query += " AND related_symbols LIKE ?"
            params.append(f"%{symbol}%")

        query += " ORDER BY last_updated DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [self._row_to_event(r) for r in rows if r]

    def link_causal_chain(self, child_id: str, parent_id: str) -> None:
        """Link two events in a causal chain."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE events SET causal_parent_id = ?, last_updated = ? WHERE event_id = ?",
            (parent_id, datetime.now().isoformat(), child_id),
        )
        conn.commit()

    def get_causal_chain(self, event_id: str) -> list[Event]:
        """Walk the causal chain from an event back to root."""
        chain: list[Event] = []
        current_id: str | None = event_id
        visited: set[str] = set()

        while current_id and current_id not in visited:
            visited.add(current_id)
            event = self.get_event(current_id)
            if not event:
                break
            chain.append(event)
            current_id = event.causal_parent_id

        chain.reverse()  # root first
        return chain

    def update_stage(self, event_id: str, stage: str) -> None:
        """Update an event's lifecycle stage."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE events SET stage = ?, last_updated = ? WHERE event_id = ?",
            (stage, datetime.now().isoformat(), event_id),
        )
        conn.commit()

    def archive_stale(self, days: int = 7) -> int:
        """Mark old resolved events for archival.

        Returns count of archived events.
        """
        conn = self._get_conn()
        cutoff = datetime.now().timestamp() - days * 86400
        cursor = conn.execute(
            "UPDATE events SET stage = 'archived' WHERE stage = 'resolved' AND last_updated < ?",
            (datetime.fromtimestamp(cutoff).isoformat(),),
        )
        conn.commit()
        return cursor.rowcount

    def get_events_for_symbol(self, symbol: str, days: int = 30) -> list[Event]:
        """Get all events related to a symbol in the last N days."""
        conn = self._get_conn()
        cutoff = datetime.now().timestamp() - days * 86400
        rows = conn.execute(
            """
            SELECT * FROM events
            WHERE related_symbols LIKE ?
              AND first_seen >= ?
            ORDER BY first_seen DESC
            """,
            (f"%{symbol}%", datetime.fromtimestamp(cutoff).isoformat()),
        ).fetchall()
        return [self._row_to_event(r) for r in rows if r]

    def _row_to_event(self, row: sqlite3.Row) -> Event:
        """Convert a database row to an Event dataclass."""
        return Event(
            event_id=row["event_id"],
            event_type=row["event_type"],
            title=row["title"],
            description=row["description"] or "",
            source=row["source"] or "",
            first_seen=datetime.fromisoformat(row["first_seen"]),
            last_updated=datetime.fromisoformat(row["last_updated"]),
            stage=row["stage"],
            severity=float(row["severity"]),
            related_symbols=json.loads(row["related_symbols"] or "[]"),
            related_sectors=json.loads(row["related_sectors"] or "[]"),
            causal_parent_id=row["causal_parent_id"],
            market_impact=json.loads(row["market_impact"] or "{}"),
            metadata=json.loads(row["metadata"] or "{}"),
        )
