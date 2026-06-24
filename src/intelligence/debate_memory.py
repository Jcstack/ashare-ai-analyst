"""Per-agent debate memory with TF-IDF retrieval.

Stores debate records and post-outcome reflections in SQLite.
Each debate can be retrieved by textual similarity (BM25-style
TF-IDF + cosine scoring) so agents can reference relevant past
debates before reasoning.

No external dependencies — reuses the tokenization and TF-IDF
helpers from ``memory_store.py``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.intelligence.memory_store import (
    _compute_idf,
    _cosine_similarity,
    _tfidf_vector,
    _tokenize,
)

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = "data/debate_memory.db"


class DebateMemory:
    """SQLite-backed debate memory with TF-IDF retrieval.

    Stores full debate records (arguments + verdict) and post-outcome
    reflections.  Agents can retrieve similar past debates to inform
    their current reasoning.
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._init_db()

    # ── Schema ────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS debate_records (
                    debate_id    TEXT PRIMARY KEY,
                    symbol       TEXT NOT NULL,
                    name         TEXT DEFAULT '',
                    trigger      TEXT DEFAULT '',
                    final_action TEXT NOT NULL,
                    verdict_json TEXT NOT NULL,
                    bull_json    TEXT NOT NULL,
                    bear_json    TEXT NOT NULL,
                    tokens       TEXT NOT NULL,
                    created_at   TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_dr_symbol
                    ON debate_records(symbol);
                CREATE INDEX IF NOT EXISTS idx_dr_created
                    ON debate_records(created_at);

                CREATE TABLE IF NOT EXISTS debate_reflections (
                    reflection_id TEXT PRIMARY KEY,
                    debate_id     TEXT NOT NULL,
                    outcome_date  TEXT NOT NULL,
                    t1_return_pct REAL,
                    t3_return_pct REAL,
                    direction_correct INTEGER,
                    lessons       TEXT NOT NULL,
                    created_at    TEXT NOT NULL,
                    FOREIGN KEY (debate_id)
                        REFERENCES debate_records(debate_id)
                );
                CREATE INDEX IF NOT EXISTS idx_ref_debate
                    ON debate_reflections(debate_id);
                """
            )

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    # ── Store ─────────────────────────────────────────────────────

    def store(self, record_dict: dict[str, Any]) -> str:
        """Store a completed debate record.

        Args:
            record_dict: Output of ``DebateRecord.to_dict()``.

        Returns:
            debate_id for later reference.
        """
        debate_id = record_dict.get("debate_id", str(uuid.uuid4()))
        symbol = record_dict.get("symbol", "")
        name = record_dict.get("name", "")
        trigger = record_dict.get("trigger", "")
        final_action = record_dict.get("final_action", "hold")

        # Build searchable text from arguments
        text_parts = [symbol, name, trigger, final_action]
        for arg in record_dict.get("bull_arguments", []):
            text_parts.append(arg.get("claim", ""))
            text_parts.append(arg.get("evidence", ""))
        for arg in record_dict.get("bear_arguments", []):
            text_parts.append(arg.get("claim", ""))
            text_parts.append(arg.get("evidence", ""))
        verdict = record_dict.get("verdict") or {}
        text_parts.append(verdict.get("reasoning", ""))
        text_parts.append(verdict.get("key_risk", ""))

        tokens = _tokenize(" ".join(text_parts))

        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO debate_records
                   (debate_id, symbol, name, trigger, final_action,
                    verdict_json, bull_json, bear_json, tokens, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    debate_id,
                    symbol,
                    name,
                    trigger,
                    final_action,
                    json.dumps(verdict, ensure_ascii=False),
                    json.dumps(
                        record_dict.get("bull_arguments", []),
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        record_dict.get("bear_arguments", []),
                        ensure_ascii=False,
                    ),
                    json.dumps(tokens, ensure_ascii=False),
                    datetime.now(UTC).isoformat(),
                ),
            )
        logger.debug("Stored debate %s for %s (%s)", debate_id, symbol, final_action)
        return debate_id

    # ── Retrieve ──────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        symbol: str = "",
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Retrieve similar past debates via TF-IDF cosine similarity.

        Args:
            query: Free-text query (e.g. "资金流出 主力减仓").
            symbol: Optional — filter to this symbol only.
            top_k: Max results to return.

        Returns:
            List of debate dicts sorted by relevance, each containing
            symbol, name, final_action, verdict, bull/bear argument
            summaries, and similarity score.
        """
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        with self._conn() as conn:
            if symbol:
                rows = conn.execute(
                    "SELECT * FROM debate_records WHERE symbol = ? "
                    "ORDER BY created_at DESC LIMIT 100",
                    (symbol,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM debate_records ORDER BY created_at DESC LIMIT 200",
                ).fetchall()

        if not rows:
            return []

        # Build corpus for IDF
        corpus: list[list[str]] = []
        for row in rows:
            corpus.append(json.loads(row["tokens"]))
        corpus.append(query_tokens)  # Include query in IDF

        idf = _compute_idf(corpus)
        query_vec = _tfidf_vector(query_tokens, idf)

        scored: list[tuple[float, dict]] = []
        for i, row in enumerate(rows):
            doc_tokens = corpus[i]
            doc_vec = _tfidf_vector(doc_tokens, idf)
            score = _cosine_similarity(query_vec, doc_vec)
            if score > 0.01:
                scored.append(
                    (
                        score,
                        {
                            "debate_id": row["debate_id"],
                            "symbol": row["symbol"],
                            "name": row["name"],
                            "final_action": row["final_action"],
                            "verdict": json.loads(row["verdict_json"]),
                            "bull_count": len(json.loads(row["bull_json"])),
                            "bear_count": len(json.loads(row["bear_json"])),
                            "created_at": row["created_at"],
                            "similarity": round(score, 3),
                        },
                    )
                )

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:top_k]]

    # ── Reflection ────────────────────────────────────────────────

    def store_reflection(
        self,
        debate_id: str,
        outcome: dict[str, Any],
        lessons: list[str],
    ) -> None:
        """Store post-outcome reflection for a past debate.

        Args:
            debate_id: ID of the debate to reflect on.
            outcome: Dict with t1_return_pct, t3_return_pct, direction_correct.
            lessons: List of lesson strings (what went right/wrong).
        """
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO debate_reflections
                   (reflection_id, debate_id, outcome_date,
                    t1_return_pct, t3_return_pct, direction_correct,
                    lessons, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    debate_id,
                    outcome.get("date", datetime.now(UTC).strftime("%Y-%m-%d")),
                    outcome.get("t1_return_pct"),
                    outcome.get("t3_return_pct"),
                    outcome.get("direction_correct"),
                    json.dumps(lessons, ensure_ascii=False),
                    datetime.now(UTC).isoformat(),
                ),
            )
        logger.debug("Stored reflection for debate %s", debate_id)

    def get_reflection_context(
        self,
        symbol: str,
        top_k: int = 2,
    ) -> str:
        """Get formatted reflection context for prompt injection.

        Returns a Chinese-language summary of past lessons for this symbol.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT dr.symbol, dr.name, dr.final_action,
                          ref.t1_return_pct, ref.direction_correct,
                          ref.lessons
                   FROM debate_reflections ref
                   JOIN debate_records dr ON ref.debate_id = dr.debate_id
                   WHERE dr.symbol = ?
                   ORDER BY ref.created_at DESC
                   LIMIT ?""",
                (symbol, top_k),
            ).fetchall()

        if not rows:
            return ""

        lines = ["[历史辩论反思]"]
        for row in rows:
            action = row["final_action"]
            t1 = row["t1_return_pct"]
            correct = row["direction_correct"]
            lessons = json.loads(row["lessons"])
            result_str = f"T+1: {t1:+.1f}%" if t1 is not None else "待评估"
            correct_str = "正确" if correct else "错误" if correct is not None else "?"
            lines.append(
                f"- {row['name']}({row['symbol']}) {action} → "
                f"{result_str} ({correct_str})"
            )
            for lesson in lessons[:2]:
                lines.append(f"  教训: {lesson}")
        return "\n".join(lines)

    # ── Cleanup ───────────────────────────────────────────────────

    def cleanup(self, max_age_days: int = 90) -> int:
        """Remove debate records older than max_age_days."""
        cutoff = datetime.now(UTC).isoformat()[:10]
        # Simple date-prefix comparison (ISO format sorts correctly)
        from datetime import timedelta

        cutoff_dt = datetime.now(UTC) - timedelta(days=max_age_days)
        cutoff = cutoff_dt.isoformat()

        with self._conn() as conn:
            # Delete reflections first (FK)
            conn.execute(
                """DELETE FROM debate_reflections
                   WHERE debate_id IN (
                       SELECT debate_id FROM debate_records
                       WHERE created_at < ?
                   )""",
                (cutoff,),
            )
            cursor = conn.execute(
                "DELETE FROM debate_records WHERE created_at < ?",
                (cutoff,),
            )
            deleted = cursor.rowcount
        if deleted:
            logger.info("Cleaned up %d old debate records", deleted)
        return deleted
