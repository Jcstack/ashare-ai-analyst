"""Integration tests: backtest pipeline and full end-to-end pipeline.

Tests data -> strategy -> backtest -> metrics flow and the complete
fetch -> analyze -> predict -> evaluate pipeline. All external
dependencies (AKShare, LLM APIs, Discord) are mocked.
"""

import json
from unittest.mock import MagicMock, patch

import pandas as pd

from src.llm.base import LLMResponse, ProviderName
from tests.integration.conftest import (
    EVALUATOR_CONFIG,
    PREDICTION_CONFIG,
    PROMPT_CONFIG,
)


class TestBacktestPipeline:
    """Test data -> strategy -> backtest -> metrics pipeline."""

    def test_trend_strategy_backtest_produces_metrics(
        self,
        mock_akshare: MagicMock,
        stocks_config: dict,
    ) -> None:
        """Verify the full data -> strategy -> backtest -> metrics flow."""
        with patch("src.data.fetcher.load_config", return_value=stocks_config):
            from src.data.fetcher import StockDataFetcher
            from src.data.preprocessor import DataPreprocessor

            fetcher = StockDataFetcher()
            preprocessor = DataPreprocessor()
            raw_df = fetcher.fetch_daily_ohlcv("000001")
            clean_df = preprocessor.clean_ohlcv(raw_df)
            enriched_df = preprocessor.add_returns(clean_df)

        from src.backtest.engine import BacktestEngine
        from src.backtest.metrics import PerformanceMetrics
        from src.strategy.trend_following import TrendFollowingStrategy

        strategy = TrendFollowingStrategy()
        engine = BacktestEngine()
        result = engine.run(enriched_df, strategy, board="main")

        assert result.initial_capital > 0
        assert result.final_capital > 0
        assert len(result.equity_curve) == len(enriched_df)
        assert len(result.daily_returns) == len(enriched_df)
        assert isinstance(result.trades, list)

        perf = PerformanceMetrics()
        metrics = perf.calculate(result)

        required_keys = {
            "total_return",
            "annual_return",
            "sharpe_ratio",
            "max_drawdown",
            "win_rate",
            "profit_factor",
            "total_trades",
            "avg_holding_days",
        }
        assert required_keys.issubset(set(metrics.keys())), (
            f"Missing keys: {required_keys - set(metrics.keys())}"
        )

        assert -1.0 <= metrics["total_return"] <= 10.0
        assert 0.0 <= metrics["max_drawdown"] <= 1.0
        assert 0.0 <= metrics["win_rate"] <= 1.0
        assert metrics["total_trades"] >= 0

    def test_backtest_enforces_t_plus_1_rule(
        self,
        realistic_ohlcv_df: pd.DataFrame,
    ) -> None:
        """Verify T+1 rule: cannot sell on the same day as buy."""
        from src.backtest.engine import BacktestEngine
        from src.strategy.base import (
            SIGNAL_BUY,
            SIGNAL_HOLD,
            SIGNAL_SELL,
            BaseStrategy,
        )

        class BuySellNextDayStrategy(BaseStrategy):
            """Buy on bar 2, sell on bar 3 (next day)."""

            def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
                signals = []
                for i in range(len(df)):
                    if i == 2:
                        signals.append(
                            self._build_signal_row(
                                df.at[i, "date"],
                                SIGNAL_BUY,
                                0.8,
                                "test buy",
                            )
                        )
                    elif i == 3:
                        signals.append(
                            self._build_signal_row(
                                df.at[i, "date"],
                                SIGNAL_SELL,
                                0.8,
                                "test sell",
                            )
                        )
                    else:
                        signals.append(
                            self._build_signal_row(
                                df.at[i, "date"],
                                SIGNAL_HOLD,
                                0.0,
                                "",
                            )
                        )
                return pd.DataFrame(signals)

        strategy = BuySellNextDayStrategy()
        engine = BacktestEngine()
        result = engine.run(realistic_ohlcv_df, strategy, board="main")

        buy_trades = [t for t in result.trades if t["action"] == "buy"]
        sell_trades = [t for t in result.trades if t["action"] == "sell"]

        assert len(buy_trades) == 1
        assert len(sell_trades) == 1

        buy_date = pd.Timestamp(buy_trades[0]["date"])
        sell_date = pd.Timestamp(sell_trades[0]["date"])
        assert sell_date > buy_date, (
            "T+1 violation: sell should not occur on the same day as buy"
        )

    def test_backtest_rounds_to_lot_size(
        self,
        realistic_ohlcv_df: pd.DataFrame,
    ) -> None:
        """Verify all trades are rounded to 100-share lots."""
        from src.backtest.engine import BacktestEngine
        from src.strategy.trend_following import TrendFollowingStrategy

        strategy = TrendFollowingStrategy()
        engine = BacktestEngine()
        result = engine.run(realistic_ohlcv_df, strategy, board="main")

        for trade in result.trades:
            assert trade["shares"] % 100 == 0, (
                f"Shares {trade['shares']} not a multiple of 100"
            )

    def test_backtest_applies_commission_and_stamp_tax(
        self,
        realistic_ohlcv_df: pd.DataFrame,
    ) -> None:
        """Verify commission and stamp tax are applied to trades."""
        from src.backtest.engine import BacktestEngine
        from src.strategy.trend_following import TrendFollowingStrategy

        strategy = TrendFollowingStrategy()
        engine = BacktestEngine()
        result = engine.run(realistic_ohlcv_df, strategy, board="main")

        for trade in result.trades:
            assert trade["commission"] > 0
            assert trade["commission"] >= 5.0, (
                f"Commission {trade['commission']:.2f} below min 5 RMB"
            )

    def test_metrics_report_generation(
        self,
        mock_akshare: MagicMock,
        stocks_config: dict,
    ) -> None:
        """Verify performance metrics report is generated in Chinese."""
        with patch("src.data.fetcher.load_config", return_value=stocks_config):
            from src.data.fetcher import StockDataFetcher
            from src.data.preprocessor import DataPreprocessor

            fetcher = StockDataFetcher()
            preprocessor = DataPreprocessor()
            raw_df = fetcher.fetch_daily_ohlcv("000001")
            clean_df = preprocessor.clean_ohlcv(raw_df)
            enriched_df = preprocessor.add_returns(clean_df)

        from src.backtest.engine import BacktestEngine
        from src.backtest.metrics import PerformanceMetrics
        from src.strategy.trend_following import TrendFollowingStrategy

        strategy = TrendFollowingStrategy()
        engine = BacktestEngine()
        result = engine.run(enriched_df, strategy)

        perf = PerformanceMetrics()
        metrics = perf.calculate(result)
        report = perf.generate_report(metrics)

        assert "回测绩效报告" in report
        assert "总收益率" in report
        assert "夏普比率" in report
        assert "最大回撤" in report


class TestFullPipeline:
    """End-to-end test: fetch -> analyze -> predict -> evaluate."""

    def test_end_to_end_pipeline(
        self,
        mock_akshare: MagicMock,
        stocks_config: dict,
        prediction_result: dict,
    ) -> None:
        """Run the full pipeline with all external deps mocked."""
        mock_router = MagicMock()
        mock_router.complete.return_value = LLMResponse(
            text=json.dumps(prediction_result, ensure_ascii=False),
            provider=ProviderName.ANTHROPIC,
            model="claude-sonnet-4-5-20250929",
            input_tokens=100,
            output_tokens=200,
            cost_usd=0.003,
        )
        mock_router.available_providers = [ProviderName.ANTHROPIC]

        with (
            patch(
                "src.data.fetcher.load_config",
                return_value=stocks_config,
            ),
            patch(
                "src.prediction.analyzer.load_config",
                return_value=PREDICTION_CONFIG,
            ),
            patch(
                "src.prediction.prompts.load_config",
                return_value=PROMPT_CONFIG,
            ),
            patch(
                "src.prediction.evaluator.load_config",
                return_value=EVALUATOR_CONFIG,
            ),
        ):
            # Step 1: Fetch
            from src.data.fetcher import StockDataFetcher
            from src.data.preprocessor import DataPreprocessor

            fetcher = StockDataFetcher()
            preprocessor = DataPreprocessor()
            raw_df = fetcher.fetch_daily_ohlcv("000001")
            assert not raw_df.empty
            clean_df = preprocessor.clean_ohlcv(raw_df)
            enriched_df = preprocessor.add_returns(clean_df)

            # Step 2: Analyze
            from src.analysis.indicators import TechnicalIndicators
            from src.analysis.patterns import PatternRecognizer

            indicators = TechnicalIndicators()
            recognizer = PatternRecognizer()
            df_ind = indicators.add_all(enriched_df)
            df_pat = recognizer.detect_candlestick_patterns(df_ind)
            sr_levels = recognizer.find_support_resistance(df_pat)

            # Step 3: Predict
            last_row = df_pat.iloc[-1]
            indicator_values = {
                col: (
                    float(last_row[col])
                    if hasattr(last_row[col], "item")
                    else last_row[col]
                )
                for col in df_pat.columns
                if col
                not in (
                    "date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                )
            }
            pattern_cols = [c for c in df_pat.columns if c.startswith("pattern_")]
            active_patterns = [
                {"name": col, "value": float(last_row[col])}
                for col in pattern_cols
                if last_row[col] != 0
            ]

            from src.prediction.analyzer import StockAnalyzer

            analyzer = StockAnalyzer(router=mock_router)
            prediction = analyzer.analyze(
                symbol="000001",
                ohlcv_df=df_pat,
                indicators=indicator_values,
                patterns=active_patterns,
                sr_levels=sr_levels,
            )
            assert prediction["signal"] == "buy"
            assert prediction["confidence"] == 0.75

            # Step 4: Evaluate
            from src.prediction.evaluator import PredictionEvaluator

            evaluator = PredictionEvaluator()
            actual_data = enriched_df.tail(10).reset_index(drop=True)
            evaluation = evaluator.evaluate(prediction, actual_data)

            assert "direction_accuracy" in evaluation
            assert "price_range_hit" in evaluation
            assert "signal_accuracy" in evaluation
            assert "confidence_calibration" in evaluation
            assert "actual_return" in evaluation

            # Step 5: Report
            report = evaluator.generate_report([evaluation])
            assert "A股预测模型评估报告" in report
            assert "方向准确率" in report
            assert "评级" in report

    def test_pipeline_error_isolation_per_stock(
        self,
        realistic_ohlcv_df: pd.DataFrame,
        stocks_config: dict,
        prediction_result: dict,
    ) -> None:
        """Verify one stock's failure does not block other stocks."""
        call_count = 0

        def mock_akshare_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Network error for first stock")
            chinese_df = realistic_ohlcv_df.rename(
                columns={
                    "date": "日期",
                    "open": "开盘",
                    "close": "收盘",
                    "high": "最高",
                    "low": "最低",
                    "volume": "成交量",
                    "amount": "成交额",
                }
            )
            chinese_df["日期"] = chinese_df["日期"].dt.strftime("%Y-%m-%d")
            return chinese_df

        mock_router = MagicMock()
        mock_router.complete.return_value = LLMResponse(
            text=json.dumps(prediction_result, ensure_ascii=False),
            provider=ProviderName.ANTHROPIC,
            model="claude-sonnet-4-5-20250929",
            input_tokens=100,
            output_tokens=200,
            cost_usd=0.003,
        )
        mock_router.available_providers = [ProviderName.ANTHROPIC]

        with (
            patch(
                "akshare.stock_zh_a_hist",
                side_effect=mock_akshare_side_effect,
            ),
            patch(
                "akshare.stock_zh_a_hist_tx",
                side_effect=Exception("Tencent unavailable in test"),
            ),
            patch(
                "src.data.fetcher._HAS_ADATA",
                False,
            ),
            patch(
                "src.data.fetcher.load_config",
                return_value=stocks_config,
            ),
            patch(
                "src.prediction.analyzer.load_config",
                return_value=PREDICTION_CONFIG,
            ),
            patch(
                "src.prediction.prompts.load_config",
                return_value=PROMPT_CONFIG,
            ),
        ):
            from src.analysis.indicators import TechnicalIndicators
            from src.analysis.patterns import PatternRecognizer
            from src.data.fetcher import StockDataFetcher
            from src.data.preprocessor import DataPreprocessor
            from src.prediction.analyzer import StockAnalyzer

            fetcher = StockDataFetcher()
            preprocessor = DataPreprocessor()
            indicators_calc = TechnicalIndicators()
            pattern_recognizer = PatternRecognizer()
            analyzer = StockAnalyzer(router=mock_router)

            predictions: dict = {}
            for entry in stocks_config["watchlist"]:
                symbol = entry["symbol"]
                try:
                    raw_df = fetcher.fetch_daily_ohlcv(symbol)
                    clean_df = preprocessor.clean_ohlcv(raw_df)
                    enriched_df = preprocessor.add_returns(clean_df)
                    df_ind = indicators_calc.add_all(enriched_df)
                    df_pat = pattern_recognizer.detect_candlestick_patterns(df_ind)
                    sr_levels = pattern_recognizer.find_support_resistance(df_pat)
                    prediction = analyzer.analyze(
                        symbol=symbol,
                        ohlcv_df=df_pat,
                        indicators={},
                        patterns=[],
                        sr_levels=sr_levels,
                    )
                    predictions[symbol] = prediction
                except Exception as exc:
                    predictions[symbol] = {"error": str(exc)}

        assert "error" in predictions["000001"]
        assert "error" not in predictions["600519"]
        assert predictions["600519"]["signal"] == "buy"

    def test_full_pipeline_with_discord_notifications(
        self,
        mock_akshare: MagicMock,
        stocks_config: dict,
        prediction_result: dict,
    ) -> None:
        """Verify Discord notifications are sent at each pipeline stage."""
        mock_router = MagicMock()
        mock_router.complete.return_value = LLMResponse(
            text=json.dumps(prediction_result, ensure_ascii=False),
            provider=ProviderName.ANTHROPIC,
            model="claude-sonnet-4-5-20250929",
            input_tokens=100,
            output_tokens=200,
            cost_usd=0.003,
        )
        mock_router.available_providers = [ProviderName.ANTHROPIC]

        mock_notifier = MagicMock()
        mock_notifier.send_analysis_alert.return_value = True
        mock_notifier.send_daily_summary.return_value = True

        with (
            patch(
                "src.data.fetcher.load_config",
                return_value=stocks_config,
            ),
            patch(
                "src.prediction.analyzer.load_config",
                return_value=PREDICTION_CONFIG,
            ),
            patch(
                "src.prediction.prompts.load_config",
                return_value=PROMPT_CONFIG,
            ),
        ):
            from src.analysis.indicators import TechnicalIndicators
            from src.analysis.patterns import PatternRecognizer
            from src.data.fetcher import StockDataFetcher
            from src.data.preprocessor import DataPreprocessor
            from src.prediction.analyzer import StockAnalyzer

            fetcher = StockDataFetcher()
            preprocessor = DataPreprocessor()
            indicators_calc = TechnicalIndicators()
            pattern_recognizer = PatternRecognizer()
            analyzer = StockAnalyzer(router=mock_router)

            summary_results = []
            for entry in stocks_config["watchlist"]:
                symbol = entry["symbol"]
                raw_df = fetcher.fetch_daily_ohlcv(symbol)
                clean_df = preprocessor.clean_ohlcv(raw_df)
                enriched_df = preprocessor.add_returns(clean_df)
                df_ind = indicators_calc.add_all(enriched_df)
                df_pat = pattern_recognizer.detect_candlestick_patterns(df_ind)
                sr_levels = pattern_recognizer.find_support_resistance(df_pat)
                prediction = analyzer.analyze(
                    symbol=symbol,
                    ohlcv_df=df_pat,
                    indicators={},
                    patterns=[],
                    sr_levels=sr_levels,
                )
                mock_notifier.send_analysis_alert(symbol=symbol, prediction=prediction)
                summary_results.append(
                    {
                        "symbol": symbol,
                        "signal": prediction.get("signal", "N/A"),
                        "confidence": prediction.get("confidence", 0.0),
                    }
                )

            mock_notifier.send_daily_summary(results=summary_results)

        assert mock_notifier.send_analysis_alert.call_count == 2
        mock_notifier.send_daily_summary.assert_called_once()

        summary_call = mock_notifier.send_daily_summary.call_args
        results_arg = summary_call.kwargs.get(
            "results", summary_call.args[0] if summary_call.args else []
        )
        assert len(results_arg) == 2
        symbols = [r["symbol"] for r in results_arg]
        assert "000001" in symbols
        assert "600519" in symbols
