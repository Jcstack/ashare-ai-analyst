"""Tests for ProfileOverrideService.

Covers CRUD operations, persistence to JSON file, directory creation,
backup on save, and multi-symbol management.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.web.services.profile_override_service import ProfileOverrideService


@pytest.fixture
def svc(tmp_path: Path):
    """ProfileOverrideService writing to a temp directory."""
    override_path = tmp_path / "profile_overrides.json"
    with patch.object(
        ProfileOverrideService, "_resolve_path", return_value=override_path
    ):
        return ProfileOverrideService()


@pytest.fixture
def svc_with_data(tmp_path: Path):
    """ProfileOverrideService with pre-existing data."""
    override_path = tmp_path / "profile_overrides.json"
    data = {
        "001330": {
            "added_concepts": [{"code": "BK9999", "name": "自定义概念"}],
            "removed_concept_codes": [],
            "added_peers": [],
            "removed_peer_symbols": [],
            "added_keywords": ["春节档"],
            "removed_keywords": [],
            "industry_override": "entertainment",
            "updated_at": "2026-02-14T10:00:00",
        }
    }
    override_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with patch.object(
        ProfileOverrideService, "_resolve_path", return_value=override_path
    ):
        return ProfileOverrideService()


class TestGetOverride:
    def test_returns_none_for_unknown_symbol(self, svc):
        assert svc.get_override("999999") is None

    def test_returns_existing_override(self, svc_with_data):
        result = svc_with_data.get_override("001330")
        assert result is not None
        assert result["industry_override"] == "entertainment"
        assert len(result["added_concepts"]) == 1
        assert result["added_keywords"] == ["春节档"]


class TestSetOverride:
    def test_creates_new_override(self, svc):
        result = svc.set_override(
            "600000",
            {
                "added_keywords": ["银行", "金融"],
                "industry_override": "banking",
            },
        )
        assert result["added_keywords"] == ["银行", "金融"]
        assert result["industry_override"] == "banking"
        assert "updated_at" in result

        # Verify persistence
        reloaded = svc.get_override("600000")
        assert reloaded is not None
        assert reloaded["industry_override"] == "banking"

    def test_merges_with_existing(self, svc_with_data):
        result = svc_with_data.set_override(
            "001330",
            {
                "added_keywords": ["票房"],
            },
        )
        # New keyword replaces the old list
        assert result["added_keywords"] == ["票房"]
        # Other fields preserved
        assert result["industry_override"] == "entertainment"
        assert len(result["added_concepts"]) == 1

    def test_ignores_unknown_keys(self, svc):
        result = svc.set_override(
            "600000",
            {
                "added_keywords": ["test"],
                "unknown_field": "ignored",
            },
        )
        assert "unknown_field" not in result

    def test_creates_backup_on_save(self, svc, tmp_path):
        svc.set_override("600000", {"added_keywords": ["first"]})
        svc.set_override("600000", {"added_keywords": ["second"]})

        backup = svc._path.with_suffix(".json.bak")
        assert backup.exists()
        backup_data = json.loads(backup.read_text())
        assert backup_data["600000"]["added_keywords"] == ["first"]


class TestDeleteOverride:
    def test_deletes_existing(self, svc_with_data):
        assert svc_with_data.delete_override("001330") is True
        assert svc_with_data.get_override("001330") is None

    def test_returns_false_for_nonexistent(self, svc):
        assert svc.delete_override("999999") is False


class TestListOverrides:
    def test_returns_all(self, svc_with_data):
        svc_with_data.set_override("600000", {"added_keywords": ["test"]})
        result = svc_with_data.list_overrides()
        assert "001330" in result
        assert "600000" in result

    def test_empty_when_no_overrides(self, svc):
        assert svc.list_overrides() == {}


class TestPersistence:
    def test_survives_reload(self, tmp_path):
        override_path = tmp_path / "profile_overrides.json"
        with patch.object(
            ProfileOverrideService, "_resolve_path", return_value=override_path
        ):
            svc1 = ProfileOverrideService()
            svc1.set_override("001330", {"added_keywords": ["持久化测试"]})

        # Create a new instance (simulating restart)
        with patch.object(
            ProfileOverrideService, "_resolve_path", return_value=override_path
        ):
            svc2 = ProfileOverrideService()
            result = svc2.get_override("001330")
            assert result is not None
            assert result["added_keywords"] == ["持久化测试"]
