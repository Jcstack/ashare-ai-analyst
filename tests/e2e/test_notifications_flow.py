"""E2E tests for notification endpoints.

QA cases: QA-NOTIF-001~004.
"""


class TestNotificationsFlow:
    def test_get_recent(self, client):
        """QA-NOTIF-001: Get recent notifications."""
        resp = client.get("/api/v1/notifications/recent")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_unread_count(self, client):
        """QA-NOTIF-002: Get unread notification count."""
        resp = client.get("/api/v1/notifications/unread-count")
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
        assert isinstance(data["count"], int)

    def test_mark_read(self, client):
        """QA-NOTIF-003: Mark specific notifications as read."""
        resp = client.post(
            "/api/v1/notifications/read",
            json=["n1"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_mark_all_read(self, client):
        """QA-NOTIF-004: Mark all notifications as read."""
        resp = client.post("/api/v1/notifications/read-all")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
