"""Unit tests for DataAggregator — file I/O and fusion logic mocked."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


class TestDataAggregator:
    """Test DataAggregator with mocked external dependencies."""

    def _make_aggregator(self):
        from scripts.data_aggregator import DataAggregator

        return DataAggregator()

    def test_confidence_to_signal_strong_buy(self):
        agg = self._make_aggregator()
        assert "看多" in agg._confidence_to_signal(0.80)

    def test_confidence_to_signal_neutral(self):
        agg = self._make_aggregator()
        assert "中性" in agg._confidence_to_signal(0.50)

    def test_confidence_to_signal_sell(self):
        agg = self._make_aggregator()
        result = agg._confidence_to_signal(0.30)
        assert "看空" in result

    def test_check_constraints_main_board(self):
        agg = self._make_aggregator()
        constraints = agg._check_constraints("600519")
        assert constraints["board"] == "Main"
        assert constraints["limit_pct"] == 0.10

    def test_check_constraints_chinext(self):
        agg = self._make_aggregator()
        constraints = agg._check_constraints("300750")
        assert constraints["board"] == "ChiNext/STAR"
        assert constraints["limit_pct"] == 0.20

    def test_check_constraints_star(self):
        agg = self._make_aggregator()
        constraints = agg._check_constraints("688001")
        assert constraints["board"] == "ChiNext/STAR"

    def test_extract_sentinel_score_present(self):
        agg = self._make_aggregator()
        sentinel_data = {
            "sentiment": {"600519": {"score": 0.72, "label": "偏多"}},
        }
        score = agg._extract_sentinel_score("600519", sentinel_data)
        assert score == 0.72

    def test_extract_sentinel_score_missing(self):
        agg = self._make_aggregator()
        score = agg._extract_sentinel_score("600519", {})
        assert score is None

    def test_extract_sentinel_score_numeric(self):
        agg = self._make_aggregator()
        sentinel_data = {"sentiment": {"600519": 0.65}}
        score = agg._extract_sentinel_score("600519", sentinel_data)
        assert score == 0.65

    def test_compute_fusion_all_sources(self):
        agg = self._make_aggregator()
        sources = {
            "sentinel": {"score": 0.70},
            "actuary": {"score": 0.60},
            "technical": {"p_up": 0.55},
        }
        weights = {"sentinel": 0.25, "actuary": 0.35, "technical": 0.40}
        fusion = agg._compute_fusion(sources, weights)

        assert "confidence" in fusion
        assert "signal" in fusion
        assert 0 < fusion["confidence"] < 1

    def test_compute_fusion_technical_only(self):
        agg = self._make_aggregator()
        sources = {
            "sentinel": {"score": None},
            "actuary": {"score": None},
            "technical": {"p_up": 0.55},
        }
        weights = {"technical": 0.40}
        fusion = agg._compute_fusion(sources, weights)

        # With only technical, weight should be re-normalized to 1.0
        assert fusion["weights_used"]["technical"] == 1.0

    def test_compute_fusion_empty_weights(self):
        agg = self._make_aggregator()
        fusion = agg._compute_fusion({}, {})
        assert fusion["confidence"] == 0.5
        assert fusion["signal"] == "中性"

    def test_load_sentinel_data_missing_file(self):
        agg = self._make_aggregator()
        with patch(
            "scripts.data_aggregator.get_project_root",
            return_value=MagicMock(
                __truediv__=MagicMock(
                    return_value=MagicMock(exists=MagicMock(return_value=False))
                )
            ),
        ):
            data = agg._load_sentinel_data()
        assert data == {}

    def test_write_output(self, tmp_path):
        agg = self._make_aggregator()
        results = [
            {
                "symbol": "600519",
                "date": "2026-03-01",
                "fusion": {"confidence": 0.65, "signal": "看多"},
            }
        ]
        with patch(
            "scripts.data_aggregator.get_project_root",
            return_value=tmp_path,
        ):
            agg._config.setdefault("orchestration", {})["report_dir"] = str(
                tmp_path / "reports"
            )
            path = agg._write_output(results, "2026-03-01")

        assert path.exists()
        data = json.loads(path.read_text())
        assert len(data) == 1
        assert data[0]["symbol"] == "600519"

    @patch("scripts.data_aggregator.DataAggregator._get_technical_signal")
    @patch("scripts.data_aggregator.DataAggregator._get_qlib_predictions")
    @patch("scripts.data_aggregator.DataAggregator._load_sentinel_data")
    def test_aggregate_full_pipeline(
        self, mock_sentinel, mock_qlib, mock_tech, tmp_path
    ):
        mock_sentinel.return_value = {
            "fallback_used": False,
            "sentiment": {"600519": {"score": 0.70}},
        }
        mock_qlib.return_value = {
            "600519": {"score": 0.65, "ic": 0.05},
        }
        mock_tech.return_value = {
            "p_up": 0.55,
            "composite_signal": "bullish",
            "available": True,
        }

        agg = self._make_aggregator()

        with patch.object(agg, "_write_output", return_value=tmp_path / "out.json"):
            results = agg.aggregate(["600519"], "2026-03-01")

        assert len(results) == 1
        assert results[0]["symbol"] == "600519"
        assert "fusion" in results[0]
        assert results[0]["fusion"]["confidence"] > 0
