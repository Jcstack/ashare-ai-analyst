"""Unit tests for src/web/services/admin_service.py — AdminService.

Tests key management, usage dashboard, balance checks, and routing updates.
"""

from unittest.mock import MagicMock, patch

from src.llm.base import ProviderName


class TestAdminService:
    """Tests for AdminService."""

    def _make_service(self):
        """Create an AdminService with mocked dependencies."""
        from src.web.services.admin_service import AdminService

        mock_router = MagicMock()
        mock_router.available_providers = [
            ProviderName.ANTHROPIC,
            ProviderName.OPENAI,
        ]
        mock_provider = MagicMock()
        mock_provider.check_balance.return_value = {
            "provider": "anthropic",
            "status": "active",
        }
        mock_router.get_provider.return_value = mock_provider

        svc = AdminService(router=mock_router)
        svc._key_manager = MagicMock()
        svc._usage_tracker = MagicMock()
        return svc

    def test_list_keys(self):
        svc = self._make_service()
        svc._key_manager.list_keys.return_value = [
            {"provider": "anthropic", "label": "test", "key": "sk-te***"}
        ]
        keys = svc.list_keys()
        assert len(keys) == 1
        assert keys[0]["provider"] == "anthropic"

    def test_add_key_success(self):
        svc = self._make_service()
        result = svc.add_key("anthropic", "sk-test", "my-key")
        assert result["status"] == "success"
        svc._key_manager.add_key.assert_called_once()

    def test_add_key_invalid_provider(self):
        svc = self._make_service()
        result = svc.add_key("invalid_provider", "key", "label")
        assert result["status"] == "error"

    def test_remove_key_success(self):
        svc = self._make_service()
        svc._key_manager.remove_key.return_value = True
        result = svc.remove_key("anthropic", "my-key")
        assert result["status"] == "success"

    def test_remove_key_not_found(self):
        svc = self._make_service()
        svc._key_manager.remove_key.return_value = False
        result = svc.remove_key("anthropic", "nope")
        assert result["status"] == "error"

    def test_remove_key_invalid_provider(self):
        svc = self._make_service()
        result = svc.remove_key("invalid", "label")
        assert result["status"] == "error"

    def test_check_balances(self):
        svc = self._make_service()
        balances = svc.check_balances()
        assert len(balances) == 2  # anthropic + openai

    def test_get_usage_dashboard(self):
        svc = self._make_service()
        svc._usage_tracker.get_daily_summary.return_value = {
            "total_calls": 5,
            "total_cost_usd": 0.01,
        }
        svc._usage_tracker.get_total_cost.return_value = 0.05
        svc._usage_tracker.get_provider_summary.return_value = {
            "total_calls": 3,
        }

        dashboard = svc.get_usage_dashboard()
        assert "today" in dashboard
        assert "total_cost_usd" in dashboard
        assert "providers" in dashboard

    def test_get_routing_config(self):
        svc = self._make_service()
        config = svc.get_routing_config()
        assert "available_providers" in config
        assert "strategies" in config
        assert "cost" in config["strategies"]

    def test_update_routing_strategy_valid(self):
        svc = self._make_service()
        result = svc.update_routing_strategy("cost")
        assert result["status"] == "success"

    def test_update_routing_strategy_invalid(self):
        svc = self._make_service()
        result = svc.update_routing_strategy("invalid_strategy")
        assert result["status"] == "error"

    @patch("src.web.services.admin_service.load_config")
    def test_update_watchlist(self, mock_load_config):
        mock_load_config.return_value = {"watchlist": []}
        svc = self._make_service()
        new_watchlist = [
            {"symbol": "000001", "name": "平安银行", "board": "main"},
        ]
        result = svc.update_watchlist(new_watchlist)
        assert result["status"] == "success"
        assert len(result["watchlist"]) == 1

    @patch("src.web.services.admin_service.load_config")
    def test_update_analysis_params_success(self, mock_load_config):
        mock_load_config.return_value = {"indicators": {"rsi_period": 14}}
        svc = self._make_service()
        result = svc.update_analysis_params("analysis", {"rsi_period": 21})
        assert result["status"] == "success"
        assert "rsi_period" in result["updated_keys"]

    @patch("src.web.services.admin_service.load_config")
    def test_update_analysis_params_error(self, mock_load_config):
        mock_load_config.side_effect = FileNotFoundError("not found")
        svc = self._make_service()
        result = svc.update_analysis_params("bad_section", {})
        assert result["status"] == "error"
