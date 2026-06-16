"""Unit tests for QlibAdapter — graceful degradation and subprocess bridge."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestQlibAdapterWithoutQlib:
    """Test QlibAdapter when both Qlib and .venv-qlib are unavailable."""

    @patch("src.prediction.qlib_adapter._HAS_QLIB_VENV", False)
    @patch("src.prediction.qlib_adapter._HAS_QLIB", False)
    def test_is_available_returns_false(self):
        from src.prediction.qlib_adapter import QlibAdapter

        adapter = QlibAdapter()
        adapter._initialized = False
        adapter._mode = "none"
        assert adapter.is_available() is False

    @patch("src.prediction.qlib_adapter._HAS_QLIB_VENV", False)
    @patch("src.prediction.qlib_adapter._HAS_QLIB", False)
    def test_predict_returns_empty(self):
        from src.prediction.qlib_adapter import QlibAdapter

        adapter = QlibAdapter()
        adapter._initialized = False
        adapter._mode = "none"
        result = adapter.predict(["600519", "000001"])
        assert result == {}

    @patch("src.prediction.qlib_adapter._HAS_QLIB_VENV", False)
    @patch("src.prediction.qlib_adapter._HAS_QLIB", False)
    def test_get_ic_value_returns_none(self):
        from src.prediction.qlib_adapter import QlibAdapter

        adapter = QlibAdapter()
        adapter._initialized = False
        adapter._mode = "none"
        assert adapter.get_ic_value("600519") is None

    @patch("src.prediction.qlib_adapter._HAS_QLIB_VENV", False)
    @patch("src.prediction.qlib_adapter._HAS_QLIB", False)
    def test_get_alpha_factors_returns_none(self):
        from src.prediction.qlib_adapter import QlibAdapter

        adapter = QlibAdapter()
        adapter._initialized = False
        adapter._mode = "none"
        assert adapter.get_alpha_factors("600519") is None

    @patch("src.prediction.qlib_adapter._HAS_QLIB_VENV", False)
    @patch("src.prediction.qlib_adapter._HAS_QLIB", False)
    def test_health_info_shows_not_installed(self):
        from src.prediction.qlib_adapter import QlibAdapter

        adapter = QlibAdapter()
        info = adapter.get_health_info()
        assert info["installed"] is False
        assert info["initialized"] is False


class TestQlibAdapterSubprocessBridge:
    """Test QlibAdapter subprocess bridge mode."""

    def test_subprocess_bridge_detected(self):
        """Verify .venv-qlib is detected when present."""
        from src.prediction.qlib_adapter import _HAS_QLIB_VENV, _QLIB_VENV_PYTHON

        if _QLIB_VENV_PYTHON.exists():
            assert _HAS_QLIB_VENV is True
        else:
            assert _HAS_QLIB_VENV is False

    @patch("src.prediction.qlib_adapter._HAS_QLIB_VENV", True)
    @patch("src.prediction.qlib_adapter._HAS_QLIB", False)
    def test_subprocess_health_check(self):
        """Test health check via subprocess bridge (mocked)."""
        from src.prediction.qlib_adapter import QlibAdapter

        adapter = QlibAdapter()
        with patch.object(
            adapter,
            "_call_worker",
            return_value={"installed": True, "version": "0.9.7"},
        ):
            assert adapter.initialize() is True
            assert adapter._mode == "subprocess"

    @patch("src.prediction.qlib_adapter._HAS_QLIB_VENV", True)
    @patch("src.prediction.qlib_adapter._HAS_QLIB", False)
    def test_subprocess_predict(self):
        """Test prediction via subprocess bridge (mocked)."""
        from src.prediction.qlib_adapter import QlibAdapter

        adapter = QlibAdapter()
        adapter._initialized = True
        adapter._mode = "subprocess"

        mock_result = {
            "600519": {
                "score": 0.42,
                "ic": -0.15,
                "features": ["Alpha158"],
                "alpha_factors": {"momentum_5d": -0.01},
                "horizon": 5,
            }
        }
        with patch.object(adapter, "_call_worker", return_value=mock_result):
            result = adapter.predict(["600519"])
            assert "600519" in result
            assert result["600519"]["score"] == 0.42


class TestQlibAdapterWithMockedQlib:
    """Test QlibAdapter with Qlib mocked as available (in-process mode)."""

    def test_to_qlib_code_sh(self):
        from src.prediction.qlib_adapter import QlibAdapter

        assert QlibAdapter._to_qlib_code("600519") == "SH600519"
        assert QlibAdapter._to_qlib_code("900123") == "SH900123"

    def test_to_qlib_code_sz(self):
        from src.prediction.qlib_adapter import QlibAdapter

        assert QlibAdapter._to_qlib_code("000001") == "SZ000001"
        assert QlibAdapter._to_qlib_code("300750") == "SZ300750"

    @patch("src.prediction.qlib_adapter._HAS_QLIB", True)
    @patch("src.prediction.qlib_adapter._HAS_QLIB_VENV", False)
    def test_predict_with_mocked_qlib(self):
        from src.prediction.qlib_adapter import QlibAdapter

        adapter = QlibAdapter()
        adapter._initialized = True
        adapter._mode = "inprocess"

        # Mock _compute_score and _get_features
        adapter._compute_score = MagicMock(return_value=0.65)
        adapter._get_features = MagicMock(return_value=["Alpha158"])

        # Mock _ic_inprocess
        adapter._ic_inprocess = MagicMock(return_value=0.05)

        result = adapter.predict(["600519"])

        assert "600519" in result
        assert result["600519"]["score"] == 0.65
        assert result["600519"]["ic"] == 0.05

    @patch("src.prediction.qlib_adapter._HAS_QLIB", True)
    @patch("src.prediction.qlib_adapter._HAS_QLIB_VENV", False)
    def test_predict_handles_exception(self):
        from src.prediction.qlib_adapter import QlibAdapter

        adapter = QlibAdapter()
        adapter._initialized = True
        adapter._mode = "inprocess"

        # Mock _compute_score to raise
        adapter._compute_score = MagicMock(side_effect=RuntimeError("test error"))
        adapter._get_features = MagicMock(return_value=[])

        result = adapter.predict(["600519"])

        assert "600519" in result
        assert result["600519"]["score"] is None
        assert "error" in result["600519"]

    def test_config_loads_from_research_yaml(self):
        from src.prediction.qlib_adapter import QlibAdapter

        adapter = QlibAdapter()
        # Config should have loaded actuary section
        assert isinstance(adapter._config, dict)
