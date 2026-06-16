"""Tests for Profile Override API routes.

Covers GET/PUT/DELETE profile-overrides endpoints and industries list.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


MOCK_OVERRIDE = {
    "added_concepts": [{"code": "BK9999", "name": "自定义概念"}],
    "removed_concept_codes": [],
    "added_peers": [{"symbol": "NFLX", "market": "us", "tags": []}],
    "removed_peer_symbols": [],
    "added_keywords": ["春节档"],
    "removed_keywords": [],
    "industry_override": "entertainment",
    "updated_at": "2026-02-14T10:00:00",
}


@pytest.fixture
def client():
    """FastAPI TestClient with mocked services."""
    from src.web.dependencies import (
        get_association_profile_builder,
        get_holiday_research_service,
        get_profile_override_service,
    )
    from src.web.routes.api_v1.holiday_research import router

    mock_override_svc = MagicMock()
    mock_override_svc.get_override.return_value = MOCK_OVERRIDE
    mock_override_svc.set_override.return_value = MOCK_OVERRIDE
    mock_override_svc.delete_override.return_value = True

    mock_research_svc = MagicMock()
    mock_research_svc._get_holiday_key.return_value = "2026-02-24"
    mock_research_svc.collect_context.return_value = {
        "status": "success",
        "symbol": "001330",
    }

    mock_builder = MagicMock()
    mock_builder.get_available_industries.return_value = [
        {"tag": "entertainment", "display": "影视传媒"},
        {"tag": "shipping", "display": "航运物流"},
    ]

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/advisor/holiday-research")
    app.dependency_overrides[get_profile_override_service] = lambda: mock_override_svc
    app.dependency_overrides[get_holiday_research_service] = lambda: mock_research_svc
    app.dependency_overrides[get_association_profile_builder] = lambda: mock_builder

    yield TestClient(app)
    app.dependency_overrides.clear()


class TestProfileOverrideRoutes:
    def test_get_overrides(self, client):
        resp = client.get("/api/v1/advisor/holiday-research/001330/profile-overrides")
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_override"] is True
        assert data["symbol"] == "001330"
        assert data["industry_override"] == "entertainment"
        assert len(data["added_concepts"]) == 1

    def test_update_overrides(self, client):
        resp = client.put(
            "/api/v1/advisor/holiday-research/001330/profile-overrides",
            json={
                "added_keywords": ["票房"],
                "industry_override": "entertainment",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_override"] is True

    def test_delete_overrides(self, client):
        resp = client.delete(
            "/api/v1/advisor/holiday-research/001330/profile-overrides"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["symbol"] == "001330"

    def test_list_industries(self, client):
        resp = client.get("/api/v1/advisor/holiday-research/industries")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["industries"]) == 2
        assert data["industries"][0]["tag"] == "entertainment"

    def test_get_overrides_no_data(self, client):
        """When override service returns None, has_override should be False."""
        # Get the mock from the override
        from src.web.dependencies import get_profile_override_service

        mock_svc = client.app.dependency_overrides[get_profile_override_service]()
        mock_svc.get_override.return_value = None

        resp = client.get("/api/v1/advisor/holiday-research/999999/profile-overrides")
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_override"] is False
