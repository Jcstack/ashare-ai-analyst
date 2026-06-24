"""Data validation and enrichment layer for AI analysis inputs.

Validates data freshness, board type consistency, indicator completeness,
and computes a data quality score before passing data to LLM analysis.

Prevents common AI errors such as misattributing board types (e.g., treating
a main board stock as a STAR Market stock) or using stale data without
appropriate caveats.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

from src.utils.logger import get_logger
from src.utils.market_hours import get_market_session

logger = get_logger("prediction.data_validator")

# Board type detection based on symbol prefix
_BOARD_RULES: list[tuple[str, str, str]] = [
    ("688", "科创板", "±20%"),
    ("689", "科创板", "±20%"),
    ("300", "创业板", "±20%"),
    ("301", "创业板", "±20%"),
    ("60", "沪市主板", "±10%"),
    ("00", "深市主板", "±10%"),
    ("83", "北交所", "±30%"),
    ("87", "北交所", "±30%"),
    ("43", "北交所", "±30%"),
    ("92", "北交所", "±30%"),
]

# Key indicators that should be present for a complete analysis
_KEY_INDICATORS = ["MA_5", "MA_20", "RSI", "MACD_hist"]


@dataclass
class AnalysisContext:
    """Validated and enriched data context for AI analysis."""

    symbol: str
    name: str
    board_type: str  # "沪市主板" / "深市主板" / "创业板" / "科创板" / "北交所"
    price_limit: str  # "±10%" / "±20%" / "±30%"
    market_session: dict[str, Any] = field(default_factory=dict)
    quote: dict[str, Any] = field(default_factory=dict)
    quote_is_realtime: bool = False
    indicators: dict[str, Any] = field(default_factory=dict)
    indicators_complete: bool = False
    missing_indicators: list[str] = field(default_factory=list)
    fund_flow: list[dict[str, Any]] = field(default_factory=list)
    fund_flow_type: str = (
        "unavailable"  # intraday / today_final / historical / unavailable
    )
    fund_flow_note: str = ""
    sector_info: dict[str, Any] = field(default_factory=dict)
    news_items: list[dict[str, Any]] = field(default_factory=list)
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    indices: list[dict[str, Any]] = field(default_factory=list)
    position: dict[str, Any] | None = None
    strategy_signals: dict[str, Any] = field(default_factory=dict)
    bayesian_analysis: dict[str, Any] = field(default_factory=dict)
    intraday_trades: dict[str, Any] | None = None
    capital_flow_context: dict[str, Any] = field(default_factory=dict)
    support_resistance: list[dict[str, Any]] = field(default_factory=list)
    dragon_tiger: list[dict[str, Any]] = field(default_factory=list)
    fund_flow_detail: dict[str, Any] = field(default_factory=dict)
    fund_flow_timeline: list[dict[str, Any]] = field(default_factory=list)
    policy_context: str = ""
    divergence_signals: list[dict[str, Any]] = field(default_factory=list)
    valuation: dict[str, Any] = field(default_factory=dict)
    data_quality_score: int = 0
    data_warnings: list[str] = field(default_factory=list)


class AnalysisDataValidator:
    """Validates and enriches data before passing to AI analysis."""

    def validate_and_enrich(
        self,
        symbol: str,
        quote: dict[str, Any] | None = None,
        indicators: dict[str, Any] | None = None,
        fund_flow: Any = None,
        sector_info: dict[str, Any] | None = None,
        news: Any = None,
        anomalies: Any = None,
        indices: list[dict[str, Any]] | None = None,
        strategy_signals: dict[str, Any] | None = None,
        bayesian: dict[str, Any] | None = None,
        position: dict[str, Any] | None = None,
        intraday_trades: dict[str, Any] | None = None,
        capital_flow_context: dict[str, Any] | None = None,
        support_resistance: list[dict[str, Any]] | None = None,
        dragon_tiger: Any = None,
        fund_flow_detail: Any = None,
        fund_flow_timeline: list[dict] | None = None,
        policy_context: str = "",
        divergence_signals: list[dict[str, Any]] | None = None,
        valuation: dict[str, Any] | None = None,
    ) -> AnalysisContext:
        """Validate all data sources and return an enriched AnalysisContext.

        Args:
            symbol: 6-digit stock code.
            quote: Real-time quote dict.
            indicators: Technical indicator dict.
            fund_flow: Fund flow data (DataFrame or list of dicts).
            sector_info: Sector/concept board info.
            news: News data (DataFrame or list of dicts).
            anomalies: Anomaly data (DataFrame or list of dicts).
            indices: Market index data list.
            strategy_signals: Multi-strategy signal context.
            bayesian: Bayesian probability analysis.
            position: Optional portfolio position context.
            intraday_trades: Intraday tick stats and recent ticks.

        Returns:
            AnalysisContext with validated data and quality scores.
        """
        warnings: list[str] = []
        score = 100

        # 1. Board type detection
        board_type, price_limit = self._detect_board(symbol)

        # 2. Market session
        session = get_market_session()

        # 3. Quote validation
        quote = quote or {}
        quote_is_realtime = self._assess_quote_freshness(quote, session)
        if not quote or quote.get("price") is None:
            warnings.append("无行情数据" if not quote else "行情缺少价格数据")
            score -= 30
        elif not quote_is_realtime:
            warnings.append("行情数据可能非实时（非交易时段或数据延迟）")
            score -= 10

        # 4. Indicator completeness
        indicators = indicators or {}
        indicators_complete, missing = self._check_indicators(indicators)
        if not indicators:
            warnings.append("无技术指标数据")
            score -= 20
        elif not indicators_complete:
            warnings.append(f"缺少关键指标: {', '.join(missing)}")
            score -= 5 * len(missing)

        # 5. Fund flow freshness
        fund_flow_list = self._normalize_to_list(fund_flow)
        ff_type, ff_note = self._assess_fund_flow_freshness(fund_flow_list, session)
        if ff_type == "unavailable":
            warnings.append("无资金流向数据")
            score -= 10
        elif ff_type == "historical":
            warnings.append(ff_note)
            score -= 5

        # 5b. Fund flow vs market cap sanity check
        total_mv = (valuation or {}).get("total_mv", 0)
        if total_mv and fund_flow_list:
            main_net = fund_flow_list[0].get("main_net", 0)
            try:
                main_net_val = abs(float(main_net))
                total_mv_val = float(total_mv)
                if total_mv_val > 0 and main_net_val > total_mv_val * 0.10:
                    warnings.append(
                        "⚠ 资金流数据异常偏大(超过市值10%)，"
                        "可能为多日累计或数据源异常，请谨慎引用"
                    )
                    score -= 10
            except (TypeError, ValueError):
                pass

        # 6. News items
        news_list = self._normalize_to_list(news)
        if not news_list:
            warnings.append("无近期新闻数据")
            score -= 5

        # 7. Anomalies
        anomaly_list = self._normalize_to_list(anomalies)

        # 8. Sector info
        sector_info = sector_info or {}
        if not sector_info:
            warnings.append("无板块信息")
            score -= 5

        # 9. Strategy signals
        strategy_signals = strategy_signals or {}
        if not strategy_signals or isinstance(strategy_signals, Exception):
            strategy_signals = {}

        # 10. Bayesian analysis
        bayesian = bayesian or {}
        if not bayesian or isinstance(bayesian, Exception):
            bayesian = {}

        # 11. Indices
        indices = indices or []
        if not indices:
            warnings.append("无大盘指数数据")
            score -= 5

        # Clamp score
        score = max(0, min(100, score))

        name = quote.get("name", symbol) if quote else symbol

        ctx = AnalysisContext(
            symbol=symbol,
            name=name,
            board_type=board_type,
            price_limit=price_limit,
            market_session=session,
            quote=quote,
            quote_is_realtime=quote_is_realtime,
            indicators=indicators,
            indicators_complete=indicators_complete,
            missing_indicators=missing,
            fund_flow=fund_flow_list,
            fund_flow_type=ff_type,
            fund_flow_note=ff_note,
            sector_info=sector_info,
            news_items=news_list,
            anomalies=anomaly_list,
            indices=indices,
            position=position,
            strategy_signals=strategy_signals,
            bayesian_analysis=bayesian,
            intraday_trades=intraday_trades,
            data_quality_score=score,
            data_warnings=warnings,
        )

        # Enrich with extended context fields
        ctx.capital_flow_context = capital_flow_context or {}
        ctx.fund_flow_timeline = fund_flow_timeline or []
        ctx.support_resistance = support_resistance or []
        ctx.policy_context = policy_context
        ctx.divergence_signals = divergence_signals or []
        ctx.valuation = valuation or {}

        if dragon_tiger is not None:
            if hasattr(dragon_tiger, "to_dict"):
                ctx.dragon_tiger = (
                    dragon_tiger.to_dict(orient="records")
                    if not dragon_tiger.empty
                    else []
                )
            elif isinstance(dragon_tiger, list):
                ctx.dragon_tiger = dragon_tiger

        if fund_flow_detail is not None:
            if hasattr(fund_flow_detail, "to_dict"):
                ctx.fund_flow_detail = (
                    fund_flow_detail.iloc[0].to_dict()
                    if not fund_flow_detail.empty
                    else {}
                )
            elif isinstance(fund_flow_detail, dict):
                ctx.fund_flow_detail = fund_flow_detail

        logger.debug(
            "Validated data for %s: quality=%d, warnings=%d, board=%s",
            symbol,
            score,
            len(warnings),
            board_type,
        )
        return ctx

    @staticmethod
    def _detect_board(symbol: str) -> tuple[str, str]:
        """Detect board type and price limit from stock symbol prefix."""
        symbol = symbol.strip()
        for prefix, board, limit in _BOARD_RULES:
            if symbol.startswith(prefix):
                return board, limit
        return "未知板块", "±10%"

    @staticmethod
    def _assess_quote_freshness(quote: dict[str, Any], session: dict[str, Any]) -> bool:
        """Check if quote data is likely real-time."""
        if not quote:
            return False
        # During trading sessions, assume quote is real-time
        return bool(session.get("is_trading", False))

    @staticmethod
    def _check_indicators(indicators: dict[str, Any]) -> tuple[bool, list[str]]:
        """Check if key technical indicators are present."""
        if not indicators:
            return False, list(_KEY_INDICATORS)
        missing = []
        flat_keys = set()
        for key, value in indicators.items():
            flat_keys.add(key)
            if isinstance(value, dict):
                for sub_key in value:
                    flat_keys.add(f"{key}_{sub_key}")
                    flat_keys.add(sub_key)
        for needed in _KEY_INDICATORS:
            if needed not in flat_keys:
                missing.append(needed)
        return len(missing) == 0, missing

    @staticmethod
    def _assess_fund_flow_freshness(
        fund_flow: list[dict[str, Any]], session: dict[str, Any]
    ) -> tuple[str, str]:
        """Assess fund flow data type and return (type, note)."""
        if not fund_flow:
            return "unavailable", "无资金流向数据"

        latest_date = ""
        for row in fund_flow[:1]:
            latest_date = str(row.get("date", row.get("日期", "")))
            break

        today = datetime.date.today().isoformat()
        if latest_date == today or latest_date.replace("-", "") == today.replace(
            "-", ""
        ):
            if session.get("is_trading"):
                return "intraday", "盘中实时资金流向（截至当前，可能继续变化）"
            return "today_final", "今日收盘资金流向（最终数据）"

        if latest_date:
            return "historical", f"资金流向为 {latest_date} 数据（非今日）"
        return "unavailable", "资金流向数据日期未知"

    @staticmethod
    def _normalize_to_list(data: Any) -> list[dict[str, Any]]:
        """Convert DataFrame or list to list of dicts."""
        if data is None or isinstance(data, Exception):
            return []
        if isinstance(data, list):
            return data
        # pandas DataFrame
        if hasattr(data, "empty"):
            if data.empty:
                return []
            return data.to_dict(orient="records")
        return []
