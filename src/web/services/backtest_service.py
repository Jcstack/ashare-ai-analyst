"""Service layer for strategy backtesting.

Wraps the backtest engine and performance metrics for web routes.
"""

from __future__ import annotations

from typing import Any

from src.backtest.engine import BacktestEngine
from src.backtest.metrics import PerformanceMetrics
from src.strategy.trend_following import TrendFollowingStrategy
from src.strategy.mean_reversion import MeanReversionStrategy
from src.strategy.momentum import MomentumStrategy
from src.strategy.base import BOARD_MAIN, BOARD_CHINEXT, BOARD_STAR
from src.web.services.stock_service import StockService
from src.utils.logger import get_logger

logger = get_logger("web.backtest_service")

# Available strategies mapped by key
STRATEGY_MAP: dict[str, type] = {
    "trend_following": TrendFollowingStrategy,
    "mean_reversion": MeanReversionStrategy,
    "momentum": MomentumStrategy,
}

STRATEGY_NAMES: dict[str, str] = {
    "trend_following": "趋势跟踪",
    "mean_reversion": "均值回归",
    "momentum": "动量策略",
}

BOARD_MAP: dict[str, str] = {
    "main": BOARD_MAIN,
    "chinext": BOARD_CHINEXT,
    "star": BOARD_STAR,
}


class BacktestService:
    """Service for running strategy backtests with A-share rules.

    Orchestrates data fetching, strategy selection, backtest execution,
    and performance metric calculation.
    """

    def __init__(self, stock_service: StockService | None = None) -> None:
        self._stock_service = stock_service or StockService()
        self._engine = BacktestEngine()
        self._metrics = PerformanceMetrics()

    def run_backtest(
        self,
        symbol: str,
        strategy_key: str,
        board: str = "main",
        param_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a backtest for a given stock and strategy.

        Args:
            symbol: 6-digit stock code.
            strategy_key: Strategy identifier (trend_following,
                mean_reversion, momentum).
            board: Board type (main, chinext, star).
            param_overrides: Optional parameter overrides for the strategy.

        Returns:
            Dict with keys: status, metrics, trades_count, strategy_name,
            equity_curve, signals, round_trips, dates, attribution,
            strategy_metadata. Returns error dict on failure.
        """
        if strategy_key not in STRATEGY_MAP:
            return {
                "status": "error",
                "message": f"未知策略: {strategy_key}",
            }

        # Fetch data with indicators (strategies need indicator columns)
        df = self._stock_service.get_stock_with_indicators(symbol)
        if df is None or df.empty:
            return {
                "status": "error",
                "message": f"无法获取 {symbol} 的数据",
            }

        board_type = BOARD_MAP.get(board, BOARD_MAIN)

        try:
            strategy = STRATEGY_MAP[strategy_key]()

            # Apply parameter overrides with type safety
            if param_overrides:
                for k, v in param_overrides.items():
                    if hasattr(strategy, k):
                        # Cast float→int when the strategy attribute is int-typed
                        # (frontend JSON sends all numbers as float via Pydantic)
                        current = getattr(strategy, k)
                        if isinstance(current, int) and isinstance(v, float):
                            v = int(v)
                        setattr(strategy, k, v)

            result = self._engine.run(df, strategy, board=board_type)
            metrics = self._metrics.calculate(result)
            report = self._metrics.generate_report(metrics)
            attribution = self._metrics.calculate_attribution(result)
            metadata = strategy.get_metadata()

            return {
                "status": "success",
                "symbol": symbol,
                "strategy_key": strategy_key,
                "strategy_name": STRATEGY_NAMES.get(strategy_key, strategy_key),
                "board": board,
                "metrics": metrics,
                "report": report,
                "trades_count": len(result.trades),
                "equity_curve": result.equity_curve,
                "initial_capital": result.initial_capital,
                "final_capital": result.final_capital,
                "signals": result.signals,
                "round_trips": result.round_trips,
                "dates": result.dates,
                "attribution": attribution,
                "strategy_metadata": metadata,
            }
        except Exception as exc:
            logger.error(
                "Backtest failed for %s with %s: %s",
                symbol,
                strategy_key,
                exc,
            )
            return {"status": "error", "message": f"回测执行失败: {exc}"}

    def get_strategy_metadata(self, strategy_key: str) -> dict[str, Any]:
        """Return metadata for a specific strategy.

        Args:
            strategy_key: Strategy identifier.

        Returns:
            Strategy metadata dict or error dict.
        """
        if strategy_key not in STRATEGY_MAP:
            return {"status": "error", "message": f"未知策略: {strategy_key}"}

        strategy = STRATEGY_MAP[strategy_key]()
        metadata = strategy.get_metadata()
        return {"status": "success", **metadata}

    def get_available_strategies(self) -> list[dict[str, str]]:
        """Return the list of available strategies.

        Returns:
            List of dicts with keys: key, name.
        """
        return [{"key": k, "name": v} for k, v in STRATEGY_NAMES.items()]
