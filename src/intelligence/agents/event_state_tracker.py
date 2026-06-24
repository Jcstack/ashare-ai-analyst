"""Event State Tracker Agent — Analyst Team member for event lifecycle management.

Tracks major events through their lifecycle:
  DETECTED -> DEVELOPING -> ESCALATING -> PEAK -> DE_ESCALATING -> RESOLVED
                              ^                       |
                              +------- RELAPSED <------+

Per PRD v39.0 FR-GIT008.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from functools import lru_cache

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("intelligence.agents.event_state_tracker")


class EventState(str, Enum):
    DETECTED = "detected"
    DEVELOPING = "developing"
    ESCALATING = "escalating"
    PEAK = "peak"
    DE_ESCALATING = "de_escalating"
    RESOLVED = "resolved"
    RELAPSED = "relapsed"


@dataclass
class StateTransition:
    from_state: str
    to_state: str
    timestamp: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_state": self.from_state,
            "to_state": self.to_state,
            "timestamp": self.timestamp,
            "reason": self.reason,
        }


@dataclass
class TrackedEvent:
    event_id: str
    title: str
    event_type: str
    state: EventState
    region: str = "未知"
    first_seen: str = ""
    last_updated: str = ""
    state_history: list[StateTransition] = field(default_factory=list)
    mention_count_24h: int = 1
    mention_trend: str = "stable"  # rising | falling | stable
    baseline_mentions: float = 1.0
    probability_holds: float = 0.5
    impact_chain_ids: list[str] = field(default_factory=list)
    affected_symbols: list[str] = field(default_factory=list)
    affected_sectors: list[str] = field(default_factory=list)
    ai_summary: str = ""
    next_catalyst: str = ""
    reversal_risk: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "title": self.title,
            "event_type": self.event_type,
            "state": self.state.value,
            "region": self.region,
            "first_seen": self.first_seen,
            "last_updated": self.last_updated,
            "state_history": [s.to_dict() for s in self.state_history],
            "mention_count_24h": self.mention_count_24h,
            "mention_trend": self.mention_trend,
            "baseline_mentions": self.baseline_mentions,
            "probability_holds": self.probability_holds,
            "impact_chain_ids": self.impact_chain_ids,
            "affected_symbols": self.affected_symbols,
            "affected_sectors": self.affected_sectors,
            "ai_summary": self.ai_summary,
            "next_catalyst": self.next_catalyst,
            "reversal_risk": self.reversal_risk,
        }

    @property
    def hours_since_last_update(self) -> float:
        if not self.last_updated:
            return 0.0
        try:
            last = datetime.fromisoformat(self.last_updated)
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            delta = datetime.now(UTC) - last
            return delta.total_seconds() / 3600
        except (ValueError, TypeError):
            return 0.0


class EventStateStore:
    """SQLite-backed persistence for tracked events."""

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            from src.utils.config import get_project_root

            db_path = str(get_project_root() / "data" / "tracked_events.db")
        self._db_path = db_path
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _ensure_schema(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
            conn = self._get_conn()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tracked_events (
                    event_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    event_type TEXT DEFAULT '',
                    state TEXT DEFAULT 'detected',
                    region TEXT DEFAULT '未知',
                    first_seen TEXT NOT NULL,
                    last_updated TEXT NOT NULL,
                    state_history_json TEXT DEFAULT '[]',
                    mention_count_24h INTEGER DEFAULT 1,
                    mention_trend TEXT DEFAULT 'stable',
                    baseline_mentions REAL DEFAULT 1.0,
                    probability_holds REAL DEFAULT 0.5,
                    impact_chain_ids_json TEXT DEFAULT '[]',
                    affected_symbols_json TEXT DEFAULT '[]',
                    affected_sectors_json TEXT DEFAULT '[]',
                    ai_summary TEXT DEFAULT '',
                    next_catalyst TEXT DEFAULT '',
                    reversal_risk REAL DEFAULT 0.5
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_state ON tracked_events(state)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_updated ON tracked_events(last_updated)"
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.error("Failed to init event store schema: %s", exc)

    def upsert(self, event: TrackedEvent) -> None:
        try:
            conn = self._get_conn()
            conn.execute(
                """INSERT OR REPLACE INTO tracked_events
                   (event_id, title, event_type, state, region,
                    first_seen, last_updated, state_history_json,
                    mention_count_24h, mention_trend, baseline_mentions,
                    probability_holds, impact_chain_ids_json,
                    affected_symbols_json, affected_sectors_json,
                    ai_summary, next_catalyst, reversal_risk)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event.event_id,
                    event.title,
                    event.event_type,
                    event.state.value,
                    event.region,
                    event.first_seen,
                    event.last_updated,
                    json.dumps(
                        [s.to_dict() for s in event.state_history], ensure_ascii=False
                    ),
                    event.mention_count_24h,
                    event.mention_trend,
                    event.baseline_mentions,
                    event.probability_holds,
                    json.dumps(event.impact_chain_ids, ensure_ascii=False),
                    json.dumps(event.affected_symbols, ensure_ascii=False),
                    json.dumps(event.affected_sectors, ensure_ascii=False),
                    event.ai_summary,
                    event.next_catalyst,
                    event.reversal_risk,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.error("Failed to upsert event %s: %s", event.event_id, exc)

    def get_active_events(self) -> list[TrackedEvent]:
        """Get all events not in RESOLVED state."""
        try:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM tracked_events WHERE state != 'resolved' ORDER BY last_updated DESC"
            ).fetchall()
            conn.close()
            return [self._row_to_event(r) for r in rows]
        except Exception as exc:
            logger.error("Failed to get active events: %s", exc)
            return []

    def get_event(self, event_id: str) -> TrackedEvent | None:
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT * FROM tracked_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            conn.close()
            return self._row_to_event(row) if row else None
        except Exception as exc:
            logger.error("Failed to get event %s: %s", event_id, exc)
            return None

    def _row_to_event(self, row: tuple) -> TrackedEvent:
        state_history = []
        try:
            for s in json.loads(row[7] or "[]"):
                state_history.append(StateTransition(**s))
        except (json.JSONDecodeError, TypeError):
            pass

        return TrackedEvent(
            event_id=row[0],
            title=row[1],
            event_type=row[2] or "",
            state=EventState(row[3] or "detected"),
            region=row[4] or "未知",
            first_seen=row[5],
            last_updated=row[6],
            state_history=state_history,
            mention_count_24h=row[8] or 1,
            mention_trend=row[9] or "stable",
            baseline_mentions=row[10] or 1.0,
            probability_holds=row[11] or 0.5,
            impact_chain_ids=json.loads(row[12] or "[]"),
            affected_symbols=json.loads(row[13] or "[]"),
            affected_sectors=json.loads(row[14] or "[]"),
            ai_summary=row[15] or "",
            next_catalyst=row[16] or "",
            reversal_risk=row[17] or 0.5,
        )


class EventStateTracker:
    """Analyst team: tracks events through lifecycle state machine.

    Creates tracked events from EventUnderstanding outputs and
    evaluates state transitions based on mention frequency, trend,
    and time since last update.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or self._load_config()
        tracker_cfg = self._config.get("analyst", {}).get("event_tracker", {})
        self._resolve_hours = tracker_cfg.get("resolve_after_hours", 48)
        self._escalation_mult = tracker_cfg.get("escalation_multiplier", 3.0)
        self._peak_cooldown = tracker_cfg.get("peak_cooldown_hours", 6)
        self._max_active = tracker_cfg.get("max_active_events", 50)
        self._store = EventStateStore()
        self._mention_buffer: dict[str, int] = {}  # event_id -> new mentions this cycle
        logger.info("EventStateTracker initialized")

    @staticmethod
    def _load_config() -> dict[str, Any]:
        try:
            return load_config("global_intelligence")
        except FileNotFoundError:
            return {}

    def register_event(
        self,
        title: str,
        event_type: str = "",
        region: str = "未知",
        sectors: list[str] | None = None,
        symbols: list[str] | None = None,
        reversal_risk: float = 0.5,
        ai_summary: str = "",
    ) -> TrackedEvent:
        """Register a new event or update mention count of existing one.

        If an event with a similar title already exists and is active,
        increments its mention count instead of creating a new one.
        """
        # Check for existing similar event
        existing = self._find_similar(title)
        if existing:
            existing.mention_count_24h += 1
            existing.last_updated = datetime.now(UTC).isoformat()
            if sectors:
                existing.affected_sectors = list(
                    set(existing.affected_sectors + sectors)
                )
            if symbols:
                existing.affected_symbols = list(
                    set(existing.affected_symbols + symbols)
                )
            self._store.upsert(existing)
            logger.debug(
                "Updated existing event: %s (mentions=%d)",
                existing.event_id[:8],
                existing.mention_count_24h,
            )
            return existing

        # Create new event
        now = datetime.now(UTC).isoformat()
        event = TrackedEvent(
            event_id=str(uuid.uuid4()),
            title=title,
            event_type=event_type,
            state=EventState.DETECTED,
            region=region,
            first_seen=now,
            last_updated=now,
            affected_sectors=sectors or [],
            affected_symbols=symbols or [],
            reversal_risk=reversal_risk,
            ai_summary=ai_summary,
        )
        self._store.upsert(event)
        logger.info("Registered new event: %s — %s", event.event_id[:8], title[:50])
        return event

    def evaluate_transitions(self) -> list[dict[str, Any]]:
        """Evaluate state transitions for all active events.

        Returns:
            List of state change dicts for publishing to event bus.
        """
        active = self._store.get_active_events()
        changes: list[dict[str, Any]] = []

        for event in active:
            new_state = self._check_transition(event)
            if new_state and new_state != event.state:
                reason = self._explain_transition(event, new_state)
                transition = StateTransition(
                    from_state=event.state.value,
                    to_state=new_state.value,
                    timestamp=datetime.now(UTC).isoformat(),
                    reason=reason,
                )
                event.state_history.append(transition)
                old_state = event.state
                event.state = new_state
                event.last_updated = datetime.now(UTC).isoformat()
                self._store.upsert(event)

                change = {
                    "event_id": event.event_id,
                    "title": event.title,
                    "old_state": old_state.value,
                    "new_state": new_state.value,
                    "reason": reason,
                    "affected_sectors": event.affected_sectors,
                    "affected_symbols": event.affected_symbols,
                }
                changes.append(change)
                logger.info(
                    "Event %s state: %s → %s (%s)",
                    event.event_id[:8],
                    old_state.value,
                    new_state.value,
                    reason,
                )

        return changes

    def _check_transition(self, event: TrackedEvent) -> EventState | None:
        """Check if an event should transition to a new state."""
        hours = event.hours_since_last_update
        mentions = event.mention_count_24h
        baseline = max(event.baseline_mentions, 1.0)
        trend = event.mention_trend

        if event.state == EventState.DETECTED:
            if mentions >= 3:  # Multi-source confirmation
                return EventState.DEVELOPING
            if hours > 24:
                return EventState.RESOLVED

        elif event.state == EventState.DEVELOPING:
            if mentions > baseline * self._escalation_mult:
                return EventState.ESCALATING
            if mentions < baseline * 0.5 and hours > 12:
                return EventState.DE_ESCALATING

        elif event.state == EventState.ESCALATING:
            if trend == "falling" and hours > self._peak_cooldown:
                return EventState.PEAK

        elif event.state == EventState.PEAK:
            if trend == "falling" and hours > self._peak_cooldown:
                return EventState.DE_ESCALATING

        elif event.state == EventState.DE_ESCALATING:
            if hours > self._resolve_hours:
                return EventState.RESOLVED
            if mentions > baseline * 2:
                return EventState.RELAPSED

        elif event.state == EventState.RELAPSED:
            return EventState.ESCALATING  # Auto-transition

        return None

    def _explain_transition(self, event: TrackedEvent, new_state: EventState) -> str:
        """Generate human-readable explanation for state transition."""
        mentions = event.mention_count_24h

        explanations = {
            EventState.DEVELOPING: f"多源确认（提及{mentions}次）",
            EventState.ESCALATING: f"提及频率激增（{mentions}次，基线{event.baseline_mentions:.0f}）",
            EventState.PEAK: f"提及频率开始下降（趋势：{event.mention_trend}）",
            EventState.DE_ESCALATING: "事件热度持续降温",
            EventState.RESOLVED: f"超过{self._resolve_hours}小时无新进展",
            EventState.RELAPSED: f"重新升温（提及{mentions}次）",
        }
        return explanations.get(new_state, "状态变更")

    # v54: Cross-language bilingual entity mappings for semantic dedup
    _BILINGUAL_ENTITIES: dict[str, str] = {
        "央行": "PBOC",
        "中国人民银行": "PBOC",
        "降准": "RRR",
        "准备金": "RRR",
        "降息": "RATE_CUT",
        "加息": "RATE_HIKE",
        "美联储": "FED",
        "联储": "FED",
        "关税": "TARIFF",
        "贸易战": "TRADE_WAR",
        "制裁": "SANCTION",
        "伊朗": "IRAN",
        "以色列": "ISRAEL",
        "俄罗斯": "RUSSIA",
        "乌克兰": "UKRAINE",
        "台海": "TAIWAN",
        "南海": "SCS",
        "中东": "MIDEAST",
        "原油": "OIL",
        "黄金": "GOLD",
        "半导体": "SEMICONDUCTOR",
        "芯片": "CHIP",
        "新能源": "NEV",
        "光伏": "SOLAR",
    }

    @classmethod
    def _extract_key_entities(cls, text: str) -> set[str]:
        """Extract key entities for cross-language dedup.

        Normalizes Chinese financial terms to canonical English tokens
        so that '央行降准' and 'PBOC RRR cut' share entity overlap.
        """
        import re

        entities: set[str] = set()
        # English acronyms (2+ uppercase letters)
        entities.update(re.findall(r"\b[A-Z]{2,}\b", text))
        # Numbers (standalone, may include %)
        entities.update(re.findall(r"\b\d+(?:\.\d+)?%?\b", text))
        # Bilingual mapping
        for cn, en in cls._BILINGUAL_ENTITIES.items():
            if cn in text:
                entities.add(en)
            if en.lower() in text.lower():
                entities.add(en)
        return entities

    def _find_similar(self, title: str) -> TrackedEvent | None:
        """Find an active event with a similar title.

        v54: Enhanced with cross-language entity matching.
        '央行降准' matches 'PBOC cuts RRR' via shared entity set.
        """
        active = self._store.get_active_events()
        title_lower = title.lower()
        title_words = set(title_lower.split())
        title_entities = self._extract_key_entities(title)

        best_match: TrackedEvent | None = None
        best_score: float = 0.0

        for event in active:
            event_words = set(event.title.lower().split())

            # 1. Word overlap (Jaccard)
            word_overlap = 0.0
            if event_words and title_words:
                word_overlap = len(event_words & title_words) / min(
                    len(event_words), len(title_words)
                )

            # 2. Entity overlap (handles cross-language)
            entity_overlap = 0.0
            if title_entities:
                event_entities = self._extract_key_entities(event.title)
                if event_entities:
                    entity_overlap = len(title_entities & event_entities) / min(
                        len(title_entities), len(event_entities)
                    )

            # Combined score (max of two approaches)
            score = max(word_overlap, entity_overlap)
            if score > best_score:
                best_score = score
                best_match = event

        if best_score > 0.5:
            return best_match
        return None

    def get_active_events(self) -> list[TrackedEvent]:
        """Get all active (non-resolved) events."""
        return self._store.get_active_events()

    def get_event(self, event_id: str) -> TrackedEvent | None:
        return self._store.get_event(event_id)

    def update_mention_stats(self, event_id: str, new_mentions: int = 1) -> None:
        """Update mention statistics for an event."""
        event = self._store.get_event(event_id)
        if event:
            event.mention_count_24h += new_mentions
            # Update trend based on comparison to baseline
            ratio = event.mention_count_24h / max(event.baseline_mentions, 1.0)
            if ratio > 1.5:
                event.mention_trend = "rising"
            elif ratio < 0.5:
                event.mention_trend = "falling"
            else:
                event.mention_trend = "stable"
            event.last_updated = datetime.now(UTC).isoformat()
            self._store.upsert(event)


# ---------------------------------------------------------------------------
# DI singleton
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_event_state_tracker() -> EventStateTracker:
    return EventStateTracker(
        config=load_config("global_intelligence"),
    )
