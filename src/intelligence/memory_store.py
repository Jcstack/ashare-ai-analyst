"""Memory store — vector-based experience accumulation and retrieval.

Part of v18.0 Intelligence Loop.

Stores analysis experiences (patterns, errors, insights) with TF-IDF-like
vector embeddings for semantic retrieval. Uses SQLite for persistence,
no external vector DB dependency.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Memory:
    """A stored memory entry."""

    memory_id: str
    category: str  # "pattern", "error", "insight", "prediction_review"
    content: str  # Natural language content
    metadata: dict[str, Any] = field(default_factory=dict)
    symbol: str = ""
    created_at: str = ""  # ISO datetime
    relevance_score: float = 0.0  # Set during retrieval


@dataclass
class MemoryConfig:
    """Configuration for memory store."""

    max_entries: int = 1000
    max_retrieval_results: int = 5
    ttl_days: int = 90  # 0 = no expiry
    db_path: str = "data/memory.db"


class MemoryStore:
    """SQLite-backed memory store with TF-IDF retrieval.

    Stores analysis experiences as text memories with category labels.
    Retrieval uses simple TF-IDF cosine similarity over Chinese/English
    tokenized content.

    Not a full vector database — designed for lightweight usage
    without external dependencies (no ChromaDB, no embedding models).
    """

    def __init__(self, config: MemoryConfig | None = None):
        self.config = config or MemoryConfig()
        self._db_path = Path(self.config.db_path)
        self._ensure_db()

    def _ensure_db(self) -> None:
        """Create database tables if they don't exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_tokens TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}',
                    symbol TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memories_category
                ON memories(category)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memories_symbol
                ON memories(symbol)
                """
            )
            conn.commit()
        finally:
            conn.close()

    def store(
        self,
        content: str,
        category: str = "insight",
        symbol: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store a new memory. Returns memory_id.

        If store is at capacity, evicts oldest entries first.
        """
        memory_id = str(uuid.uuid4())[:12]
        tokens = _tokenize(content)
        tokens_json = json.dumps(tokens, ensure_ascii=False)
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)

        conn = sqlite3.connect(str(self._db_path))
        try:
            # Check capacity and evict if needed
            count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            if count >= self.config.max_entries:
                excess = count - self.config.max_entries + 1
                conn.execute(
                    "DELETE FROM memories WHERE memory_id IN "
                    "(SELECT memory_id FROM memories ORDER BY created_at ASC LIMIT ?)",
                    (excess,),
                )

            conn.execute(
                """
                INSERT INTO memories
                    (memory_id, category, content, content_tokens, metadata, symbol)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (memory_id, category, content, tokens_json, meta_json, symbol),
            )
            conn.commit()
        finally:
            conn.close()

        logger.info(
            "Stored memory %s [%s] %s: %s",
            memory_id,
            category,
            symbol,
            content[:60],
        )
        return memory_id

    def retrieve(
        self,
        query: str,
        category: str | None = None,
        symbol: str | None = None,
        limit: int | None = None,
    ) -> list[Memory]:
        """Retrieve memories most relevant to the query.

        Uses TF-IDF cosine similarity for ranking.

        Args:
            query: Natural language query.
            category: Filter by category (optional).
            symbol: Filter by symbol (optional).
            limit: Max results (defaults to config.max_retrieval_results).

        Returns:
            List of Memory objects sorted by relevance (descending).
        """
        max_results = limit or self.config.max_retrieval_results
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            where_clauses = ["1=1"]
            params: list[Any] = []

            if category:
                where_clauses.append("category = ?")
                params.append(category)
            if symbol:
                where_clauses.append("(symbol = ? OR symbol = '')")
                params.append(symbol)

            # Apply TTL filter
            if self.config.ttl_days > 0:
                cutoff = (
                    datetime.now() - timedelta(days=self.config.ttl_days)
                ).isoformat()
                where_clauses.append("created_at >= ?")
                params.append(cutoff)

            where = " AND ".join(where_clauses)
            rows = conn.execute(
                f"SELECT * FROM memories WHERE {where}",  # noqa: S608
                params,
            ).fetchall()

            if not rows:
                return []

            # Build corpus for IDF calculation
            all_doc_tokens = []
            for row in rows:
                try:
                    doc_tokens = json.loads(row["content_tokens"])
                except (json.JSONDecodeError, TypeError):
                    doc_tokens = _tokenize(row["content"])
                all_doc_tokens.append(doc_tokens)

            idf = _compute_idf(all_doc_tokens)

            # Score each document against query
            query_vec = _tfidf_vector(query_tokens, idf)
            scored: list[tuple[float, sqlite3.Row, list[str]]] = []
            for row, doc_tokens in zip(rows, all_doc_tokens):
                doc_vec = _tfidf_vector(doc_tokens, idf)
                score = _cosine_similarity(query_vec, doc_vec)
                if score > 0:
                    scored.append((score, row, doc_tokens))

            # Sort by score descending
            scored.sort(key=lambda x: x[0], reverse=True)

            results = []
            for score, row, _ in scored[:max_results]:
                try:
                    meta = json.loads(row["metadata"])
                except (json.JSONDecodeError, TypeError):
                    meta = {}
                results.append(
                    Memory(
                        memory_id=row["memory_id"],
                        category=row["category"],
                        content=row["content"],
                        metadata=meta,
                        symbol=row["symbol"],
                        created_at=row["created_at"],
                        relevance_score=round(score, 4),
                    )
                )

            return results
        finally:
            conn.close()

    def get_by_symbol(
        self,
        symbol: str,
        category: str | None = None,
        limit: int = 10,
    ) -> list[Memory]:
        """Get all memories for a specific symbol."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            where = "symbol = ?"
            params: list[Any] = [symbol]
            if category:
                where += " AND category = ?"
                params.append(category)

            rows = conn.execute(
                f"SELECT * FROM memories WHERE {where} "  # noqa: S608
                f"ORDER BY created_at DESC LIMIT ?",
                [*params, limit],
            ).fetchall()

            results = []
            for row in rows:
                try:
                    meta = json.loads(row["metadata"])
                except (json.JSONDecodeError, TypeError):
                    meta = {}
                results.append(
                    Memory(
                        memory_id=row["memory_id"],
                        category=row["category"],
                        content=row["content"],
                        metadata=meta,
                        symbol=row["symbol"],
                        created_at=row["created_at"],
                    )
                )
            return results
        finally:
            conn.close()

    def delete(self, memory_id: str) -> bool:
        """Delete a specific memory."""
        conn = sqlite3.connect(str(self._db_path))
        try:
            cursor = conn.execute(
                "DELETE FROM memories WHERE memory_id = ?",
                (memory_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def cleanup_expired(self) -> int:
        """Remove memories older than TTL. Returns count deleted."""
        if self.config.ttl_days <= 0:
            return 0

        cutoff = (datetime.now() - timedelta(days=self.config.ttl_days)).isoformat()
        conn = sqlite3.connect(str(self._db_path))
        try:
            cursor = conn.execute(
                "DELETE FROM memories WHERE created_at < ?",
                (cutoff,),
            )
            conn.commit()
            deleted = cursor.rowcount
            if deleted > 0:
                logger.info("Cleaned up %d expired memories", deleted)
            return deleted
        finally:
            conn.close()

    def count(self, category: str | None = None) -> int:
        """Count stored memories."""
        conn = sqlite3.connect(str(self._db_path))
        try:
            if category:
                row = conn.execute(
                    "SELECT COUNT(*) FROM memories WHERE category = ?",
                    (category,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
            return row[0] if row else 0
        finally:
            conn.close()


# ── TF-IDF helpers ──────────────────────────────────────────────


def _tokenize(text: str) -> list[str]:
    """Simple tokenization for Chinese + English text.

    Splits on whitespace and punctuation, keeps Chinese characters
    as individual tokens (character-level for CJK).
    """
    if not text:
        return []

    # Normalize
    text = text.lower().strip()

    tokens: list[str] = []
    current_word: list[str] = []

    for char in text:
        if "\u4e00" <= char <= "\u9fff":
            # CJK character — flush current word, add char as token
            if current_word:
                word = "".join(current_word)
                if len(word) >= 2:
                    tokens.append(word)
                current_word = []
            tokens.append(char)
        elif char.isalnum():
            current_word.append(char)
        else:
            # Separator
            if current_word:
                word = "".join(current_word)
                if len(word) >= 2:
                    tokens.append(word)
                current_word = []

    # Flush remaining
    if current_word:
        word = "".join(current_word)
        if len(word) >= 2:
            tokens.append(word)

    return tokens


def _compute_idf(corpus: list[list[str]]) -> dict[str, float]:
    """Compute IDF (inverse document frequency) for a corpus."""
    n_docs = len(corpus)
    if n_docs == 0:
        return {}

    doc_freq: Counter[str] = Counter()
    for doc_tokens in corpus:
        unique_tokens = set(doc_tokens)
        for token in unique_tokens:
            doc_freq[token] += 1

    idf: dict[str, float] = {}
    for token, df in doc_freq.items():
        idf[token] = math.log((n_docs + 1) / (df + 1)) + 1  # Smoothed IDF

    return idf


def _tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    """Compute TF-IDF vector for a token list."""
    if not tokens:
        return {}

    tf = Counter(tokens)
    max_tf = max(tf.values()) if tf else 1

    vector: dict[str, float] = {}
    for token, count in tf.items():
        normalized_tf = count / max_tf  # Augmented TF
        token_idf = idf.get(token, 1.0)
        vector[token] = normalized_tf * token_idf

    return vector


def _cosine_similarity(
    vec_a: dict[str, float],
    vec_b: dict[str, float],
) -> float:
    """Compute cosine similarity between two sparse vectors."""
    if not vec_a or not vec_b:
        return 0.0

    # Dot product (only shared keys)
    shared_keys = set(vec_a.keys()) & set(vec_b.keys())
    if not shared_keys:
        return 0.0

    dot = sum(vec_a[k] * vec_b[k] for k in shared_keys)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)
