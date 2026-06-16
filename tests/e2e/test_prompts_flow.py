"""E2E tests for prompt management endpoints.

QA cases: QA-PROMPT-001~004.
"""


class TestPromptsFlow:
    def test_list_prompts(self, client):
        """QA-PROMPT-001: List all prompt templates."""
        resp = client.get("/api/v1/prompts")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_get_prompt(self, client):
        """QA-PROMPT-002: Get a specific prompt template by ID."""
        resp = client.get("/api/v1/prompts/p1")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert data["id"] == "p1"

    def test_create_prompt(self, client):
        """QA-PROMPT-003: Create a new prompt template."""
        resp = client.post(
            "/api/v1/prompts",
            json={"name": "Test", "user_template": "Analyze {symbol}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "id" in data

    def test_test_prompt(self, client):
        """QA-PROMPT-004: Execute a prompt template with test variables."""
        resp = client.post(
            "/api/v1/prompts/p1/test",
            json={"variables": {"symbol": "000001"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
