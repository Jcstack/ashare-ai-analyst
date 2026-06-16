"""Tests for UserConfigService investment style config.

Part of v28.0 Smart Stock Recommendation System.
"""

from __future__ import annotations

import pytest

from src.web.schemas.user_config import InvestmentStyleConfig
from src.web.services.user_config_service import UserConfigService


class TestInvestmentStyleConfig:
    """Tests for InvestmentStyleConfig schema."""

    def test_defaults(self) -> None:
        """Default config should have value style."""
        config = InvestmentStyleConfig()
        assert config.styles == ["value"]
        assert config.sector_preferences == []
        assert config.blacklist == []
        assert config.session_toggles["pre_market"] is True

    def test_multiple_styles(self) -> None:
        """Should accept 1-3 styles."""
        config = InvestmentStyleConfig(styles=["value", "growth", "momentum"])
        assert len(config.styles) == 3

    def test_sector_preferences(self) -> None:
        """Should accept up to 5 sectors."""
        config = InvestmentStyleConfig(sector_preferences=["白酒", "新能源", "半导体"])
        assert len(config.sector_preferences) == 3

    def test_session_toggles(self) -> None:
        """Can disable specific sessions."""
        config = InvestmentStyleConfig(
            session_toggles={
                "pre_market": False,
                "early": True,
                "mid": True,
                "late": True,
                "post_market": False,
            }
        )
        assert config.session_toggles["pre_market"] is False
        assert config.session_toggles["early"] is True

    def test_blacklist(self) -> None:
        """Blacklist should accept symbols."""
        config = InvestmentStyleConfig(blacklist=["600519", "000858"])
        assert "600519" in config.blacklist

    def test_model_dump(self) -> None:
        """model_dump should produce JSON-compatible dict."""
        config = InvestmentStyleConfig(
            styles=["value", "growth"],
            sector_preferences=["白酒"],
            blacklist=["600519"],
        )
        d = config.model_dump()
        assert d["styles"] == ["value", "growth"]
        assert d["sector_preferences"] == ["白酒"]
        assert d["blacklist"] == ["600519"]


class TestUserConfigServiceStyleConfig:
    """Tests for UserConfigService investment style config methods."""

    @pytest.fixture()
    def svc(self, tmp_path) -> UserConfigService:
        return UserConfigService(db_path=tmp_path / "test_config.db")

    def test_get_default(self, svc: UserConfigService) -> None:
        """Get default config when nothing stored."""
        config = svc.get_investment_style_config()
        assert config["styles"] == ["value"]
        assert config["blacklist"] == []

    def test_update_and_get(self, svc: UserConfigService) -> None:
        """Update and retrieve config."""
        updated = svc.update_investment_style_config(
            {"styles": ["value", "growth"], "blacklist": ["600519"]}
        )
        assert updated["styles"] == ["value", "growth"]
        assert updated["blacklist"] == ["600519"]

        # Retrieve
        config = svc.get_investment_style_config()
        assert config["styles"] == ["value", "growth"]

    def test_merge_update(self, svc: UserConfigService) -> None:
        """Update should merge with existing config."""
        svc.update_investment_style_config(
            {"styles": ["momentum"], "sector_preferences": ["白酒"]}
        )
        # Now update only blacklist
        updated = svc.update_investment_style_config({"blacklist": ["000858"]})
        assert updated["styles"] == ["momentum"]
        assert updated["sector_preferences"] == ["白酒"]
        assert updated["blacklist"] == ["000858"]
