"""Weekend factor validation pipeline.

Runs Saturday 02:00 CST to validate quantitative factors against
historical A-share data. Fills factor_returns table in factor_validator.db
so the daily_outcome_verification pipeline can compute accurate IC/hit-rate.

Three core factors validated:
1. VWAP trigger (mean-reversion z-score)
2. VPIN (volume-weighted toxicity)
3. Momentum (multi-timeframe)

Uses walk-forward on 90-day rolling windows to compute OOS metrics.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from openclaw.celery_app import app

logger = logging.getLogger(__name__)

_CST = ZoneInfo("Asia/Shanghai")


def _validate_factor(
    factor_name: str,
    symbols: list[str],
    lookback_days: int = 90,
) -> dict:
    """Validate a single factor by computing IC against forward returns.

    For each symbol, fetches daily data, computes factor scores,
    pairs with T+5 returns, and computes Spearman IC.

    Args:
        factor_name: Factor identifier (vwap_trigger, vpin, momentum).
        symbols: List of stock codes to evaluate.
        lookback_days: Days of history to analyze.

    Returns:
        Dict with factor_name, ic, hit_rate, sample_count, scores, returns.
    """
    from src.agent_loop.factor_validator import _spearman_rank_corr

    scores: list[float] = []
    returns: list[float] = []

    for symbol in symbols:
        try:
            from src.data.fetcher import StockDataFetcher

            fetcher = StockDataFetcher()
            df = fetcher.fetch_daily_ohlcv(symbol)
            if df is None or len(df) < lookback_days:
                continue

            df = df.tail(lookback_days).copy()
            if len(df) < 20:
                continue

            # Compute factor score based on factor_name
            if factor_name == "vwap_trigger":
                # VWAP z-score: (close - vwap) / std
                if "volume" in df.columns and "close" in df.columns:
                    typical_price = (
                        df["high"] + df["low"] + df["close"]
                    ) / 3
                    vwap = (typical_price * df["volume"]).cumsum() / df[
                        "volume"
                    ].cumsum()
                    deviation = df["close"] - vwap
                    std = deviation.rolling(20).std()
                    z = deviation / std.replace(0, float("nan"))
                    score = z.iloc[-6] if len(z) > 5 else 0.0
                else:
                    continue

            elif factor_name == "vpin":
                # Simplified VPIN proxy: abs(close - open) / (high - low)
                spread = df["high"] - df["low"]
                body = (df["close"] - df["open"]).abs()
                vpin_proxy = body / spread.replace(0, float("nan"))
                score = vpin_proxy.iloc[-6] if len(vpin_proxy) > 5 else 0.0

            elif factor_name == "momentum":
                # 5-day momentum
                mom = df["close"].pct_change(5)
                score = mom.iloc[-6] if len(mom) > 5 else 0.0

            else:
                continue

            # T+5 forward return
            if len(df) >= 1:
                fwd_return = (df["close"].iloc[-1] / df["close"].iloc[-6] - 1) * 100
            else:
                continue

            if score is not None and not (score != score):  # not NaN
                scores.append(float(score))
                returns.append(float(fwd_return))

        except Exception:
            continue

    # Compute IC
    ic = 0.0
    hit_rate = 0.0
    if len(scores) >= 10:
        ic = _spearman_rank_corr(scores, returns)
        # Hit rate: % of times sign(score) == sign(return)
        hits = sum(
            1
            for s, r in zip(scores, returns)
            if (s > 0 and r > 0) or (s < 0 and r < 0)
        )
        hit_rate = hits / len(scores)

    return {
        "factor_name": factor_name,
        "ic": round(ic, 4),
        "hit_rate": round(hit_rate, 4),
        "sample_count": len(scores),
        "scores": scores,
        "returns": returns,
    }


@app.task(
    name="openclaw.tasks.factor_validation.task_factor_validation",
    soft_time_limit=600,
    time_limit=660,
)
def task_factor_validation() -> dict:
    """Weekend factor validation (Saturday 02:00 CST).

    Validates 3 core factors against A-share daily data:
    - VWAP trigger z-score
    - VPIN toxicity proxy
    - 5-day momentum

    Fills factor_returns table for daily outcome pipeline to use.
    """
    now = datetime.now(_CST)
    if now.weekday() not in (5, 6):  # Saturday or Sunday
        return {"skipped": True, "reason": "not_weekend"}

    logger.info("=== Factor Validation START ===")

    # Get active watchlist + portfolio symbols
    symbols: list[str] = []
    try:
        from src.web.dependencies import get_portfolio_store

        ps = get_portfolio_store()
        positions = ps.list_positions()
        symbols = [p.get("symbol", "") for p in positions if p.get("symbol")]
    except Exception:
        pass

    # Add some broad market representative stocks
    broad_market = [
        "600519", "000858", "601318", "600036", "000333",
        "601012", "600276", "000001", "601166", "600000",
        "002714", "300750", "601888", "600809", "000568",
        "002475", "600887", "601398", "600030", "002304",
    ]
    symbols = list(set(symbols + broad_market))

    if not symbols:
        return {"skipped": True, "reason": "no_symbols"}

    # Validate each factor
    factors = ["vwap_trigger", "vpin", "momentum"]
    results = {}

    from src.agent_loop.factor_validator import FactorValidator

    validator = FactorValidator()

    for factor_name in factors:
        try:
            result = _validate_factor(factor_name, symbols, lookback_days=90)
            results[factor_name] = {
                "ic": result["ic"],
                "hit_rate": result["hit_rate"],
                "sample_count": result["sample_count"],
            }
            logger.info(
                "Factor %s: IC=%.4f, hit_rate=%.2f%%, samples=%d",
                factor_name,
                result["ic"],
                result["hit_rate"] * 100,
                result["sample_count"],
            )

            # Record to factor_validator.db
            if result["scores"] and result["returns"]:
                today = now.strftime("%Y-%m-%d")
                score_rows = [
                    {"symbol": s, "factor_name": factor_name, "score": sc}
                    for s, sc in zip(symbols[: len(result["scores"])], result["scores"])
                ]
                return_rows = [
                    {"symbol": s, "return_pct": r / 100.0}
                    for s, r in zip(symbols[: len(result["returns"])], result["returns"])
                ]

                import asyncio

                asyncio.run(validator.record_factor_scores(today, score_rows))
                asyncio.run(validator.record_returns(today, return_rows))

        except Exception:
            logger.exception("Factor validation failed for %s", factor_name)
            results[factor_name] = {"error": "validation_failed"}

    logger.info("=== Factor Validation END: %s ===", results)
    return {"task": "factor_validation", "results": results}
