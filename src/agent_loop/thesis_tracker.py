"""Thesis lifecycle management — tracks investment theses from creation to resolution.

Each thesis represents a reason to hold a position. Theses have confidence that
decays over time and can be strengthened/weakened by new evidence. When confidence
drops below thresholds, the thesis transitions through statuses:

    active → weakening (< 0.35) → invalidated (< 0.20)

Theses can also be realized (closed profitably) or invalidated manually.
Expiry is enforced: default 5 trading days from creation.

Storage: SQLite in ``data/theses.db``.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("agent_loop.thesis_tracker")

_DB_PATH = Path("data/theses.db")

# Confidence thresholds
_WEAKENING_THRESHOLD = 0.35
_INVALIDATION_THRESHOLD = 0.20


class Thesis:
    """In-memory representation of a thesis row."""

    __slots__ = (
        "id",
        "symbol",
        "direction",
        "narrative",
        "entry_condition",
        "invalidation_condition",
        "created_at",
        "expires_at",
        "initial_confidence",
        "current_confidence",
        "decay_rate",
        "status",
        "evidence",
        "position_id",
        "resolved_at",
        "resolved_reason",
    )

    def __init__(
        self,
        *,
        id: str,
        symbol: str,
        direction: str = "long",
        narrative: str = "",
        entry_condition: str = "",
        invalidation_condition: str = "",
        created_at: datetime | None = None,
        expires_at: datetime | None = None,
        initial_confidence: float = 0.5,
        current_confidence: float | None = None,
        decay_rate: float = 0.02,
        status: str = "active",
        evidence: list[dict[str, Any]] | None = None,
        position_id: str | None = None,
        resolved_at: datetime | None = None,
        resolved_reason: str | None = None,
    ) -> None:
        self.id = id
        self.symbol = symbol
        self.direction = direction
        self.narrative = narrative
        self.entry_condition = entry_condition
        self.invalidation_condition = invalidation_condition
        self.created_at = created_at or datetime.now(timezone.utc)
        self.expires_at = expires_at or (self.created_at + timedelta(days=5))
        self.initial_confidence = initial_confidence
        self.current_confidence = (
            current_confidence if current_confidence is not None else initial_confidence
        )
        self.decay_rate = decay_rate
        self.status = status
        self.evidence = evidence if evidence is not None else []
        self.position_id = position_id
        self.resolved_at = resolved_at
        self.resolved_reason = resolved_reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "direction": self.direction,
            "narrative": self.narrative,
            "entry_condition": self.entry_condition,
            "invalidation_condition": self.invalidation_condition,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "initial_confidence": self.initial_confidence,
            "current_confidence": self.current_confidence,
            "decay_rate": self.decay_rate,
            "status": self.status,
            "evidence": self.evidence,
            "position_id": self.position_id,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_reason": self.resolved_reason,
        }


class ThesisTracker:
    """Manages thesis lifecycle with SQLite persistence."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._ensure_tables()

    # ------------------------------------------------------------------
    # Database setup
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(str(self._db_path))

    def _ensure_tables(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS theses (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL DEFAULT 'long',
                    narrative TEXT NOT NULL,
                    entry_condition TEXT,
                    invalidation_condition TEXT,
                    created_at TIMESTAMP NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    initial_confidence REAL NOT NULL,
                    current_confidence REAL NOT NULL,
                    decay_rate REAL NOT NULL DEFAULT 0.02,
                    status TEXT NOT NULL DEFAULT 'active',
                    evidence TEXT DEFAULT '[]',
                    position_id TEXT,
                    resolved_at TIMESTAMP,
                    resolved_reason TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_theses_symbol ON theses(symbol);
                CREATE INDEX IF NOT EXISTS idx_theses_status ON theses(status);
                CREATE INDEX IF NOT EXISTS idx_theses_position_id ON theses(position_id);

                CREATE TABLE IF NOT EXISTS thesis_conviction_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thesis_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence_count INTEGER NOT NULL DEFAULT 0,
                    pnl_pct REAL,
                    health_score REAL,
                    UNIQUE(thesis_id, date)
                );
                CREATE INDEX IF NOT EXISTS idx_history_thesis_id
                    ON thesis_conviction_history(thesis_id);
                """
            )

    # ------------------------------------------------------------------
    # Row ↔ Thesis mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_thesis(row: sqlite3.Row) -> Thesis:
        evidence_raw = row["evidence"] or "[]"
        try:
            evidence = json.loads(evidence_raw)
        except (json.JSONDecodeError, TypeError):
            evidence = []

        def _parse_ts(val: str | None) -> datetime | None:
            if not val:
                return None
            try:
                return datetime.fromisoformat(val)
            except (ValueError, TypeError):
                return None

        return Thesis(
            id=row["id"],
            symbol=row["symbol"],
            direction=row["direction"],
            narrative=row["narrative"],
            entry_condition=row["entry_condition"] or "",
            invalidation_condition=row["invalidation_condition"] or "",
            created_at=_parse_ts(row["created_at"]) or datetime.now(timezone.utc),
            expires_at=_parse_ts(row["expires_at"]) or datetime.now(timezone.utc),
            initial_confidence=row["initial_confidence"],
            current_confidence=row["current_confidence"],
            decay_rate=row["decay_rate"],
            status=row["status"],
            evidence=evidence,
            position_id=row["position_id"],
            resolved_at=_parse_ts(row["resolved_at"]),
            resolved_reason=row["resolved_reason"],
        )

    def _save_thesis(self, thesis: Thesis, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO theses
                (id, symbol, direction, narrative, entry_condition,
                 invalidation_condition, created_at, expires_at,
                 initial_confidence, current_confidence, decay_rate,
                 status, evidence, position_id, resolved_at, resolved_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                thesis.id,
                thesis.symbol,
                thesis.direction,
                thesis.narrative,
                thesis.entry_condition,
                thesis.invalidation_condition,
                thesis.created_at.isoformat(),
                thesis.expires_at.isoformat(),
                thesis.initial_confidence,
                thesis.current_confidence,
                thesis.decay_rate,
                thesis.status,
                json.dumps(thesis.evidence, ensure_ascii=False),
                thesis.position_id,
                thesis.resolved_at.isoformat() if thesis.resolved_at else None,
                thesis.resolved_reason,
            ),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_thesis(
        self,
        symbol: str,
        direction: str,
        narrative: str,
        entry_condition: str,
        invalidation_condition: str,
        confidence: float,
        expires_days: int = 5,
        position_id: str | None = None,
    ) -> Thesis:
        """Create and persist a new thesis."""
        now = datetime.now(timezone.utc)
        thesis = Thesis(
            id=str(uuid.uuid4()),
            symbol=symbol,
            direction=direction,
            narrative=narrative,
            entry_condition=entry_condition,
            invalidation_condition=invalidation_condition,
            created_at=now,
            expires_at=now + timedelta(days=expires_days),
            initial_confidence=confidence,
            current_confidence=confidence,
            position_id=position_id,
        )
        with self._connect() as conn:
            self._save_thesis(thesis, conn)
        logger.info(
            "Created thesis %s for %s (conf=%.2f, expires=%dd)",
            thesis.id[:8],
            symbol,
            confidence,
            expires_days,
        )
        return thesis

    def get_thesis(self, thesis_id: str) -> Thesis | None:
        """Return a single thesis by ID."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM theses WHERE id = ?", (thesis_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_thesis(row)

    def get_active_theses(self) -> list[Thesis]:
        """Return all theses with status 'active' or 'weakening'."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM theses WHERE status IN ('active', 'weakening') "
                "ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_thesis(r) for r in rows]

    def get_weakening_theses(self) -> list[Thesis]:
        """Return theses with status 'weakening'."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM theses WHERE status = 'weakening' ORDER BY current_confidence ASC"
            ).fetchall()
        return [self._row_to_thesis(r) for r in rows]

    def get_thesis_for_position(self, position_id: str) -> Thesis | None:
        """Return the active thesis linked to a position, or None."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM theses WHERE position_id = ? "
                "AND status IN ('active', 'weakening') "
                "ORDER BY created_at DESC LIMIT 1",
                (position_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_thesis(row)

    def list_theses(
        self,
        status: str | None = None,
        symbol: str | None = None,
    ) -> list[Thesis]:
        """List theses with optional filtering."""
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        where = " AND ".join(clauses)
        sql = "SELECT * FROM theses"
        if where:
            sql += f" WHERE {where}"
        sql += " ORDER BY created_at DESC"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_thesis(r) for r in rows]

    def add_evidence(
        self,
        thesis_id: str,
        evidence_type: str,
        description: str,
        source: str = "",
        confidence_impact: float = 0.0,
    ) -> Thesis | None:
        """Add evidence to a thesis and update confidence.

        Args:
            thesis_id: Target thesis.
            evidence_type: "supporting" or "contradicting".
            description: What happened.
            source: Where this evidence came from.
            confidence_impact: Signed float — positive for supporting,
                negative for contradicting.  Applied to current_confidence.

        Returns:
            Updated thesis, or None if not found.
        """
        thesis = self.get_thesis(thesis_id)
        if thesis is None:
            return None
        if thesis.status in ("invalidated", "realized"):
            logger.debug("Thesis %s already resolved, skipping evidence", thesis_id[:8])
            return thesis

        entry = {
            "type": evidence_type,
            "description": description,
            "source": source,
            "confidence_impact": confidence_impact,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        thesis.evidence.append(entry)

        # Apply impact
        thesis.current_confidence = max(
            0.0, min(1.0, thesis.current_confidence + confidence_impact)
        )

        # Status transitions based on confidence
        thesis.status = self._compute_status(thesis)

        with self._connect() as conn:
            self._save_thesis(thesis, conn)

        logger.info(
            "Evidence added to thesis %s: %s (impact=%.2f, conf=%.2f→%s)",
            thesis_id[:8],
            evidence_type,
            confidence_impact,
            thesis.current_confidence,
            thesis.status,
        )

        # Publish status change to event bus (v50.0)
        try:
            from src.event_bus.producers import publish_thesis_change

            publish_thesis_change(
                thesis_id=thesis.id,
                symbol=thesis.symbol,
                status=thesis.status,
                confidence=thesis.current_confidence,
            )
        except Exception:
            pass  # Never break the caller

        return thesis

    def apply_daily_decay(self) -> list[Thesis]:
        """Apply time decay to all active/weakening theses.

        Returns list of theses whose status changed.
        """
        changed: list[Thesis] = []
        theses = self.get_active_theses()
        with self._connect() as conn:
            for thesis in theses:
                old_status = thesis.status
                thesis.current_confidence = max(
                    0.0, thesis.current_confidence - thesis.decay_rate
                )
                thesis.status = self._compute_status(thesis)
                self._save_thesis(thesis, conn)
                if thesis.status != old_status:
                    changed.append(thesis)
                    logger.info(
                        "Thesis %s (%s) decayed: conf=%.2f, %s→%s",
                        thesis.id[:8],
                        thesis.symbol,
                        thesis.current_confidence,
                        old_status,
                        thesis.status,
                    )
                    # Publish to event bus (v50.0)
                    try:
                        from src.event_bus.producers import publish_thesis_change

                        publish_thesis_change(
                            thesis_id=thesis.id,
                            symbol=thesis.symbol,
                            status=thesis.status,
                            confidence=thesis.current_confidence,
                        )
                    except Exception:
                        pass  # Never break the caller
        if changed:
            logger.info(
                "Daily decay: %d/%d theses changed status", len(changed), len(theses)
            )
        return changed

    def check_expired_and_invalid(self) -> list[Thesis]:
        """Return active theses that are expired or invalidated.

        Checks:
        1. Theses past their expires_at date
        2. Theses with current_confidence < _INVALIDATION_THRESHOLD

        Returns list of theses that should trigger sell signals.
        Does NOT modify thesis status — caller should resolve them.
        """
        now = datetime.now(timezone.utc)
        actionable: list[Thesis] = []

        for thesis in self.get_active_theses():
            if thesis.expires_at and now >= thesis.expires_at:
                actionable.append(thesis)
                logger.info(
                    "Thesis %s (%s) expired: expires_at=%s",
                    thesis.id[:8],
                    thesis.symbol,
                    thesis.expires_at.isoformat(),
                )
            elif thesis.current_confidence < _INVALIDATION_THRESHOLD:
                actionable.append(thesis)
                logger.info(
                    "Thesis %s (%s) invalidated: conf=%.2f < %.2f",
                    thesis.id[:8],
                    thesis.symbol,
                    thesis.current_confidence,
                    _INVALIDATION_THRESHOLD,
                )

        return actionable

    def resolve_thesis(self, thesis_id: str, reason: str) -> None:
        """Mark a thesis as invalidated with a reason."""
        thesis = self.get_thesis(thesis_id)
        if thesis is None or thesis.status in ("invalidated", "realized"):
            return
        thesis.status = "invalidated"
        thesis.resolved_at = datetime.now(timezone.utc)
        thesis.resolved_reason = reason
        with self._connect() as conn:
            self._save_thesis(thesis, conn)
        logger.info("Thesis %s resolved: %s", thesis_id[:8], reason)

    def check_invalidation(
        self,
        thesis_id: str,
        current_price: float,
        market_data: dict[str, Any] | None = None,
    ) -> bool:
        """Check if a thesis should be invalidated based on conditions.

        This is a simple keyword-based check against the invalidation_condition
        string. For example, if the condition mentions a price level and the
        current price breaches it, the thesis is invalidated.

        Returns True if thesis was invalidated.
        """
        thesis = self.get_thesis(thesis_id)
        if thesis is None or thesis.status in ("invalidated", "realized"):
            return False

        mkt = market_data or {}
        condition = thesis.invalidation_condition.lower()

        # Check price-based invalidation: "跌破X" or "price below X"
        invalidated = False
        reason = ""

        # Pattern: price drop below a level
        for keyword in ("跌破", "price below", "below "):
            if keyword in condition:
                try:
                    # Extract numeric value after keyword
                    idx = condition.index(keyword) + len(keyword)
                    num_str = ""
                    for ch in condition[idx:].strip():
                        if ch.isdigit() or ch == ".":
                            num_str += ch
                        else:
                            break
                    if num_str:
                        threshold = float(num_str)
                        if current_price < threshold:
                            invalidated = True
                            reason = f"Price {current_price:.2f} below threshold {threshold:.2f}"
                except (ValueError, IndexError):
                    pass

        # Pattern: price rise above a level (for short theses)
        for keyword in ("突破", "price above", "above "):
            if keyword in condition and thesis.direction == "short":
                try:
                    idx = condition.index(keyword) + len(keyword)
                    num_str = ""
                    for ch in condition[idx:].strip():
                        if ch.isdigit() or ch == ".":
                            num_str += ch
                        else:
                            break
                    if num_str:
                        threshold = float(num_str)
                        if current_price > threshold:
                            invalidated = True
                            reason = f"Price {current_price:.2f} above threshold {threshold:.2f}"
                except (ValueError, IndexError):
                    pass

        # Check regime-based invalidation
        regime = mkt.get("regime", "")
        if regime and regime in condition:
            invalidated = True
            reason = f"Market regime '{regime}' matches invalidation condition"

        if invalidated:
            self.invalidate_thesis(thesis_id, reason)
            return True

        return False

    def check_expiry(self) -> list[Thesis]:
        """Invalidate all expired theses. Returns list of expired theses."""
        now = datetime.now(timezone.utc)
        expired: list[Thesis] = []
        theses = self.get_active_theses()
        with self._connect() as conn:
            for thesis in theses:
                if thesis.expires_at <= now:
                    thesis.status = "invalidated"
                    thesis.resolved_at = now
                    thesis.resolved_reason = "Expired (time limit reached)"
                    self._save_thesis(thesis, conn)
                    expired.append(thesis)
                    logger.info("Thesis %s (%s) expired", thesis.id[:8], thesis.symbol)
        return expired

    def realize_thesis(self, thesis_id: str, reason: str) -> Thesis | None:
        """Mark thesis as realized (position closed with profit)."""
        thesis = self.get_thesis(thesis_id)
        if thesis is None:
            return None
        thesis.status = "realized"
        thesis.resolved_at = datetime.now(timezone.utc)
        thesis.resolved_reason = reason
        with self._connect() as conn:
            self._save_thesis(thesis, conn)
        logger.info("Thesis %s realized: %s", thesis_id[:8], reason)

        # Publish to event bus (v50.0)
        try:
            from src.event_bus.producers import publish_thesis_change

            publish_thesis_change(
                thesis_id=thesis.id,
                symbol=thesis.symbol,
                status="realized",
                confidence=thesis.current_confidence,
            )
        except Exception:
            pass  # Never break the caller

        return thesis

    def invalidate_thesis(self, thesis_id: str, reason: str) -> Thesis | None:
        """Mark thesis as invalidated — generates sell signal."""
        thesis = self.get_thesis(thesis_id)
        if thesis is None:
            return None
        thesis.status = "invalidated"
        thesis.resolved_at = datetime.now(timezone.utc)
        thesis.resolved_reason = reason
        with self._connect() as conn:
            self._save_thesis(thesis, conn)
        logger.info("Thesis %s invalidated: %s", thesis_id[:8], reason)

        # Publish to event bus (v50.0)
        try:
            from src.event_bus.producers import publish_thesis_change

            publish_thesis_change(
                thesis_id=thesis.id,
                symbol=thesis.symbol,
                status="invalidated",
                confidence=thesis.current_confidence,
            )
        except Exception:
            pass  # Never break the caller

        return thesis

    def link_position(self, thesis_id: str, position_id: str) -> Thesis | None:
        """Link a thesis to a portfolio position."""
        thesis = self.get_thesis(thesis_id)
        if thesis is None:
            return None
        thesis.position_id = position_id
        with self._connect() as conn:
            self._save_thesis(thesis, conn)
        logger.info("Thesis %s linked to position %s", thesis_id[:8], position_id[:8])
        return thesis

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_status(thesis: Thesis) -> str:
        """Derive status from confidence level (only for non-resolved theses)."""
        if thesis.status in ("invalidated", "realized"):
            return thesis.status
        if thesis.current_confidence < _INVALIDATION_THRESHOLD:
            thesis.resolved_at = datetime.now(timezone.utc)
            thesis.resolved_reason = (
                f"Confidence dropped to {thesis.current_confidence:.2f}"
            )
            return "invalidated"
        if thesis.current_confidence < _WEAKENING_THRESHOLD:
            return "weakening"
        return "active"

    # ------------------------------------------------------------------
    # v70: Cross-day conviction history
    # ------------------------------------------------------------------

    def snapshot_daily(self, thesis_id: str, pnl_pct: float | None = None) -> None:
        """Save a daily conviction snapshot for cross-day tracking."""
        thesis = self.get_thesis(thesis_id)
        if thesis is None:
            return
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        evidence_count = len(thesis.evidence) if thesis.evidence else 0
        health = self.compute_health_score(thesis_id, pnl_pct)

        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO thesis_conviction_history
                   (thesis_id, date, confidence, evidence_count, pnl_pct, health_score)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    thesis_id,
                    today,
                    thesis.current_confidence,
                    evidence_count,
                    pnl_pct,
                    health,
                ),
            )
        logger.debug(
            "Thesis %s daily snapshot: conf=%.2f health=%.2f pnl=%s",
            thesis_id[:8],
            thesis.current_confidence,
            health,
            f"{pnl_pct:+.1f}%" if pnl_pct is not None else "n/a",
        )

    def get_conviction_history(
        self, thesis_id: str, limit: int = 30
    ) -> list[dict[str, Any]]:
        """Return day-by-day conviction snapshots for a thesis."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT date, confidence, evidence_count, pnl_pct, health_score
                   FROM thesis_conviction_history
                   WHERE thesis_id = ?
                   ORDER BY date DESC
                   LIMIT ?""",
                (thesis_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def compute_health_score(
        self, thesis_id: str, pnl_pct: float | None = None
    ) -> float:
        """Compute thesis health: 0.4*trend + 0.3*freshness + 0.3*pnl_alignment.

        Returns 0.0-1.0 where higher = healthier.
        """
        thesis = self.get_thesis(thesis_id)
        if thesis is None:
            return 0.0

        # Trend: compare last 3 daily snapshots
        history = self.get_conviction_history(thesis_id, limit=3)
        if len(history) >= 2:
            latest = history[0]["confidence"]
            oldest = history[-1]["confidence"]
            trend_score = min(1.0, max(0.0, 0.5 + (latest - oldest) * 2))
        else:
            trend_score = 0.5  # Neutral when not enough history

        # Evidence freshness: hours since last evidence
        evidence = thesis.evidence or []
        if evidence:
            last_ts = evidence[-1].get("ts", "")
            try:
                last_dt = datetime.fromisoformat(last_ts)
                hours_ago = (
                    datetime.now(timezone.utc) - last_dt
                ).total_seconds() / 3600
                freshness_score = max(0.0, 1.0 - hours_ago / 72)  # Decays over 72h
            except (ValueError, TypeError):
                freshness_score = 0.3
        else:
            freshness_score = 0.0

        # PnL alignment: positive PnL on bullish thesis = healthy
        if pnl_pct is not None:
            if thesis.direction == "long":
                pnl_alignment = min(1.0, max(0.0, 0.5 + pnl_pct / 20))
            else:
                pnl_alignment = min(1.0, max(0.0, 0.5 - pnl_pct / 20))
        else:
            pnl_alignment = 0.5  # Neutral when no PnL data

        health = 0.4 * trend_score + 0.3 * freshness_score + 0.3 * pnl_alignment
        return round(health, 3)

    def get_by_symbol(self, symbol: str) -> Thesis | None:
        """Return the most recent active thesis for a symbol."""
        theses = self.list_theses(status=None, symbol=symbol)
        active = [t for t in theses if t.status in ("active", "weakening")]
        if active:
            return active[0]
        return theses[0] if theses else None
