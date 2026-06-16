"""Tests for feature store cache.

Part of v15.0 Quant Core layer.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from src.quant.feature_store import FeatureDefinition, FeatureStore, FeatureValue

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_quant_config():
    return {
        "feature_store": {
            "default_ttl_seconds": 60,
            "max_features_per_symbol": 5,
            "version_prefix": "v1",
            "categories": [
                "momentum",
                "mean_reversion",
                "volatility",
                "volume",
                "technical",
            ],
        }
    }


@pytest.fixture
def store(mock_quant_config):
    with patch("src.quant.feature_store.load_config", return_value=mock_quant_config):
        return FeatureStore()


@pytest.fixture
def rsi_def():
    return FeatureDefinition(
        name="rsi_14", category="momentum", description="RSI 14-period"
    )


@pytest.fixture
def macd_def():
    return FeatureDefinition(
        name="macd_hist", category="momentum", description="MACD histogram"
    )


@pytest.fixture
def vol_def():
    return FeatureDefinition(
        name="atr_20", category="volatility", description="ATR 20-period"
    )


# ---------------------------------------------------------------------------
# FeatureDefinition tests
# ---------------------------------------------------------------------------


class TestFeatureDefinition:
    def test_defaults(self):
        fd = FeatureDefinition(name="test", category="momentum")
        assert fd.name == "test"
        assert fd.category == "momentum"
        assert fd.version == "v1"
        assert fd.params == {}

    def test_custom(self):
        fd = FeatureDefinition(
            name="rsi_14",
            category="momentum",
            version="v2",
            params={"period": 14},
        )
        assert fd.params["period"] == 14


class TestFeatureValue:
    def test_defaults(self):
        fd = FeatureDefinition(name="test", category="momentum")
        fv = FeatureValue(definition=fd, symbol="600519", value=45.2)
        assert fv.symbol == "600519"
        assert fv.value == 45.2


# ---------------------------------------------------------------------------
# FeatureStore tests
# ---------------------------------------------------------------------------


class TestFeatureStore:
    def test_config_loaded(self, store):
        assert store.default_ttl == 60
        assert store.max_features_per_symbol == 5
        assert "momentum" in store.categories

    def test_put_and_get(self, store, rsi_def):
        store.put("600519", rsi_def, value=45.2)
        result = store.get("600519", "rsi_14")
        assert result is not None
        assert result.value == 45.2
        assert result.symbol == "600519"

    def test_get_nonexistent(self, store):
        result = store.get("600519", "nonexistent")
        assert result is None

    def test_ttl_expiry(self, store, rsi_def):
        store.put("600519", rsi_def, value=45.2, ttl=0)
        time.sleep(0.01)
        result = store.get("600519", "rsi_14")
        assert result is None

    def test_custom_ttl(self, store, rsi_def):
        fv = store.put("600519", rsi_def, value=45.2, ttl=3600)
        assert fv.expires_at > fv.computed_at

    def test_get_all(self, store, rsi_def, macd_def, vol_def):
        store.put("600519", rsi_def, value=45.2)
        store.put("600519", macd_def, value=0.05)
        store.put("600519", vol_def, value=2.3)
        results = store.get_all("600519")
        assert len(results) == 3

    def test_get_all_empty(self, store):
        results = store.get_all("999999")
        assert results == []

    def test_get_all_filters_expired(self, store, rsi_def, macd_def):
        store.put("600519", rsi_def, value=45.2, ttl=0)
        store.put("600519", macd_def, value=0.05, ttl=3600)
        time.sleep(0.01)
        results = store.get_all("600519")
        assert len(results) == 1
        assert results[0].definition.name == "macd_hist"

    def test_get_by_category(self, store, rsi_def, macd_def, vol_def):
        store.put("600519", rsi_def, value=45.2)
        store.put("600519", macd_def, value=0.05)
        store.put("600519", vol_def, value=2.3)
        momentum = store.get_by_category("600519", "momentum")
        assert len(momentum) == 2
        volatility = store.get_by_category("600519", "volatility")
        assert len(volatility) == 1

    def test_invalidate_specific(self, store, rsi_def, macd_def):
        store.put("600519", rsi_def, value=45.2)
        store.put("600519", macd_def, value=0.05)
        removed = store.invalidate("600519", "rsi_14")
        assert removed == 1
        assert store.get("600519", "rsi_14") is None
        assert store.get("600519", "macd_hist") is not None

    def test_invalidate_all(self, store, rsi_def, macd_def):
        store.put("600519", rsi_def, value=45.2)
        store.put("600519", macd_def, value=0.05)
        removed = store.invalidate("600519")
        assert removed == 2
        assert store.get_all("600519") == []

    def test_invalidate_nonexistent(self, store):
        assert store.invalidate("600519", "nonexistent") == 0

    def test_cleanup_expired(self, store, rsi_def, macd_def):
        store.put("600519", rsi_def, value=45.2, ttl=0)
        store.put("300750", macd_def, value=0.05, ttl=0)
        store.put("600519", macd_def, value=0.1, ttl=3600)
        time.sleep(0.01)
        removed = store.cleanup_expired()
        assert removed == 2

    def test_max_features_eviction(self, store):
        """Test that oldest feature is evicted when max is reached."""
        for i in range(5):
            defn = FeatureDefinition(name=f"feat_{i}", category="momentum")
            store.put("600519", defn, value=i)

        # All 5 should be stored
        assert len(store.get_all("600519")) == 5

        # Adding 6th should evict the oldest
        defn6 = FeatureDefinition(name="feat_new", category="momentum")
        store.put("600519", defn6, value=99)
        all_feats = store.get_all("600519")
        assert len(all_feats) == 5
        names = [f.definition.name for f in all_feats]
        assert "feat_new" in names

    def test_different_symbols(self, store, rsi_def):
        store.put("600519", rsi_def, value=45.2)
        store.put("300750", rsi_def, value=52.1)
        assert store.get("600519", "rsi_14").value == 45.2
        assert store.get("300750", "rsi_14").value == 52.1

    def test_overwrite(self, store, rsi_def):
        store.put("600519", rsi_def, value=45.2)
        store.put("600519", rsi_def, value=50.0)
        result = store.get("600519", "rsi_14")
        assert result.value == 50.0

    def test_stats(self, store, rsi_def, macd_def, vol_def):
        store.put("600519", rsi_def, value=45.2)
        store.put("600519", macd_def, value=0.05)
        store.put("300750", vol_def, value=2.3)
        stats = store.stats()
        assert stats["total_entries"] == 3
        assert stats["symbols"] == 2
        assert stats["categories"]["momentum"] == 2
        assert stats["categories"]["volatility"] == 1

    def test_stats_excludes_expired(self, store, rsi_def):
        store.put("600519", rsi_def, value=45.2, ttl=0)
        time.sleep(0.01)
        stats = store.stats()
        assert stats["total_entries"] == 0
        assert stats["total_expired"] == 1

    def test_version_isolation(self, store):
        """Features with different versions are isolated."""
        defn_v1 = FeatureDefinition(name="rsi_14", category="momentum", version="v1")
        defn_v2 = FeatureDefinition(name="rsi_14", category="momentum", version="v2")
        store.put("600519", defn_v1, value=45.2)
        store.put("600519", defn_v2, value=50.0)
        assert store.get("600519", "rsi_14", version="v1").value == 45.2
        assert store.get("600519", "rsi_14", version="v2").value == 50.0

    def test_dict_value(self, store, rsi_def):
        """Features can store dict values."""
        store.put("600519", rsi_def, value={"rsi": 45.2, "signal": "neutral"})
        result = store.get("600519", "rsi_14")
        assert result.value["rsi"] == 45.2
