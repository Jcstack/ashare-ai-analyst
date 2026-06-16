"""E2E tests for scheduler management endpoints.

QA cases: QA-SCHED-001~004.
"""


class TestSchedulerFlow:
    def test_scheduler_status(self, client):
        """QA-SCHED-001: Scheduler status returns current mode."""
        resp = client.get("/api/v1/scheduler/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "mode" in data

    def test_scheduler_plans(self, client):
        """QA-SCHED-002: Scheduler plans returns plan list."""
        resp = client.get("/api/v1/scheduler/plans")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "plans" in data
        assert isinstance(data["plans"], list)

    def test_scheduler_override(self, client):
        """QA-SCHED-003: Override sets scheduler to holiday mode."""
        resp = client.post(
            "/api/v1/scheduler/override",
            json={"profile": "holiday"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"

    def test_scheduler_calendar(self, client):
        """QA-SCHED-004: Calendar returns list of upcoming trading days."""
        resp = client.get("/api/v1/scheduler/calendar")
        assert resp.status_code == 200
        data = resp.json()
        assert "days" in data
        assert isinstance(data["days"], list)
        assert len(data["days"]) > 0
