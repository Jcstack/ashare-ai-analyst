"""Tests for scheduler API routes (FR-SS004)."""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.web.app import create_app
from src.web.dependencies import (
    get_sentinel_config_service,
    get_timeline_scheduler,
    get_trading_calendar,
)


def _mock_scheduler():
    scheduler = MagicMock()
    scheduler.get_status.return_value = {
        "current_profile": "trading_day",
        "override": None,
        "is_trading_day": True,
        "current_session": "morning",
        "is_holiday_period": False,
        "next_trading_day": "2026-02-16",
    }
    scheduler._config = {
        "profiles": {
            "trading_day": {"default": True, "tasks": {}},
            "holiday": {
                "default": False,
                "tasks": {"task_fetch_global_snapshot": True},
            },
        }
    }
    return scheduler


def _mock_calendar():
    cal = MagicMock()
    cal.is_trading_day.return_value = True
    cal.next_trading_day.return_value = MagicMock(isoformat=lambda: "2026-02-16")
    return cal


def _mock_sentinel_config_service():
    svc = MagicMock()
    svc.get_config.return_value = {
        "data_sources": {
            "global_markets": {"enabled": True, "provider": "yfinance"},
            "news_platforms": {
                "enabled": True,
                "platforms": ["eastmoney", "cls"],
                "refresh_interval": 1800,
            },
        },
        "notifications": {
            "channels": [
                {
                    "type": "wecom",
                    "enabled": False,
                    "events": ["risk_alert"],
                }
            ],
            "event_types": ["risk_alert", "sentiment_update"],
        },
    }
    return svc


def _create_test_client():
    app = create_app()
    mock_scheduler = _mock_scheduler()
    mock_cal = _mock_calendar()
    mock_sentinel = _mock_sentinel_config_service()

    app.dependency_overrides[get_timeline_scheduler] = lambda: mock_scheduler
    app.dependency_overrides[get_trading_calendar] = lambda: mock_cal
    app.dependency_overrides[get_sentinel_config_service] = lambda: mock_sentinel

    return TestClient(app), mock_scheduler, mock_sentinel


class TestSchedulerStatus:
    def test_get_status(self):
        client, scheduler, _ = _create_test_client()
        resp = client.get("/api/v1/scheduler/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_profile"] == "trading_day"
        assert data["is_trading_day"] is True
        assert data["override"] is None

    def test_get_status_with_override(self):
        client, scheduler, _ = _create_test_client()
        scheduler.get_status.return_value["override"] = "holiday"
        scheduler.get_status.return_value["current_profile"] = "holiday"
        resp = client.get("/api/v1/scheduler/status")
        data = resp.json()
        assert data["override"] == "holiday"


class TestSchedulerPlans:
    def test_get_plans(self):
        client, _, _ = _create_test_client()
        resp = client.get("/api/v1/scheduler/plans")
        assert resp.status_code == 200
        data = resp.json()
        assert "plans" in data
        assert len(data["plans"]) == 4  # 4 profiles
        plan_names = [p["name"] for p in data["plans"]]
        assert "trading_day" in plan_names
        assert "holiday" in plan_names

    def test_update_plan(self):
        client, scheduler, _ = _create_test_client()
        resp = client.put(
            "/api/v1/scheduler/plans/holiday",
            json={"tasks": {"task_sentiment_scan": True}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"

    def test_update_invalid_plan(self):
        client, _, _ = _create_test_client()
        resp = client.put(
            "/api/v1/scheduler/plans/nonexistent",
            json={"tasks": {"foo": True}},
        )
        assert resp.status_code == 400


class TestSchedulerOverride:
    def test_set_override(self):
        client, scheduler, _ = _create_test_client()
        resp = client.post(
            "/api/v1/scheduler/override",
            json={"profile": "holiday"},
        )
        assert resp.status_code == 200
        scheduler.set_override.assert_called_once()

    def test_clear_override(self):
        client, scheduler, _ = _create_test_client()
        resp = client.post(
            "/api/v1/scheduler/override",
            json={"profile": None},
        )
        assert resp.status_code == 200
        scheduler.set_override.assert_called_once_with(None)

    def test_invalid_override(self):
        client, _, _ = _create_test_client()
        resp = client.post(
            "/api/v1/scheduler/override",
            json={"profile": "invalid_profile"},
        )
        assert resp.status_code == 400


class TestSchedulerCalendar:
    def test_get_calendar(self):
        client, _, _ = _create_test_client()
        resp = client.get("/api/v1/scheduler/calendar?days=7")
        assert resp.status_code == 200
        data = resp.json()
        assert "days" in data
        assert "today" in data
        assert "next_trading_day" in data
        assert len(data["days"]) == 7


class TestSentinelConfig:
    def test_get_config(self):
        client, _, sentinel = _create_test_client()
        resp = client.get("/api/v1/scheduler/sentinel-config")
        assert resp.status_code == 200
        data = resp.json()
        assert "data_sources" in data
        assert "notifications" in data
        assert data["data_sources"]["global_markets"]["enabled"] is True

    def test_update_config(self):
        client, _, sentinel = _create_test_client()
        resp = client.put(
            "/api/v1/scheduler/sentinel-config",
            json={"data_sources": {"global_markets": {"enabled": False}}},
        )
        assert resp.status_code == 200
        sentinel.update_config.assert_called_once()
