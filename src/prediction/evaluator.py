"""Prediction evaluation for the A-share prediction layer.

Compares prediction results against actual market data to measure
accuracy across multiple dimensions: direction, price range, signal
quality, and confidence calibration.

Per PRD FR-P003: Prediction evaluation with Chinese-language reports.
"""

import json
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.utils.config import get_data_dir, load_config
from src.utils.logger import get_logger

logger = get_logger("prediction.evaluator")


class EvaluationError(Exception):
    """Raised when prediction evaluation encounters invalid data."""


class PredictionEvaluator:
    """Evaluates prediction accuracy against actual market data.

    Compares predicted trend direction, price targets, and trading
    signals against realized market outcomes. Generates Chinese-language
    performance reports.

    Attributes:
        config: Parsed prediction.yaml configuration dictionary.
    """

    def __init__(self, config_path: str = "prediction") -> None:
        """Initialize the evaluator by loading configuration.

        Args:
            config_path: Config file name without extension, resolved
                by ``load_config`` to ``config/<name>.yaml``.
        """
        self.config: dict[str, Any] = load_config(config_path)
        self._eval_cfg: dict[str, Any] = self.config.get("evaluation", {})
        self._direction_threshold: float = self._eval_cfg.get(
            "direction_accuracy_threshold", 0.6
        )
        self._price_tolerance: float = self._eval_cfg.get("price_range_tolerance", 0.05)
        self._min_confidence: float = self._eval_cfg.get("min_confidence", 0.5)
        logger.info(
            "PredictionEvaluator initialized: "
            "direction_threshold=%.2f, price_tolerance=%.2f",
            self._direction_threshold,
            self._price_tolerance,
        )

    def evaluate(
        self,
        prediction: dict[str, Any],
        actual_data: pd.DataFrame,
    ) -> dict[str, Any]:
        """Evaluate a single prediction against actual market data.

        Args:
            prediction: Dict with trend, signal, confidence, target_price_range.
            actual_data: DataFrame with ``close`` column, >= 2 rows.

        Returns:
            Evaluation dict with direction_accuracy, price_range_hit,
            signal_accuracy, confidence_calibration, actual_return, etc.

        Raises:
            EvaluationError: If prediction or actual_data is invalid.
        """
        self._validate_prediction(prediction)
        self._validate_actual_data(actual_data)

        start_close = float(actual_data["close"].iloc[0])
        end_close = float(actual_data["close"].iloc[-1])
        actual_return = (end_close - start_close) / start_close

        # Determine actual trend direction
        actual_trend = _classify_trend(actual_return)
        predicted_trend = prediction["trend"]

        # 1. Direction accuracy
        direction_accuracy = _check_direction_accuracy(predicted_trend, actual_trend)

        # 2. Price range hit
        target_range = prediction.get("target_price_range", {})
        price_range_hit = _check_price_range_hit(
            end_close, target_range, self._price_tolerance
        )

        # 3. Signal accuracy
        signal_accuracy = _check_signal_accuracy(
            prediction.get("signal", "hold"), actual_return
        )

        # 4. Confidence calibration
        confidence = float(prediction.get("confidence", 0.5))
        accuracy_score = _compute_accuracy_score(
            direction_accuracy, price_range_hit, signal_accuracy
        )
        confidence_calibration = 1.0 - abs(confidence - accuracy_score)

        result = {
            "direction_accuracy": direction_accuracy,
            "price_range_hit": price_range_hit,
            "signal_accuracy": signal_accuracy,
            "confidence_calibration": confidence_calibration,
            "actual_return": round(actual_return, 6),
            "predicted_trend": predicted_trend,
            "actual_trend": actual_trend,
            "predicted_signal": prediction.get("signal", "hold"),
            "confidence": confidence,
            "symbol": prediction.get("symbol", "unknown"),
            "evaluation_timestamp": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            "Evaluation for %s: direction=%s, price_hit=%s, signal=%s, "
            "calibration=%.2f",
            result["symbol"],
            direction_accuracy,
            price_range_hit,
            signal_accuracy,
            confidence_calibration,
        )
        return result

    def save_prediction(
        self,
        symbol: str,
        prediction: dict[str, Any],
        timestamp: datetime | None = None,
    ) -> Path:
        """Persist a prediction to the file system as JSON.

        Saves to ``data/processed/predictions/{symbol}/{YYYY}/{MM}/
        {symbol}_{YYYYMMDD}.json``. Creates directories as needed.

        Args:
            symbol: 6-digit stock code (e.g. ``"000001"``).
            prediction: Prediction dictionary to persist.
            timestamp: Prediction timestamp. Defaults to UTC now.

        Returns:
            Path to the saved JSON file.
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        year_str = timestamp.strftime("%Y")
        month_str = timestamp.strftime("%m")
        date_str = timestamp.strftime("%Y%m%d")

        pred_dir = (
            get_data_dir("processed") / "predictions" / symbol / year_str / month_str
        )
        pred_dir.mkdir(parents=True, exist_ok=True)

        file_path = pred_dir / f"{symbol}_{date_str}.json"

        # Store prediction with timestamp metadata
        save_data = {
            **prediction,
            "save_timestamp": timestamp.isoformat(),
        }

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)

        logger.info("Saved prediction for %s to %s", symbol, file_path)
        return file_path

    def load_predictions(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """Load historical predictions from the file system.

        Reads JSON files from the prediction directory structure and
        filters by date range (inclusive on both ends).

        Args:
            symbol: 6-digit stock code (e.g. ``"000001"``).
            start_date: Start of the date range (inclusive).
            end_date: End of the date range (inclusive).

        Returns:
            List of prediction dicts sorted by date ascending.
            Returns empty list if no predictions are found.
        """
        base_dir = get_data_dir("processed") / "predictions" / symbol
        if not base_dir.exists():
            logger.info("No prediction directory found for %s", symbol)
            return []

        predictions: list[dict[str, Any]] = []
        prefix = f"{symbol}_"

        # Iterate over year/month directories
        for json_file in sorted(base_dir.rglob("*.json")):
            filename = json_file.name
            if not filename.startswith(prefix):
                continue

            # Extract date from filename: {symbol}_{YYYYMMDD}.json
            date_part = filename.replace(prefix, "").replace(".json", "")
            try:
                file_date = datetime.strptime(date_part, "%Y%m%d").date()
            except ValueError:
                logger.warning("Skipping file with unparseable date: %s", json_file)
                continue

            if start_date <= file_date <= end_date:
                try:
                    with open(json_file, "r", encoding="utf-8") as f:
                        pred = json.load(f)
                    pred["_file_date"] = file_date.isoformat()
                    predictions.append(pred)
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(
                        "Failed to load prediction %s: %s",
                        json_file,
                        exc,
                    )

        logger.info(
            "Loaded %d predictions for %s (%s to %s)",
            len(predictions),
            symbol,
            start_date,
            end_date,
        )
        return predictions

    def generate_report(self, evaluations: list[dict[str, Any]]) -> str:
        """Generate a Chinese-language performance summary report.

        Includes overall accuracy, per-symbol breakdown, rating, and
        disclaimer. Returns a complete markdown-formatted Chinese report.

        Args:
            evaluations: List of evaluation result dicts from ``evaluate()``.

        Returns:
            Chinese-language report string.
        """
        if not evaluations:
            return "暂无评估数据，无法生成报告。"

        total = len(evaluations)
        direction_correct = sum(1 for e in evaluations if e.get("direction_accuracy"))
        price_hit = sum(1 for e in evaluations if e.get("price_range_hit"))
        signal_correct = sum(1 for e in evaluations if e.get("signal_accuracy"))
        avg_calibration = (
            sum(e.get("confidence_calibration", 0.0) for e in evaluations) / total
        )
        avg_confidence = sum(e.get("confidence", 0.0) for e in evaluations) / total
        avg_return = sum(e.get("actual_return", 0.0) for e in evaluations) / total

        direction_rate = direction_correct / total
        price_rate = price_hit / total
        signal_rate = signal_correct / total

        # Determine overall rating
        overall_score = (direction_rate + price_rate + signal_rate) / 3
        if overall_score >= 0.7:
            rating = "优秀"
        elif overall_score >= 0.5:
            rating = "良好"
        elif overall_score >= 0.3:
            rating = "一般"
        else:
            rating = "较差"

        report_lines = [
            "=" * 50,
            "        A股预测模型评估报告",
            "=" * 50,
            "",
            f"评估样本数: {total}",
            "",
            "--- 准确率指标 ---",
            f"方向准确率: {direction_correct}/{total} ({direction_rate:.1%})",
            f"价格区间命中率: {price_hit}/{total} ({price_rate:.1%})",
            f"信号准确率: {signal_correct}/{total} ({signal_rate:.1%})",
            "",
            "--- 校准指标 ---",
            f"平均置信度: {avg_confidence:.2f}",
            f"置信度校准: {avg_calibration:.2f}",
            "",
            "--- 收益统计 ---",
            f"平均实际收益率: {avg_return:.2%}",
            "",
            "--- 综合评价 ---",
            f"综合评分: {overall_score:.1%}",
            f"评级: {rating}",
            "",
        ]

        # Per-symbol breakdown
        symbol_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for e in evaluations:
            sym = e.get("symbol", "unknown")
            symbol_groups[sym].append(e)

        if len(symbol_groups) > 1 or (
            len(symbol_groups) == 1 and list(symbol_groups.keys())[0] != "unknown"
        ):
            report_lines.append("--- 个股明细 ---")
            for sym, sym_evals in sorted(symbol_groups.items()):
                sym_total = len(sym_evals)
                sym_dir = sum(1 for e in sym_evals if e.get("direction_accuracy"))
                sym_price = sum(1 for e in sym_evals if e.get("price_range_hit"))
                sym_signal = sum(1 for e in sym_evals if e.get("signal_accuracy"))
                report_lines.append(
                    f"  {sym}: 方向 {sym_dir}/{sym_total} | "
                    f"价格 {sym_price}/{sym_total} | "
                    f"信号 {sym_signal}/{sym_total}"
                )
            report_lines.append("")

        # Performance threshold check
        if direction_rate >= self._direction_threshold:
            report_lines.append(
                f"[通过] 方向准确率 ({direction_rate:.1%}) "
                f">= 阈值 ({self._direction_threshold:.1%})"
            )
        else:
            report_lines.append(
                f"[未通过] 方向准确率 ({direction_rate:.1%}) "
                f"< 阈值 ({self._direction_threshold:.1%})"
            )

        # Disclaimer (免责声明)
        report_lines.extend(
            [
                "",
                "--- 免责声明 ---",
                "本报告由AI模型自动生成，仅供研究学习参考，不构成任何投资建议。",
                "股市有风险，投资需谨慎。",
                "",
                "=" * 50,
            ]
        )

        report = "\n".join(report_lines)
        logger.info(
            "Generated evaluation report: %d evaluations, rating=%s",
            total,
            rating,
        )
        return report

    @staticmethod
    def _validate_prediction(prediction: dict[str, Any]) -> None:
        """Validate prediction dict has trend, signal, confidence fields."""
        required = {"trend", "signal", "confidence"}
        missing = required - set(prediction.keys())
        if missing:
            raise EvaluationError(f"Prediction missing required fields: {missing}")

    @staticmethod
    def _validate_actual_data(actual_data: pd.DataFrame) -> None:
        """Validate actual data has close column and >= 2 rows."""
        if actual_data.empty:
            raise EvaluationError("Actual data DataFrame is empty")
        if "close" not in actual_data.columns:
            raise EvaluationError(
                "Actual data must have a 'close' column. "
                f"Got columns: {list(actual_data.columns)}"
            )
        if len(actual_data) < 2:
            raise EvaluationError(
                "Actual data must have at least 2 rows for evaluation. "
                f"Got {len(actual_data)} rows."
            )


def _classify_trend(actual_return: float) -> str:
    """Classify return into bullish (>0.5%), bearish (<-0.5%), or neutral."""
    if actual_return > 0.005:
        return "bullish"
    elif actual_return < -0.005:
        return "bearish"
    else:
        return "neutral"


def _check_direction_accuracy(predicted_trend: str, actual_trend: str) -> bool:
    """Return True if predicted trend matches actual trend exactly."""
    return predicted_trend == actual_trend


def _check_price_range_hit(
    actual_close: float,
    target_range: dict[str, float],
    tolerance: float,
) -> bool:
    """Return True if actual_close is within target range +/- tolerance buffer."""
    if not target_range:
        return False

    low = float(target_range.get("low", 0))
    high = float(target_range.get("high", 0))

    if low <= 0 or high <= 0 or high < low:
        return False

    # Apply tolerance buffer
    range_width = high - low
    buffer = range_width * tolerance
    adjusted_low = low - buffer
    adjusted_high = high + buffer

    return adjusted_low <= actual_close <= adjusted_high


def _check_signal_accuracy(signal: str, actual_return: float) -> bool:
    """Check if signal was appropriate: buy>0, sell<0, hold<2%, watch=True."""
    signal = signal.lower()
    if signal == "buy":
        return actual_return > 0
    elif signal == "sell":
        return actual_return < 0
    elif signal == "hold":
        return abs(actual_return) < 0.02
    elif signal == "watch":
        return True
    else:
        return False


def _compute_accuracy_score(
    direction_accuracy: bool,
    price_range_hit: bool,
    signal_accuracy: bool,
) -> float:
    """Weighted accuracy: direction 40%, price_range 30%, signal 30%."""
    score = (
        (0.4 * float(direction_accuracy))
        + (0.3 * float(price_range_hit))
        + (0.3 * float(signal_accuracy))
    )
    return score
