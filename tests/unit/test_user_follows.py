"""Unit tests for UserConfigService follows & notification prefs (v20.0 Phase 4).

Tests cover:
- Default follows retrieval
- Follows update and persistence
- Merge behaviour on successive updates
- Default notification preferences
- Notification preferences update
- All 8 follow dimensions
- Notification prefs validation
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.web.services.user_config_service import UserConfigService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def svc(tmp_path: Path) -> UserConfigService:
    """Create a UserConfigService backed by a temporary SQLite database."""
    db_path = tmp_path / "test_agent.db"
    return UserConfigService(db_path=db_path)


# ---------------------------------------------------------------------------
# Follows tests
# ---------------------------------------------------------------------------


class TestGetFollowsDefault:
    """No follows set yet — returns empty/default UserFollows."""

    def test_get_follows_default(self, svc: UserConfigService) -> None:
        result = svc.get_follows()

        assert isinstance(result, dict)
        assert result["stocks"] == []
        assert result["sectors"] == []
        assert result["concepts"] == []
        assert result["signal_types"] == []
        assert result["risk_levels"] == []
        assert result["keywords"] == []
        assert result["indices"] == []
        assert result["macro_factors"] == []


class TestUpdateFollows:
    """Update follows with stocks list, verify persistence."""

    def test_update_follows(self, svc: UserConfigService) -> None:
        updated = svc.update_follows({"stocks": ["600519", "000858"]})

        assert updated["stocks"] == ["600519", "000858"]

        # Re-read from DB to verify persistence
        persisted = svc.get_follows()
        assert persisted["stocks"] == ["600519", "000858"]


class TestUpdateFollowsMerge:
    """Update follows twice — second call merges, not replaces."""

    def test_update_follows_merge(self, svc: UserConfigService) -> None:
        svc.update_follows({"stocks": ["600519"], "sectors": ["白酒"]})
        svc.update_follows({"keywords": ["半导体"], "sectors": ["芯片"]})

        result = svc.get_follows()

        # stocks from first update should remain
        assert result["stocks"] == ["600519"]
        # sectors should be overwritten by second update (dict.update semantics)
        assert result["sectors"] == ["芯片"]
        # keywords from second update should be present
        assert result["keywords"] == ["半导体"]


class TestFollows8Dimensions:
    """Set all 8 dimensions, verify all are returned."""

    def test_follows_8_dimensions(self, svc: UserConfigService) -> None:
        all_dims = {
            "stocks": ["600519"],
            "sectors": ["白酒"],
            "concepts": ["AI"],
            "signal_types": ["S1_TREND"],
            "risk_levels": ["LOW"],
            "keywords": ["芯片"],
            "indices": ["000001"],
            "macro_factors": ["GDP"],
        }
        updated = svc.update_follows(all_dims)

        for key, value in all_dims.items():
            assert updated[key] == value, f"Dimension {key} mismatch"

        # Also verify round-trip persistence
        persisted = svc.get_follows()
        for key, value in all_dims.items():
            assert persisted[key] == value, f"Persisted dimension {key} mismatch"


# ---------------------------------------------------------------------------
# Notification preferences tests
# ---------------------------------------------------------------------------


class TestGetNotificationPrefsDefault:
    """Returns default NotificationPrefs values."""

    def test_get_notification_prefs_default(self, svc: UserConfigService) -> None:
        result = svc.get_notification_prefs()

        assert isinstance(result, dict)
        assert result["quiet_hours_start"] == "22:00"
        assert result["quiet_hours_end"] == "08:00"
        assert result["max_daily_notifications"] == 50
        assert result["digest_interval_minutes"] == 30
        assert result["enabled_channels"] == ["app"]
        assert result["min_confidence_threshold"] == 30.0
        assert result["diversity_level"] == "medium"


class TestUpdateNotificationPrefs:
    """Update prefs, verify persistence."""

    def test_update_notification_prefs(self, svc: UserConfigService) -> None:
        updated = svc.update_notification_prefs(
            {
                "quiet_hours_start": "23:00",
                "max_daily_notifications": 20,
            }
        )

        assert updated["quiet_hours_start"] == "23:00"
        assert updated["max_daily_notifications"] == 20
        # Unchanged fields should have defaults
        assert updated["quiet_hours_end"] == "08:00"

        # Verify persistence
        persisted = svc.get_notification_prefs()
        assert persisted["quiet_hours_start"] == "23:00"
        assert persisted["max_daily_notifications"] == 20


class TestPrefsValidation:
    """Set valid prefs (quiet_hours, max_daily, etc.), verify."""

    def test_prefs_validation(self, svc: UserConfigService) -> None:
        prefs = {
            "quiet_hours_start": "21:30",
            "quiet_hours_end": "09:00",
            "max_daily_notifications": 100,
            "digest_interval_minutes": 60,
            "enabled_channels": ["app", "wecom"],
            "min_confidence_threshold": 50.0,
            "diversity_level": "high",
        }
        updated = svc.update_notification_prefs(prefs)

        for key, value in prefs.items():
            assert updated[key] == value, f"Pref {key} mismatch"

        # Round-trip persistence
        persisted = svc.get_notification_prefs()
        for key, value in prefs.items():
            assert persisted[key] == value, f"Persisted pref {key} mismatch"
