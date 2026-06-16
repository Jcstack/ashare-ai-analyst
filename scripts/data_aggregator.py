#!/usr/bin/env python3
"""Data aggregator — Bayesian fusion of Sentinel + Actuary + Technical signals.

Reads:
- ``data/raw/gemini_sense.json`` (sentinel output)
- Qlib prediction scores (via QlibAdapter)
- Bayesian indicator probabilities (via BayesianIndicatorAnalyzer)

Outputs:
- ``scripts/output/reports/research_signal_{date}.json``

Degradation:
- Gemini data empty/stale → auto-degrade to local technical rules
- Qlib unavailable → skip actuary, re-weight remaining sources
- Technical always available (pure computation)

Usage:
    python scripts/data_aggregator.py [--symbols 600519,000001] [--date 2026-03-01]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure project root on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.utils.config import get_project_root, load_config  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger("scripts.data_aggregator")


class DataAggregator:
    """Fuses multi-source signals using configurable Bayesian weights."""

    def __init__(self) -> None:
        self._config = load_config("research")
        self._fusion_cfg = self._config.get("bayesian_fusion", {})
        self._constraint_cfg = self._config.get("ashare_constraints", {})
        self._weights = self._fusion_cfg.get(
            "weights",
            {
                "sentinel": 0.25,
                "actuary": 0.35,
                "technical": 0.40,
            },
        )
        self._thresholds = self._fusion_cfg.get("thresholds", {})
        self._labels = self._fusion_cfg.get("labels", {})

    def aggregate(
        self, symbols: list[str], date_str: str | None = None
    ) -> list[dict[str, Any]]:
        """Run aggregation for a list of symbols.

        Args:
            symbols: List of 6-digit stock codes.
            date_str: Date string (YYYY-MM-DD). Defaults to today.

        Returns:
            List of signal dicts, one per symbol.
        """
        date_str = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        logger.info("Aggregating signals for %d symbols on %s", len(symbols), date_str)

        # Load data sources
        sentinel_data = self._load_sentinel_data()
        qlib_adapter = self._get_qlib_adapter()
        qlib_predictions = self._get_qlib_predictions(qlib_adapter, symbols)

        results: list[dict[str, Any]] = []
        for symbol in symbols:
            signal = self._aggregate_symbol(
                symbol, date_str, sentinel_data, qlib_predictions
            )
            results.append(signal)

        # Write output
        output_path = self._write_output(results, date_str)
        logger.info("Aggregation complete: %d signals → %s", len(results), output_path)
        return results

    def _aggregate_symbol(
        self,
        symbol: str,
        date_str: str,
        sentinel_data: dict[str, Any],
        qlib_predictions: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Aggregate signals for a single symbol."""
        sources: dict[str, dict[str, Any]] = {}
        available_weights: dict[str, float] = {}

        # Source 1: Sentinel (Gemini sentiment)
        sentinel_score = self._extract_sentinel_score(symbol, sentinel_data)
        if sentinel_score is not None:
            # Apply emotion damping for A-share
            damping = self._constraint_cfg.get("sentiment_damping", 0.8)
            damped = 0.5 + (sentinel_score - 0.5) * damping
            sources["sentinel"] = {
                "score": round(damped, 4),
                "raw_score": sentinel_score,
                "fallback_used": sentinel_data.get("fallback_used", True),
            }
            if not sentinel_data.get("fallback_used", True):
                available_weights["sentinel"] = self._weights.get("sentinel", 0.25)

        # Source 2: Actuary (Qlib)
        qlib_result = qlib_predictions.get(symbol, {})
        qlib_score = qlib_result.get("score")
        if qlib_score is not None:
            sources["actuary"] = {
                "score": round(qlib_score, 4),
                "ic": qlib_result.get("ic"),
                "available": True,
            }
            available_weights["actuary"] = self._weights.get("actuary", 0.35)
        else:
            sources["actuary"] = {"score": None, "ic": None, "available": False}

        # Source 3: Technical (Bayesian indicators) — always available
        tech_result = self._get_technical_signal(symbol)
        sources["technical"] = tech_result
        available_weights["technical"] = self._weights.get("technical", 0.40)

        # Bayesian fusion
        fusion = self._compute_fusion(sources, available_weights)

        # A-share constraints
        constraints = self._check_constraints(symbol)

        return {
            "symbol": symbol,
            "date": date_str,
            "sources": sources,
            "fusion": fusion,
            "constraints": constraints,
        }

    def _extract_sentinel_score(
        self, symbol: str, sentinel_data: dict[str, Any]
    ) -> float | None:
        """Extract sentiment score for a symbol from sentinel data."""
        if not sentinel_data:
            return None
        sentiment = sentinel_data.get("sentiment", {})
        if symbol in sentiment:
            sym_data = sentiment[symbol]
            if isinstance(sym_data, dict):
                return sym_data.get("score")
            if isinstance(sym_data, (int, float)):
                return float(sym_data)
        return None

    def _get_technical_signal(self, symbol: str) -> dict[str, Any]:
        """Get Bayesian indicator signal for a symbol."""
        try:
            from src.analysis.bayesian_indicators import BayesianIndicatorAnalyzer
            from src.data.fetcher import StockDataFetcher

            # Fetch recent data via StockDataFetcher
            fetcher = StockDataFetcher()
            df = fetcher.fetch_daily_ohlcv(symbol)
            if df is None or df.empty:
                return {"p_up": 0.5, "composite_signal": "neutral", "available": False}

            # Add technical indicators
            from src.analysis.indicators import TechnicalIndicators

            ti = TechnicalIndicators()
            df = ti.add_all(df)

            # Run Bayesian analysis
            analyzer = BayesianIndicatorAnalyzer()
            result = analyzer.analyze(df)
            composite = result.get("composite", {})

            p_up = composite.get("bullish_count", 0) / max(
                composite.get("total_indicators", 1), 1
            )
            signal = composite.get("overall_signal", "neutral")

            return {
                "p_up": round(p_up, 4),
                "composite_signal": signal,
                "available": True,
                "indicator_count": composite.get("total_indicators", 0),
            }
        except Exception as exc:
            logger.warning("Technical signal failed for %s: %s", symbol, exc)
            return {"p_up": 0.5, "composite_signal": "neutral", "available": False}

    def _compute_fusion(
        self,
        sources: dict[str, dict[str, Any]],
        available_weights: dict[str, float],
    ) -> dict[str, Any]:
        """Compute Bayesian fusion confidence score."""
        if not available_weights:
            return {
                "confidence": 0.5,
                "signal": self._labels.get("neutral", "中性"),
                "weights_used": {},
            }

        # Re-normalize weights
        total = sum(available_weights.values())
        normalized = (
            {k: v / total for k, v in available_weights.items()} if total > 0 else {}
        )

        # Weighted average of scores
        weighted_sum = 0.0
        for source_name, weight in normalized.items():
            src = sources.get(source_name, {})
            score = src.get("score") if source_name != "technical" else src.get("p_up")
            if score is not None:
                weighted_sum += weight * score

        confidence = round(weighted_sum, 4)

        # Map to signal label
        signal = self._confidence_to_signal(confidence)

        return {
            "confidence": confidence,
            "signal": signal,
            "weights_used": {k: round(v, 4) for k, v in normalized.items()},
        }

    def _confidence_to_signal(self, confidence: float) -> str:
        """Map confidence score to signal label."""
        thresholds = self._thresholds
        if confidence >= thresholds.get("strong_buy", 0.75):
            return self._labels.get("strong_buy", "强烈看多")
        if confidence >= thresholds.get("buy", 0.60):
            return self._labels.get("buy", "看多")
        if confidence >= thresholds.get("neutral_high", 0.55):
            return self._labels.get("neutral", "中性")
        if confidence >= thresholds.get("neutral_low", 0.45):
            return self._labels.get("neutral", "中性")
        if confidence >= thresholds.get("sell", 0.40):
            return self._labels.get("sell", "看空")
        return self._labels.get("strong_sell", "强烈看空")

    def _check_constraints(self, symbol: str) -> dict[str, Any]:
        """Check A-share constraints for a symbol."""
        # Determine board type for limit threshold
        if symbol.startswith("3") or symbol.startswith("68"):
            limit = self._constraint_cfg.get("chinext_star_limit", 0.20)
            board = "ChiNext/STAR"
        else:
            limit = self._constraint_cfg.get("main_board_limit", 0.10)
            board = "Main"

        return {
            "board": board,
            "limit_pct": limit,
            "t_plus_1": self._constraint_cfg.get("t_plus_1", True),
            "sentiment_damping": self._constraint_cfg.get("sentiment_damping", 0.8),
        }

    def _load_sentinel_data(self) -> dict[str, Any]:
        """Load sentinel output from data/raw/gemini_sense.json."""
        sentinel_cfg = self._config.get("sentinel", {})
        output_path_str = sentinel_cfg.get("output_path", "workspace/sentinel/gemini_sense.json")
        if not output_path_str.startswith("/"):
            output_path = get_project_root() / output_path_str
        else:
            output_path = Path(output_path_str)

        if not output_path.exists():
            logger.info("Sentinel data not found at %s — skipping", output_path)
            return {}

        try:
            with open(output_path, encoding="utf-8") as f:
                data = json.load(f)
            logger.info(
                "Loaded sentinel data: %d symbols", len(data.get("symbols", []))
            )
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load sentinel data: %s", exc)
            return {}

    def _get_qlib_adapter(self) -> Any:
        """Get QlibAdapter instance."""
        try:
            from src.prediction.qlib_adapter import QlibAdapter

            return QlibAdapter()
        except Exception:
            return None

    def _get_qlib_predictions(
        self, adapter: Any, symbols: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Get Qlib predictions, returning empty dict on failure."""
        if adapter is None:
            return {}
        try:
            if not adapter.is_available():
                logger.info("Qlib not available — skipping actuary scores")
                return {}
            return adapter.predict(symbols)
        except Exception as exc:
            logger.warning("Qlib predictions failed: %s", exc)
            return {}

    def _write_output(self, results: list[dict[str, Any]], date_str: str) -> Path:
        """Write aggregation results to output file."""
        orch_cfg = self._config.get("orchestration", {})
        report_dir = orch_cfg.get("report_dir", "workspace/signals")
        if not report_dir.startswith("/"):
            report_dir_path = get_project_root() / report_dir
        else:
            report_dir_path = Path(report_dir)

        report_dir_path.mkdir(parents=True, exist_ok=True)
        output_path = report_dir_path / f"research_signal_{date_str}.json"

        def _default(obj: Any) -> Any:
            if hasattr(obj, "isoformat"):
                return obj.isoformat()
            if hasattr(obj, "item"):
                return obj.item()
            return str(obj)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=_default)

        return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Research data aggregator")
    parser.add_argument(
        "--symbols",
        type=str,
        default="",
        help="Comma-separated stock codes (e.g. 600519,000001)",
    )
    parser.add_argument(
        "--date",
        type=str,
        default="",
        help="Date string YYYY-MM-DD (default: today)",
    )
    args = parser.parse_args()

    # Load default symbols from config
    config = load_config("research")
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = config.get("orchestration", {}).get("default_symbols", [])

    if not symbols:
        print("No symbols specified. Use --symbols or configure default_symbols.")
        sys.exit(1)

    date_str = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    aggregator = DataAggregator()
    results = aggregator.aggregate(symbols, date_str)

    print(f"Aggregated {len(results)} signals for {date_str}")
    for r in results:
        fusion = r.get("fusion", {})
        print(
            f"  {r['symbol']}: confidence={fusion.get('confidence', 'N/A')}, "
            f"signal={fusion.get('signal', 'N/A')}"
        )


if __name__ == "__main__":
    main()
