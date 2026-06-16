"""Tests for src/intelligence/memory_store.py."""

import sqlite3
from pathlib import Path

import pytest

from src.intelligence.memory_store import (
    MemoryConfig,
    MemoryStore,
    _compute_idf,
    _cosine_similarity,
    _tfidf_vector,
    _tokenize,
)


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_memory.db")


@pytest.fixture
def store(db_path: str) -> MemoryStore:
    config = MemoryConfig(db_path=db_path, max_entries=100, ttl_days=0)
    return MemoryStore(config)


class TestDatabaseInit:
    def test_creates_tables(self, store: MemoryStore, db_path: str):
        conn = sqlite3.connect(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        assert "memories" in [t[0] for t in tables]

    def test_creates_indexes(self, store: MemoryStore, db_path: str):
        conn = sqlite3.connect(db_path)
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        conn.close()
        names = [i[0] for i in indexes]
        assert "idx_memories_category" in names
        assert "idx_memories_symbol" in names


class TestStore:
    def test_basic_store(self, store: MemoryStore):
        mid = store.store("茅台MACD出现金叉信号", category="pattern", symbol="600519")
        assert mid
        assert len(mid) == 12

    def test_count_increases(self, store: MemoryStore):
        assert store.count() == 0
        store.store("记忆1")
        assert store.count() == 1
        store.store("记忆2")
        assert store.count() == 2

    def test_count_by_category(self, store: MemoryStore):
        store.store("pattern1", category="pattern")
        store.store("pattern2", category="pattern")
        store.store("error1", category="error")
        assert store.count(category="pattern") == 2
        assert store.count(category="error") == 1

    def test_store_with_metadata(self, store: MemoryStore):
        store.store(
            "茅台假期前规律",
            category="insight",
            symbol="600519",
            metadata={"holiday": "spring_festival", "accuracy": 0.72},
        )
        memories = store.get_by_symbol("600519")
        assert len(memories) == 1
        assert memories[0].metadata["holiday"] == "spring_festival"

    def test_capacity_eviction(self, db_path: str):
        config = MemoryConfig(db_path=db_path, max_entries=3, ttl_days=0)
        store = MemoryStore(config)
        store.store("记忆1")
        store.store("记忆2")
        store.store("记忆3")
        store.store("记忆4")  # Should evict oldest
        assert store.count() == 3


class TestRetrieve:
    def test_basic_retrieval(self, store: MemoryStore):
        store.store("茅台白酒板块走弱，资金流出", category="pattern", symbol="600519")
        store.store("宁德时代新能源反弹，资金流入", category="pattern", symbol="300750")
        store.store("银行板块整体承压", category="insight")

        results = store.retrieve("白酒板块资金")
        assert len(results) > 0
        # The 茅台 memory should be most relevant
        assert results[0].symbol == "600519"

    def test_category_filter(self, store: MemoryStore):
        store.store("pattern内容A", category="pattern")
        store.store("error内容B", category="error")

        results = store.retrieve("内容", category="pattern")
        assert all(r.category == "pattern" for r in results)

    def test_symbol_filter(self, store: MemoryStore):
        store.store("茅台分析A", symbol="600519")
        store.store("宁德分析B", symbol="300750")
        store.store("通用分析C")  # No symbol — should also match

        results = store.retrieve("分析", symbol="600519")
        # Should include 600519 specific + generic (no symbol)
        for r in results:
            assert r.symbol in ("600519", "")

    def test_empty_query(self, store: MemoryStore):
        store.store("some content")
        results = store.retrieve("")
        assert len(results) == 0

    def test_no_matches(self, store: MemoryStore):
        store.store("白酒板块走弱")
        results = store.retrieve("semiconductor technology chip")
        assert len(results) == 0

    def test_limit(self, store: MemoryStore):
        for i in range(10):
            store.store(f"资金流向分析记录{i}", category="pattern")
        results = store.retrieve("资金流向", limit=3)
        assert len(results) <= 3

    def test_relevance_scores_ordered(self, store: MemoryStore):
        store.store("白酒板块资金大幅流出")
        store.store("新能源汽车行业分析")
        store.store("白酒板块资金面偏空")
        results = store.retrieve("白酒资金流出")
        if len(results) >= 2:
            assert results[0].relevance_score >= results[1].relevance_score


class TestGetBySymbol:
    def test_basic(self, store: MemoryStore):
        store.store("A", symbol="600519")
        store.store("B", symbol="600519")
        store.store("C", symbol="300750")
        results = store.get_by_symbol("600519")
        assert len(results) == 2

    def test_with_category(self, store: MemoryStore):
        store.store("pattern1", category="pattern", symbol="600519")
        store.store("error1", category="error", symbol="600519")
        results = store.get_by_symbol("600519", category="pattern")
        assert len(results) == 1


class TestDelete:
    def test_delete_existing(self, store: MemoryStore):
        mid = store.store("to be deleted")
        assert store.count() == 1
        assert store.delete(mid) is True
        assert store.count() == 0

    def test_delete_nonexistent(self, store: MemoryStore):
        assert store.delete("nonexistent") is False


class TestCleanupExpired:
    def test_no_ttl(self, db_path: str):
        config = MemoryConfig(db_path=db_path, ttl_days=0)
        store = MemoryStore(config)
        store.store("content")
        assert store.cleanup_expired() == 0

    def test_with_ttl(self, db_path: str):
        config = MemoryConfig(db_path=db_path, ttl_days=1)
        store = MemoryStore(config)
        # Insert a memory with old timestamp
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            INSERT INTO memories
                (memory_id, category, content, content_tokens, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("old1", "pattern", "old memory", "[]", "2020-01-01T00:00:00"),
        )
        conn.commit()
        conn.close()
        deleted = store.cleanup_expired()
        assert deleted == 1


class TestTokenize:
    def test_chinese(self):
        tokens = _tokenize("白酒板块走弱")
        assert "白" in tokens
        assert "酒" in tokens

    def test_english(self):
        tokens = _tokenize("MACD golden cross signal")
        assert "macd" in tokens
        assert "golden" in tokens

    def test_mixed(self):
        tokens = _tokenize("茅台MACD出现金叉")
        assert "macd" in tokens
        assert "茅" in tokens

    def test_empty(self):
        assert _tokenize("") == []

    def test_short_words_filtered(self):
        tokens = _tokenize("I a am ok fine")
        # "I" and "a" are single chars, filtered out
        assert "am" in tokens
        assert "ok" in tokens


class TestTFIDF:
    def test_idf_computation(self):
        corpus = [
            ["白", "酒", "板", "块"],
            ["白", "酒", "资", "金"],
            ["新", "能", "源"],
        ]
        idf = _compute_idf(corpus)
        # "白" and "酒" appear in 2/3 docs, should have lower IDF
        # "新" appears in 1/3 docs, should have higher IDF
        assert idf["白"] < idf["新"]

    def test_tfidf_vector(self):
        idf = {"白": 1.5, "酒": 1.5, "资": 2.0, "金": 2.0}
        tokens = ["白", "酒", "资", "金"]
        vec = _tfidf_vector(tokens, idf)
        assert len(vec) == 4
        assert all(v > 0 for v in vec.values())

    def test_cosine_identical(self):
        vec = {"a": 1.0, "b": 2.0}
        sim = _cosine_similarity(vec, vec)
        assert sim == pytest.approx(1.0, abs=0.001)

    def test_cosine_orthogonal(self):
        vec_a = {"a": 1.0}
        vec_b = {"b": 1.0}
        sim = _cosine_similarity(vec_a, vec_b)
        assert sim == 0.0

    def test_cosine_empty(self):
        assert _cosine_similarity({}, {"a": 1.0}) == 0.0
        assert _cosine_similarity({"a": 1.0}, {}) == 0.0
