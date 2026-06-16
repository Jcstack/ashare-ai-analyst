"""Tests for trade execution gate (require_market_open dependency).

Validates:
- 409 when market closed (mock time)
- Success when market open (mock time)
- Liquidation still works when closed
- Response contains MARKET_CLOSED code and next_trading_time
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from src.web.routes.api_v1.trades import require_market_open

_PATCH_SIM = "src.web.routes.api_v1.trades._is_simulation_mode"


def _make_status(is_trading: bool, label: str = "已休市", status: str = "closed"):
    """Build a mock market status dict."""
    return {
        "status": status,
        "label": label,
        "is_trading": is_trading,
        "next_event": {
            "type": "open",
            "time": "2026-03-02 09:30",
            "countdown_seconds": 36000,
        },
        "holiday_info": None,
        "is_emergency": False,
        "emergency_reason": None,
    }


class TestRequireMarketOpen:
    """Test the require_market_open() FastAPI dependency."""

    def test_raises_409_when_market_closed(self):
        with (
            patch(_PATCH_SIM, return_value=False),
            patch(
                "src.utils.market_hours.get_market_status_for_ui",
                return_value=_make_status(is_trading=False),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                require_market_open()

            assert exc_info.value.status_code == 409
            detail = exc_info.value.detail
            assert detail["code"] == "MARKET_CLOSED"
            assert "next_trading_time" in detail
            assert "当前" in detail["message"]

    def test_passes_when_market_open(self):
        with (
            patch(_PATCH_SIM, return_value=False),
            patch(
                "src.utils.market_hours.get_market_status_for_ui",
                return_value=_make_status(
                    is_trading=True, label="交易中", status="trading"
                ),
            ),
        ):
            # Should not raise
            require_market_open()

    def test_passes_in_simulation_mode_even_when_closed(self):
        """Simulation mode bypasses market hour checks."""
        with patch(_PATCH_SIM, return_value=True):
            # Should not raise even though market is closed
            require_market_open()

    def test_409_includes_holiday_info_when_holiday(self):
        status = _make_status(is_trading=False, label="春节休市", status="holiday")
        status["holiday_info"] = {
            "name": "春节",
            "end_date": "2026-02-24",
            "days_remaining": 5,
        }
        with (
            patch(_PATCH_SIM, return_value=False),
            patch(
                "src.utils.market_hours.get_market_status_for_ui",
                return_value=status,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                require_market_open()

            detail = exc_info.value.detail
            assert detail["code"] == "MARKET_CLOSED"
            assert "holiday_info" in detail
            assert detail["holiday_info"]["name"] == "春节"

    def test_409_during_emergency(self):
        status = _make_status(is_trading=False, label="紧急停牌", status="emergency")
        status["is_emergency"] = True
        status["emergency_reason"] = "熔断"
        with (
            patch(_PATCH_SIM, return_value=False),
            patch(
                "src.utils.market_hours.get_market_status_for_ui",
                return_value=status,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                require_market_open()

            assert exc_info.value.status_code == 409
            assert exc_info.value.detail["code"] == "MARKET_CLOSED"


class TestLiquidationNotGated:
    """Liquidation endpoint should NOT have the market gate dependency.

    We verify this by checking that the endpoint definitions don't include
    require_market_open in their dependencies.
    """

    def test_liquidation_endpoint_not_gated(self):
        from src.web.routes.api_v1 import portfolio

        # Find the liquidate route
        for route in portfolio.router.routes:
            if hasattr(route, "path") and "liquidate" in getattr(route, "path", ""):
                # Check that require_market_open is NOT in its dependencies
                deps = getattr(route, "dependencies", [])
                dep_callables = [d.dependency for d in deps if hasattr(d, "dependency")]
                assert require_market_open not in dep_callables
