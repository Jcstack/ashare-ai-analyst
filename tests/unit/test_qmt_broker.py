"""Unit tests for QmtBroker with mocked xttrader."""

from __future__ import annotations

from unittest.mock import patch

import pytest


class TestQmtBrokerCreation:
    """Test QmtBroker instantiation."""

    def test_requires_xttrader(self):
        """Should raise when xttrader not installed."""
        with patch("src.web.services.qmt_broker._HAS_XTTRADER", False):
            from src.web.services.qmt_broker import QmtBroker

            with pytest.raises(RuntimeError, match="requires xtquant"):
                QmtBroker(config={"qmt": {"account_id": "test"}})

    def test_requires_account_id(self):
        """Should raise when account_id is missing."""
        with patch("src.web.services.qmt_broker._HAS_XTTRADER", True):
            from src.web.services.qmt_broker import QmtBroker

            with pytest.raises(ValueError, match="account_id"):
                QmtBroker(config={"qmt": {"account_id": ""}})


class TestQmtBrokerOrderValidation:
    """Test order validation logic."""

    @pytest.fixture
    def broker(self):
        """Create a QmtBroker with mocked xttrader."""
        with (
            patch("src.web.services.qmt_broker._HAS_XTTRADER", True),
            patch("src.web.services.qmt_broker.xttrader"),
            patch("src.web.services.qmt_broker.xtconstant"),
        ):
            from src.web.services.qmt_broker import QmtBroker

            b = QmtBroker(
                config={
                    "qmt": {
                        "account_id": "test-123",
                        "mini_qmt_path": "/mock",
                        "max_order_amount": 50000,
                        "allowed_actions": ["buy", "sell"],
                    }
                }
            )
            return b

    def test_rejects_disallowed_action(self, broker):
        result = broker.submit_order("600000", "short", 100, 10.0)
        assert result.status == "rejected"
        assert "not allowed" in result.message

    def test_rejects_exceeding_amount(self, broker):
        result = broker.submit_order("600000", "buy", 10000, 10.0)
        assert result.status == "rejected"
        assert "exceeds limit" in result.message

    def test_rejects_non_lot_shares(self, broker):
        result = broker.submit_order("600000", "buy", 55, 10.0)
        assert result.status == "rejected"
        assert "lots of 100" in result.message

    def test_rejects_zero_shares(self, broker):
        result = broker.submit_order("600000", "buy", 0, 10.0)
        assert result.status == "rejected"

    def test_mode_is_qmt(self, broker):
        assert broker.mode == "qmt"


class TestBrokerFactoryQMT:
    """Test that create_broker supports QMT mode."""

    def test_factory_returns_simulation_by_default(self):
        from src.web.services.broker_interface import create_broker

        with patch("src.web.services.broker_interface.load_config") as mock_cfg:
            mock_cfg.return_value = {}
            broker = create_broker()
            assert broker.mode == "simulation"

    def test_factory_qmt_falls_back_to_simulation(self):
        """QMT mode should fall back to simulation when xttrader unavailable."""
        from src.web.services.broker_interface import create_broker

        with (
            patch("src.web.services.broker_interface.load_config") as mock_cfg,
            patch(
                "src.web.services.qmt_broker._HAS_XTTRADER",
                False,
            ),
        ):
            mock_cfg.return_value = {"mode": "qmt"}
            broker = create_broker()
            assert broker.mode == "simulation"
