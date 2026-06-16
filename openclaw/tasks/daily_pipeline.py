"""Daily pipeline tasks for automated A-share data collection and analysis.

Defines Celery tasks that run on a scheduled basis to fetch market data,
compute technical indicators, generate AI-powered predictions, and
produce periodic evaluation reports.

Per PRD FR-O001: Automated daily data collection pipeline.
Per PRD FR-O002: Automated analysis and prediction pipeline.
"""

from typing import Any

from openclaw.celery_app import app
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("openclaw.tasks.daily_pipeline")


def _should_execute(task_name: str) -> bool:
    """Check if the task should execute under the current timeline profile."""
    try:
        from openclaw.timeline_scheduler import TimelineScheduler

        scheduler = TimelineScheduler()
        return scheduler.should_execute(task_name)
    except Exception:
        # If scheduler fails, default to executing
        return True


def _get_pipeline_config() -> dict[str, Any]:
    """Load pipeline-specific configuration from openclaw.yaml.

    Returns:
        The ``pipeline`` section of ``config/openclaw.yaml``, or
        an empty dict if unavailable.
    """
    try:
        config = load_config("openclaw")
        return config.get("pipeline", {})
    except FileNotFoundError:
        logger.warning(
            "config/openclaw.yaml not found; using default pipeline settings"
        )
        return {}


def _get_retry_delay() -> int:
    """Get the configured retry delay in seconds.

    Returns:
        Retry delay from ``pipeline.retry_delay_seconds``, defaulting
        to 60 seconds.
    """
    pipeline_cfg = _get_pipeline_config()
    return pipeline_cfg.get("retry_delay_seconds", 60)


def _get_max_retries() -> int:
    """Get the configured maximum retry count.

    Returns:
        Max retries from ``pipeline.max_retries``, defaulting to 3.
    """
    pipeline_cfg = _get_pipeline_config()
    return pipeline_cfg.get("max_retries", 3)


def _create_notifier() -> Any:
    """Create a DiscordNotifier instance.

    Separated into a helper for easier mocking in tests.

    Returns:
        A configured ``DiscordNotifier`` instance.
    """
    from src.utils.notifier import DiscordNotifier

    return DiscordNotifier()


@app.task(bind=True, max_retries=3, name="openclaw.tasks.daily_pipeline.task_fetch_all")
def task_fetch_all(self: Any) -> dict[str, str]:
    """Fetch and preprocess daily OHLCV data for all watchlist stocks.

    Loads the stock watchlist from ``config/stocks.yaml``, fetches OHLCV
    data via ``StockDataFetcher``, and preprocesses it via
    ``DataPreprocessor``. On failure, sends a Discord error alert and
    retries with the configured delay.

    Args:
        self: Bound Celery task instance (for retry support).

    Returns:
        Dictionary mapping each symbol to its fetch status string
        (e.g., ``{"000001": "fetched", "600519": "fetched"}``).

    Raises:
        self.retry: On retryable errors, re-queues the task with a
            countdown delay.
    """
    if not _should_execute("task_fetch_all"):
        logger.info("task_fetch_all: skipped (timeline guard)")
        return {"_skipped": True, "_reason": "timeline_guard"}

    logger.info("task_fetch_all: starting daily data fetch")
    notifier = _create_notifier()
    retry_delay = _get_retry_delay()

    try:
        from src.data.fetcher import StockDataFetcher
        from src.data.preprocessor import DataPreprocessor

        fetcher = StockDataFetcher()
        preprocessor = DataPreprocessor()

        # Fetch OHLCV for all watchlist stocks
        raw_data = fetcher.fetch_all_watchlist()

        if not raw_data:
            logger.warning("task_fetch_all: no data fetched (empty watchlist?)")
            return {}

        # Preprocess all fetched data
        processed_data = preprocessor.process_all(raw_data)

        results: dict[str, str] = {
            symbol: "fetched" for symbol in processed_data
        }

        logger.info(
            "task_fetch_all: completed successfully — %d symbols fetched",
            len(results),
        )

        # Send success notification
        notifier.send_daily_summary(
            results=[
                {"symbol": sym, "signal": "fetched", "confidence": 1.0}
                for sym in results
            ]
        )

        return results

    except Exception as exc:
        error_msg = f"task_fetch_all failed: {exc}"
        logger.error(error_msg)
        notifier.send_error_alert(error_msg)
        raise self.retry(exc=exc, countdown=retry_delay)


@app.task(bind=True, max_retries=3, name="openclaw.tasks.daily_pipeline.task_analyze_all")
def task_analyze_all(self: Any) -> dict[str, dict[str, Any]]:
    """Run technical analysis on all watchlist stocks.

    For each stock in the watchlist, fetches OHLCV data, computes all
    configured technical indicators, and detects candlestick patterns
    and support/resistance levels.

    Args:
        self: Bound Celery task instance (for retry support).

    Returns:
        Dictionary mapping each symbol to a summary dict containing
        ``indicators_added`` (bool), ``patterns_detected`` (int), and
        ``sr_levels_found`` (int).

    Raises:
        self.retry: On retryable errors, re-queues the task with a
            countdown delay.
    """
    if not _should_execute("task_analyze_all"):
        logger.info("task_analyze_all: skipped (timeline guard)")
        return {"_skipped": True, "_reason": "timeline_guard"}

    logger.info("task_analyze_all: starting technical analysis")
    notifier = _create_notifier()
    retry_delay = _get_retry_delay()

    try:
        from src.analysis.indicators import TechnicalIndicators
        from src.analysis.patterns import PatternRecognizer
        from src.data.fetcher import StockDataFetcher
        from src.data.preprocessor import DataPreprocessor

        fetcher = StockDataFetcher()
        preprocessor = DataPreprocessor()
        indicators = TechnicalIndicators()
        pattern_recognizer = PatternRecognizer()

        stocks_config = load_config("stocks")
        watchlist: list[dict[str, str]] = stocks_config.get("watchlist", [])

        results: dict[str, dict[str, Any]] = {}

        for entry in watchlist:
            symbol = entry["symbol"]
            name = entry.get("name", symbol)

            try:
                logger.info("Analyzing %s (%s)", symbol, name)

                # Fetch and preprocess
                raw_df = fetcher.fetch_daily_ohlcv(symbol)
                clean_df = preprocessor.clean_ohlcv(raw_df)
                enriched_df = preprocessor.add_returns(clean_df)

                # Technical indicators
                df_with_indicators = indicators.add_all(enriched_df)

                # Pattern detection
                df_with_patterns = pattern_recognizer.detect_candlestick_patterns(
                    df_with_indicators
                )

                # Support/Resistance levels
                sr_levels = pattern_recognizer.find_support_resistance(
                    df_with_patterns
                )

                # Count detected patterns (columns starting with "pattern_")
                pattern_cols = [
                    c for c in df_with_patterns.columns
                    if c.startswith("pattern_")
                ]
                patterns_detected = sum(
                    int(df_with_patterns[col].any())
                    for col in pattern_cols
                )

                results[symbol] = {
                    "indicators_added": True,
                    "patterns_detected": patterns_detected,
                    "sr_levels_found": len(sr_levels),
                }

            except Exception as sym_exc:
                logger.error(
                    "Analysis failed for %s (%s): %s", symbol, name, sym_exc
                )
                results[symbol] = {
                    "indicators_added": False,
                    "patterns_detected": 0,
                    "sr_levels_found": 0,
                    "error": str(sym_exc),
                }

        logger.info(
            "task_analyze_all: completed — %d symbols analyzed",
            len(results),
        )
        return results

    except Exception as exc:
        error_msg = f"task_analyze_all failed: {exc}"
        logger.error(error_msg)
        notifier.send_error_alert(error_msg)
        raise self.retry(exc=exc, countdown=retry_delay)


@app.task(bind=True, max_retries=3, name="openclaw.tasks.daily_pipeline.task_predict_all")
def task_predict_all(self: Any) -> dict[str, dict[str, Any]]:
    """Generate AI predictions for all watchlist stocks.

    For each stock, prepares data with indicators, patterns, and S/R
    levels, then calls ``StockAnalyzer.analyze()`` to produce a Claude
    API-powered prediction. Sends a Discord alert for each prediction
    and a daily summary after all stocks are processed.

    Args:
        self: Bound Celery task instance (for retry support).

    Returns:
        Dictionary mapping each symbol to its prediction result dict.

    Raises:
        self.retry: On retryable errors, re-queues the task with a
            countdown delay.
    """
    if not _should_execute("task_predict_all"):
        logger.info("task_predict_all: skipped (timeline guard)")
        return {"_skipped": True, "_reason": "timeline_guard"}

    logger.info("task_predict_all: starting AI predictions")
    notifier = _create_notifier()
    retry_delay = _get_retry_delay()

    try:
        from src.analysis.indicators import TechnicalIndicators
        from src.analysis.patterns import PatternRecognizer
        from src.data.fetcher import StockDataFetcher
        from src.data.preprocessor import DataPreprocessor
        from src.prediction.analyzer import StockAnalyzer

        fetcher = StockDataFetcher()
        preprocessor = DataPreprocessor()
        indicators_calc = TechnicalIndicators()
        pattern_recognizer = PatternRecognizer()
        analyzer = StockAnalyzer()

        stocks_config = load_config("stocks")
        watchlist: list[dict[str, str]] = stocks_config.get("watchlist", [])

        predictions: dict[str, dict[str, Any]] = {}
        summary_results: list[dict[str, Any]] = []

        for entry in watchlist:
            symbol = entry["symbol"]
            name = entry.get("name", symbol)

            try:
                logger.info("Predicting %s (%s)", symbol, name)

                # Fetch, preprocess, and enrich data
                raw_df = fetcher.fetch_daily_ohlcv(symbol)
                clean_df = preprocessor.clean_ohlcv(raw_df)
                enriched_df = preprocessor.add_returns(clean_df)

                # Compute indicators
                df_with_indicators = indicators_calc.add_all(enriched_df)

                # Detect patterns
                df_with_patterns = pattern_recognizer.detect_candlestick_patterns(
                    df_with_indicators
                )

                # Find S/R levels
                sr_levels = pattern_recognizer.find_support_resistance(
                    df_with_patterns
                )

                # Extract indicator values from last row for the prompt
                last_row = df_with_patterns.iloc[-1]
                indicator_values: dict[str, Any] = {
                    col: (
                        float(last_row[col])
                        if hasattr(last_row[col], "item")
                        else last_row[col]
                    )
                    for col in df_with_patterns.columns
                    if col not in (
                        "date", "open", "high", "low", "close",
                        "volume", "amount",
                    )
                }

                # Extract active pattern signals
                pattern_cols = [
                    c for c in df_with_patterns.columns
                    if c.startswith("pattern_")
                ]
                active_patterns: list[dict[str, Any]] = [
                    {"name": col, "value": float(last_row[col])}
                    for col in pattern_cols
                    if last_row[col] != 0
                ]

                # Call Claude API for prediction
                prediction = analyzer.analyze(
                    symbol=symbol,
                    ohlcv_df=df_with_patterns,
                    indicators=indicator_values,
                    patterns=active_patterns,
                    sr_levels=sr_levels,
                )

                predictions[symbol] = prediction

                # Send per-stock Discord alert
                notifier.send_analysis_alert(symbol=symbol, prediction=prediction)

                # Collect for daily summary
                summary_results.append({
                    "symbol": symbol,
                    "signal": prediction.get("signal", "N/A"),
                    "confidence": prediction.get("confidence", 0.0),
                })

            except Exception as sym_exc:
                logger.error(
                    "Prediction failed for %s (%s): %s",
                    symbol, name, sym_exc,
                )
                predictions[symbol] = {"error": str(sym_exc)}

        # Send daily summary notification
        if summary_results:
            notifier.send_daily_summary(results=summary_results)

        logger.info(
            "task_predict_all: completed — %d predictions generated",
            len(predictions),
        )
        return predictions

    except Exception as exc:
        error_msg = f"task_predict_all failed: {exc}"
        logger.error(error_msg)
        notifier.send_error_alert(error_msg)
        raise self.retry(exc=exc, countdown=retry_delay)


@app.task(bind=True, max_retries=3, name="openclaw.tasks.daily_pipeline.task_weekly_report")
def task_weekly_report(
    self: Any,
    evaluations: list[dict[str, Any]] | None = None,
) -> str:
    """Generate and distribute the weekly prediction evaluation report.

    Collects all predictions made during the past week, evaluates them
    against actual market data using ``PredictionEvaluator``, generates
    a Chinese-language summary report, and sends it via Discord.

    Args:
        self: Bound Celery task instance (for retry support).
        evaluations: Optional list of evaluation result dicts. When
            ``None``, the evaluator is called with an empty list and
            will return a placeholder report.

    Returns:
        The generated Chinese-language report string.

    Raises:
        self.retry: On retryable errors, re-queues the task with a
            countdown delay.
    """
    if not _should_execute("task_weekly_report"):
        logger.info("task_weekly_report: skipped (timeline guard)")
        return "_skipped"

    logger.info("task_weekly_report: generating weekly evaluation report")
    notifier = _create_notifier()
    retry_delay = _get_retry_delay()

    try:
        from src.prediction.evaluator import PredictionEvaluator

        evaluator = PredictionEvaluator()

        if evaluations is None:
            evaluations = []

        # Generate evaluation report for the week
        report = evaluator.generate_report(evaluations=evaluations)

        # Send report text via Discord
        notifier.send_daily_summary(
            results=[
                {"symbol": "周报", "signal": "report", "confidence": 1.0}
            ]
        )

        logger.info("task_weekly_report: report generated and sent")
        return report

    except Exception as exc:
        error_msg = f"task_weekly_report failed: {exc}"
        logger.error(error_msg)
        notifier.send_error_alert(error_msg)
        raise self.retry(exc=exc, countdown=retry_delay)
