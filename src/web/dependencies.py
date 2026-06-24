"""FastAPI dependency injection for shared services and config.

All services are lazily instantiated singletons to avoid redundant
construction on every request.
"""

from __future__ import annotations

from functools import lru_cache

from src.utils.logger import get_logger
from src.web.services.stock_service import StockService

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_ai_news_service():
    """Return a singleton AiNewsService instance."""
    from src.web.services.ai_news_service import AiNewsService

    return AiNewsService()


@lru_cache(maxsize=1)
def get_watchlist_service():
    """Return a singleton WatchlistService instance."""
    from src.web.services.watchlist_service import WatchlistService

    svc = WatchlistService()
    svc.maybe_migrate_from_yaml()
    return svc


@lru_cache(maxsize=1)
def get_portfolio_store():
    """Return a singleton PortfolioStore with shared CapitalService."""
    from src.web.services.portfolio_store import PortfolioStore

    svc = PortfolioStore(capital_service=get_capital_service())
    svc.maybe_migrate_from_json()
    return svc


@lru_cache(maxsize=1)
def get_stock_service() -> StockService:
    """Return a singleton StockService instance."""
    return StockService(
        watchlist_service=get_watchlist_service(),
        qmt_adapter=get_qmt_adapter(),
    )


@lru_cache(maxsize=1)
def get_prediction_service():
    """Return a singleton PredictionService with shared StockService."""
    from src.web.services.prediction_service import PredictionService

    return PredictionService(stock_service=get_stock_service())


@lru_cache(maxsize=1)
def get_backtest_service():
    """Return a singleton BacktestService with shared StockService."""
    from src.web.services.backtest_service import BacktestService

    return BacktestService(stock_service=get_stock_service())


@lru_cache(maxsize=1)
def get_admin_service():
    """Return a singleton AdminService instance."""
    from src.web.services.admin_service import AdminService

    return AdminService()


@lru_cache(maxsize=1)
def get_llm_router():
    """Return a singleton LLMRouter instance."""
    from src.llm.router import LLMRouter

    return LLMRouter()


@lru_cache(maxsize=1)
def get_llm_gateway():
    """Return a singleton LLMGateway wrapping the LLMRouter with audit."""
    from src.llm.gateway import LLMGateway

    return LLMGateway(
        router=get_llm_router(),
        audit_log=get_audit_log(),
    )


@lru_cache(maxsize=1)
def get_qmt_adapter():
    """Return a singleton QmtDataAdapter instance.

    Connects lazily on first data request. Returns a disabled adapter
    when XtQuant is not installed (Docker/CI).
    """
    from src.data.qmt_adapter import QmtDataAdapter

    adapter = QmtDataAdapter()
    adapter.connect()  # no-op if not enabled/installed
    return adapter


@lru_cache(maxsize=1)
def get_stock_registry():
    """Return a singleton StockRegistry instance."""
    from src.data.registry import StockRegistry

    return StockRegistry()


@lru_cache(maxsize=1)
def get_realtime_quote_manager():
    """Return a singleton RealtimeQuoteManager instance."""
    from src.data.realtime import RealtimeQuoteManager

    return RealtimeQuoteManager(qmt_adapter=get_qmt_adapter())


@lru_cache(maxsize=1)
def get_news_fetcher():
    """Return a singleton NewsFetcher instance."""
    from src.data.news_fetcher import NewsFetcher

    return NewsFetcher()


@lru_cache(maxsize=1)
def get_alert_engine():
    """Return a singleton AlertEngine instance."""
    from src.analysis.alerts import AlertEngine

    return AlertEngine()


@lru_cache(maxsize=1)
def get_llm_result_cache():
    """Return a singleton LLMResultCache (L1+L2) for shared LLM result caching."""
    from src.llm.cache import LLMResultCache

    return LLMResultCache(redis_client=get_redis())


@lru_cache(maxsize=1)
def get_realtime_analyzer():
    """Return a singleton RealtimeAnalyzer instance."""
    from src.prediction.realtime_analyzer import RealtimeAnalyzer

    return RealtimeAnalyzer(router=get_llm_gateway(), cache=get_llm_result_cache())


@lru_cache(maxsize=1)
def get_sentiment_analyzer():
    """Return a singleton SentimentAnalyzer instance."""
    from src.analysis.sentiment import SentimentAnalyzer

    return SentimentAnalyzer(router=get_llm_gateway())


@lru_cache(maxsize=1)
def get_move_analyzer():
    """Return a singleton MoveAnalyzer instance."""
    from src.prediction.move_analyzer import MoveAnalyzer

    return MoveAnalyzer(router=get_llm_gateway())


@lru_cache(maxsize=1)
def get_strategy_lab_service():
    """Return a singleton StrategyLabService instance."""
    from src.web.services.strategy_lab_service import StrategyLabService

    return StrategyLabService()


@lru_cache(maxsize=1)
def get_paper_trade_signal_service():
    """Return a singleton PaperTradeSignalService with shared StockService."""
    from src.web.services.paper_trade_signal_service import PaperTradeSignalService

    return PaperTradeSignalService(stock_service=get_stock_service())


@lru_cache(maxsize=1)
def get_portfolio_service():
    """Return a singleton PortfolioService with shared StockService."""
    from src.web.services.portfolio_service import PortfolioService

    return PortfolioService(stock_service=get_stock_service())


@lru_cache(maxsize=1)
def get_strategy_context_service():
    """Return a singleton StrategyContextService with shared signal service."""
    from src.web.services.strategy_context_service import StrategyContextService

    return StrategyContextService(
        signal_service=get_paper_trade_signal_service(),
        stock_service=get_stock_service(),
    )


@lru_cache(maxsize=1)
def get_prompt_manager():
    """Return a singleton PromptManager instance."""
    from src.prediction.prompt_manager import PromptManager

    return PromptManager()


@lru_cache(maxsize=1)
def get_prompt_tester():
    """Return a singleton PromptTester instance."""
    from src.prediction.prompt_tester import PromptTester

    return PromptTester(prompt_manager=get_prompt_manager(), router=get_llm_gateway())


@lru_cache(maxsize=1)
def get_market_service():
    """Return a singleton MarketService with shared RealtimeQuoteManager."""
    from src.web.services.market_service import MarketService

    return MarketService(quote_manager=get_realtime_quote_manager())


@lru_cache(maxsize=1)
def get_analysis_data_validator():
    """Return a singleton AnalysisDataValidator instance."""
    from src.prediction.data_validator import AnalysisDataValidator

    return AnalysisDataValidator()


@lru_cache(maxsize=1)
def get_trading_calendar():
    """Return a singleton TradingCalendar instance."""
    from src.data.trading_calendar import TradingCalendar

    return TradingCalendar()


@lru_cache(maxsize=1)
def get_global_market_fetcher():
    """Return a singleton GlobalMarketFetcher instance."""
    from src.data.global_market import GlobalMarketFetcher

    return GlobalMarketFetcher()


@lru_cache(maxsize=1)
def get_timeline_scheduler():
    """Return a singleton TimelineScheduler instance."""
    from openclaw.timeline_scheduler import TimelineScheduler

    return TimelineScheduler()


@lru_cache(maxsize=1)
def get_trend_news_aggregator():
    """Return a singleton TrendNewsAggregator instance."""
    from src.data.trend_news import TrendNewsAggregator

    return TrendNewsAggregator()


@lru_cache(maxsize=1)
def get_keyword_matcher():
    """Return a singleton KeywordMatcher instance."""
    from src.data.trend_news import KeywordMatcher

    return KeywordMatcher()


@lru_cache(maxsize=1)
def get_advisor_service():
    """Return a singleton AdvisorService with shared StockService."""
    from src.web.services.advisor_service import AdvisorService

    return AdvisorService(stock_service=get_stock_service())


@lru_cache(maxsize=1)
def get_resonance_detector():
    """Return a singleton ResonanceDetector instance."""
    from src.data.trend_news import ResonanceDetector

    return ResonanceDetector(keyword_matcher=get_keyword_matcher())


@lru_cache(maxsize=1)
def get_cross_market_analyzer():
    """Return a singleton CrossMarketAnalyzer with shared GlobalMarketFetcher."""
    from src.analysis.cross_market import CrossMarketAnalyzer

    return CrossMarketAnalyzer(global_fetcher=get_global_market_fetcher())


@lru_cache(maxsize=1)
def get_sentiment_report_generator():
    """Return a singleton SentimentReportGenerator instance."""
    from src.prediction.sentiment_report import SentimentReportGenerator

    return SentimentReportGenerator(
        router=get_llm_gateway(), cache=get_llm_result_cache()
    )


@lru_cache(maxsize=1)
def get_sentiment_service():
    """Return a singleton SentimentService with shared StockService."""
    from src.web.services.sentiment_service import SentimentService

    return SentimentService(stock_service=get_stock_service())


@lru_cache(maxsize=1)
def get_notification_dispatcher():
    """Return a singleton NotificationDispatcher instance."""
    from src.web.services.notification_dispatcher import NotificationDispatcher

    return NotificationDispatcher()


@lru_cache(maxsize=1)
def get_sentinel_config_service():
    """Return a singleton SentinelConfigService instance."""
    from src.web.services.sentinel_config_service import SentinelConfigService

    return SentinelConfigService()


@lru_cache(maxsize=1)
def get_concept_board_service():
    """Return a singleton ConceptBoardService instance."""
    from src.data.concept_board import ConceptBoardService

    return ConceptBoardService()


@lru_cache(maxsize=1)
def get_concept_analyzer():
    """Return a singleton ConceptAnalyzer with shared ConceptBoardService."""
    from src.analysis.concept_analyzer import ConceptAnalyzer

    return ConceptAnalyzer(concept_service=get_concept_board_service())


@lru_cache(maxsize=1)
def get_association_profile_builder():
    """Return a singleton AssociationProfileBuilder with shared analyzers."""
    from src.analysis.association_graph import AssociationProfileBuilder

    return AssociationProfileBuilder(
        concept_analyzer=get_concept_analyzer(),
        cross_market_analyzer=get_cross_market_analyzer(),
    )


@lru_cache(maxsize=1)
def get_profile_override_service():
    """Return a singleton ProfileOverrideService instance."""
    from src.web.services.profile_override_service import ProfileOverrideService

    return ProfileOverrideService()


@lru_cache(maxsize=1)
def get_holiday_research_service():
    """Return a singleton HolidayResearchService with shared services."""
    from src.web.services.holiday_research_service import HolidayResearchService

    return HolidayResearchService(
        stock_service=get_stock_service(),
        advisor_service=get_advisor_service(),
        association_builder=get_association_profile_builder(),
        profile_override_service=get_profile_override_service(),
    )


@lru_cache(maxsize=1)
def get_conversation_service():
    """Return a singleton ConversationService with shared services."""
    from src.web.services.conversation_service import ConversationService

    return ConversationService(
        stock_service=get_stock_service(),
        realtime_analyzer=get_realtime_analyzer(),
        quote_manager=get_realtime_quote_manager(),
        trading_calendar=get_trading_calendar(),
        global_market_fetcher=get_global_market_fetcher(),
        info_store=get_info_store(),
    )


@lru_cache(maxsize=1)
def get_message_store():
    """Return a singleton MessageStore instance."""
    from src.web.services.message_store import MessageStore

    return MessageStore()


@lru_cache(maxsize=1)
def get_capital_service():
    """Return a singleton CapitalService instance."""
    from src.web.services.capital_service import CapitalService

    svc = CapitalService()
    # Migrate legacy available_capital from user_config on first access
    svc.maybe_migrate_from_config(get_user_config_service())
    return svc


@lru_cache(maxsize=1)
def get_trade_service():
    """Return a singleton TradeService instance."""
    from src.web.services.trade_service import TradeService

    return TradeService(
        capital_service=get_capital_service(),
        portfolio_store=get_portfolio_store(),
    )


@lru_cache(maxsize=1)
def get_user_config_service():
    """Return a singleton UserConfigService instance."""
    from src.web.services.user_config_service import UserConfigService

    return UserConfigService()


@lru_cache(maxsize=1)
def get_suggestion_service():
    """Return a singleton SuggestionService with shared services."""
    from src.web.services.suggestion_service import SuggestionService

    return SuggestionService(
        portfolio_service=get_portfolio_service(),
        stock_service=get_stock_service(),
        realtime_quote_manager=get_realtime_quote_manager(),
        concept_analyzer=get_concept_analyzer(),
    )


@lru_cache(maxsize=1)
def get_web_search_service():
    """Return a singleton WebSearchService for DuckDuckGo web search."""
    from src.web.services.web_search_service import WebSearchService

    return WebSearchService()


@lru_cache(maxsize=1)
def get_tool_registry():
    """Return a singleton ToolRegistry with all agent tools registered."""
    from src.web.services.tool_registry import ToolRegistry

    registry = ToolRegistry()
    registry.register_all(
        {
            "realtime_quote_manager": get_realtime_quote_manager(),
            "stock_registry": get_stock_registry(),
            "stock_service": get_stock_service(),
            "global_market_fetcher": get_global_market_fetcher(),
            "trading_calendar": get_trading_calendar(),
            "trend_news_aggregator": get_trend_news_aggregator(),
            "concept_board_service": get_concept_board_service(),
            "concept_analyzer": get_concept_analyzer(),
            "cross_market_analyzer": get_cross_market_analyzer(),
            "portfolio_service": get_portfolio_service(),
            "trade_service": get_trade_service(),
            "capital_service": get_capital_service(),
            "prediction_service": get_prediction_service(),
            "advisor_service": get_advisor_service(),
            "sentiment_service": get_sentiment_service(),
            "backtest_service": get_backtest_service(),
            "var_calculator": get_var_calculator(),
            "stress_tester": get_stress_tester(),
            "position_sizer": get_position_sizer(),
            "circuit_breaker": get_circuit_breaker(),
            "signal_library": get_signal_library(),
            "regime_detector": get_regime_detector(),
            "feature_store": get_feature_store(),
            "walk_forward_validator": get_walk_forward_validator(),
            "intelligence_hub_service": get_intelligence_hub_service(),
            "capital_flow_service": get_capital_flow_service(),
            "web_search_service": get_web_search_service(),
            "fusion_engine": get_signal_fusion_engine(),
            "minute_bar_fetcher": get_minute_bar_fetcher(),
            "gateway": get_llm_gateway(),
            "execution_bridge": get_execution_bridge(),
        }
    )
    return registry


@lru_cache(maxsize=1)
def get_lineage_service():
    """Return a singleton LineageService for data provenance tracking."""
    from src.web.services.lineage_service import LineageService

    return LineageService()


@lru_cache(maxsize=1)
def get_validation_framework():
    """Return a singleton ValidationFramework with default V01-V07 rules."""
    from src.web.services.validation_framework import ValidationFramework

    return ValidationFramework()


@lru_cache(maxsize=1)
def get_agent_registry():
    """Return a singleton AgentRegistry with all specialist agents bootstrapped."""
    from src.agents.registry import AgentRegistry

    registry = AgentRegistry()
    registry.bootstrap(
        tool_registry=get_tool_registry(),
        llm_router=get_llm_gateway(),
    )
    return registry


@lru_cache(maxsize=1)
def get_agent_service():
    """Return a singleton AgentService with LLM router and tool registry."""
    from src.web.services.agent_service import AgentService

    return AgentService(
        llm_router=get_llm_router(),
        tool_registry=get_tool_registry(),
        user_config_service=get_user_config_service(),
        trade_service=get_trade_service(),
        capital_service=get_capital_service(),
        lineage_service=get_lineage_service(),
        agent_registry=get_agent_registry(),
        model_monitor=get_model_monitor(),
        reflection_agent=get_reflection_agent(),
        memory_store=get_memory_store(),
        audit_log=get_audit_log(),
        schema_registry=get_schema_registry(),
        ensemble_validator=get_ensemble_validator(),
        intel_hub_service=get_intelligence_hub_service(),
        symbol_extractor=get_symbol_extractor(),
    )


@lru_cache(maxsize=1)
def get_walk_forward_validator():
    """Return a singleton WalkForwardValidator instance."""
    from src.quant.walk_forward import WalkForwardValidator

    return WalkForwardValidator()


@lru_cache(maxsize=1)
def get_regime_detector():
    """Return a singleton RegimeDetector instance."""
    from src.quant.regime_detector import RegimeDetector

    return RegimeDetector()


@lru_cache(maxsize=1)
def get_feature_store():
    """Return a singleton FeatureStore instance."""
    from src.quant.feature_store import FeatureStore

    return FeatureStore()


@lru_cache(maxsize=1)
def get_signal_library():
    """Return a singleton SignalLibrary instance."""
    from src.quant.signal_library import SignalLibrary

    return SignalLibrary()


@lru_cache(maxsize=1)
def get_var_calculator():
    """Return a singleton VaRCalculator instance."""
    from src.risk.var_calculator import VaRCalculator

    return VaRCalculator()


@lru_cache(maxsize=1)
def get_stress_tester():
    """Return a singleton StressTester instance."""
    from src.risk.stress_tester import StressTester

    return StressTester()


@lru_cache(maxsize=1)
def get_position_sizer():
    """Return a singleton PositionSizer instance."""
    from src.risk.position_sizer import PositionSizer

    return PositionSizer()


@lru_cache(maxsize=1)
def get_circuit_breaker():
    """Return a singleton CircuitBreaker instance."""
    from src.risk.circuit_breaker import CircuitBreaker

    return CircuitBreaker()


@lru_cache(maxsize=1)
def get_model_monitor():
    """Return a singleton ModelMonitor for prediction tracking and drift detection."""
    from src.intelligence.model_monitor import ModelMonitor

    return ModelMonitor()


@lru_cache(maxsize=1)
def get_reflection_agent():
    """Return a singleton ReflectionAgent for analysis quality review."""
    from src.intelligence.reflection_agent import ReflectionAgent

    return ReflectionAgent()


@lru_cache(maxsize=1)
def get_schema_registry():
    """Return a singleton SchemaRegistry with all agent I/O schemas registered."""
    from src.web.schemas.registry import SchemaRegistry
    from src.web.schemas.agent_io import register_all_schemas

    registry = SchemaRegistry()
    register_all_schemas(registry)
    return registry


@lru_cache(maxsize=1)
def get_ensemble_validator():
    """Return a singleton EnsembleValidator for multi-model cross-validation."""
    from src.intelligence.ensemble_validator import EnsembleValidator

    return EnsembleValidator(llm_router=get_llm_router())


@lru_cache(maxsize=1)
def get_memory_store():
    """Return a singleton MemoryStore for experience accumulation."""
    from src.intelligence.memory_store import MemoryStore

    return MemoryStore()


@lru_cache(maxsize=1)
def get_audit_log():
    """Return a singleton ImmutableAuditLog for tamper-proof event recording."""
    from src.audit.immutable_log import ImmutableAuditLog

    return ImmutableAuditLog()


@lru_cache(maxsize=1)
def get_confirmation_gate():
    """Return a singleton ConfirmationGate for multi-stage trade approval."""
    from src.workflow.confirmation_gate import ConfirmationGate

    return ConfirmationGate(audit_log=get_audit_log())


@lru_cache(maxsize=1)
def get_monitoring_agent():
    """Return a singleton MonitoringAgent for system health monitoring."""
    from src.agents.monitoring_agent import MonitoringAgent

    return MonitoringAgent()


@lru_cache(maxsize=1)
def get_data_health_tracker():
    """Return a singleton DataHealthTracker instance."""
    from src.data.health_tracker import DataHealthTracker

    return DataHealthTracker()


@lru_cache(maxsize=1)
def get_policy_news_fetcher():
    """Return a singleton PolicyNewsFetcher instance."""
    from src.data.policy_news import PolicyNewsFetcher

    return PolicyNewsFetcher()


@lru_cache(maxsize=1)
def get_redis():
    """Return a Redis client for notification storage, or None."""
    try:
        import redis

        from src.utils.config import load_config

        config = load_config("openclaw")
        broker = config.get("celery", {}).get("broker_url", "redis://redis:6379/0")
        return redis.from_url(broker, decode_responses=True)
    except Exception:
        return None


@lru_cache(maxsize=1)
def get_kill_switch():
    """Return a singleton KillSwitch backed by the shared Redis instance."""
    from src.trading.kill_switch import KillSwitch

    return KillSwitch(redis_client=get_redis())


@lru_cache(maxsize=1)
def get_preflight():
    """Return a singleton PreflightRiskCheck."""
    from src.trading.preflight import PreflightRiskCheck
    from src.web.services.broker_interface import create_broker
    from src.utils.config import load_config

    try:
        cfg = load_config("broker")
    except Exception:
        cfg = {}
    max_order = cfg.get("qmt", {}).get("max_order_amount", 100_000)

    return PreflightRiskCheck(
        kill_switch=get_kill_switch(),
        broker=create_broker(),
        max_order_amount=max_order,
    )


@lru_cache(maxsize=1)
def get_execution_bridge():
    """Return a singleton ExecutionBridge (None in simulation mode)."""
    from src.utils.config import load_config

    try:
        cfg = load_config("broker")
    except Exception:
        cfg = {}

    if cfg.get("mode", "simulation") == "simulation":
        return None

    from src.trading.execution_bridge import ExecutionBridge
    from src.web.services.broker_interface import create_broker

    exec_cfg = cfg.get("execution", {})
    return ExecutionBridge(
        broker=create_broker(),
        gate=get_confirmation_gate(),
        preflight=get_preflight(),
        kill_switch=get_kill_switch(),
        execution_mode=exec_cfg.get("mode", "dry_run"),
        max_price_slippage_pct=exec_cfg.get("max_price_slippage_pct", 2.0),
    )


@lru_cache(maxsize=1)
def get_system_alert_engine():
    """Return a singleton SystemAlertEngine for system-level alerts."""
    from src.intelligence.alert_engine import SystemAlertEngine

    return SystemAlertEngine()


@lru_cache(maxsize=1)
def get_signal_bus():
    """Return a singleton SignalBus for unified signal event bus."""
    from src.market_intelligence.signal_bus import SignalBus

    return SignalBus()


@lru_cache(maxsize=1)
def get_signal_store():
    """Return a singleton SignalStore for signal persistence."""
    from src.market_intelligence.signal_store import SignalStore

    return SignalStore()


@lru_cache(maxsize=1)
def get_macro_classifier():
    """Return a singleton MacroRegimeClassifier for macro regime classification."""
    from src.market_intelligence.macro_classifier import MacroRegimeClassifier

    return MacroRegimeClassifier(global_market_fetcher=get_global_market_fetcher())


@lru_cache(maxsize=1)
def get_risk_overlay_engine():
    """Return a singleton RiskOverlayEngine for signal risk assessment."""
    from src.market_intelligence.risk_overlay import RiskOverlayEngine

    return RiskOverlayEngine(
        regime_detector=get_regime_detector(),
        circuit_breaker=get_circuit_breaker(),
        var_calculator=get_var_calculator(),
        macro_classifier=get_macro_classifier(),
    )


@lru_cache(maxsize=1)
def get_confidence_scorer():
    """Return a singleton ConfidenceScorer for signal confidence scoring."""
    from src.market_intelligence.confidence_scorer import ConfidenceScorer

    return ConfidenceScorer(
        health_tracker=get_data_health_tracker(),
        signal_store=get_signal_store(),
        regime_detector=get_regime_detector(),
    )


@lru_cache(maxsize=1)
def get_signal_confirmation_gate():
    """Return a singleton SignalConfirmationGate for multi-source signal confirmation."""
    from src.market_intelligence.confirmation_gate import SignalConfirmationGate

    return SignalConfirmationGate()


@lru_cache(maxsize=1)
def get_phase_engine():
    """Return a singleton PhaseEngine for trading phase management."""
    from src.market_intelligence.phase_engine import PhaseEngine

    return PhaseEngine(trading_calendar=get_trading_calendar())


@lru_cache(maxsize=1)
def get_notification_log():
    """Return a singleton NotificationLog for notification delivery audit."""
    from src.market_intelligence.notification_log import NotificationLog

    return NotificationLog()


@lru_cache(maxsize=1)
def get_notification_orchestrator():
    """Return a singleton NotificationOrchestrator for intelligent signal routing."""
    from src.market_intelligence.notification_orchestrator import (
        NotificationOrchestrator,
    )

    return NotificationOrchestrator(
        dispatcher=get_notification_dispatcher(),
        phase_engine=get_phase_engine(),
        risk_overlay=get_risk_overlay_engine(),
        notification_log=get_notification_log(),
    )


@lru_cache(maxsize=1)
def get_sector_rotation_detector():
    """Return a singleton SectorRotationDetector for sector rotation analysis."""
    from src.market_intelligence.sector_rotation import SectorRotationDetector

    return SectorRotationDetector(stock_service=get_stock_service())


@lru_cache(maxsize=1)
def get_correlation_service():
    """Return a singleton CorrelationService for cross-asset correlation analysis."""
    from src.market_intelligence.correlation_service import CorrelationService

    return CorrelationService(stock_service=get_stock_service())


@lru_cache(maxsize=1)
def get_data_source_manager():
    """Return a singleton DataSourceManager for multi-source data health tracking."""
    from src.market_intelligence.data_source_manager import DataSourceManager

    return DataSourceManager(health_tracker=get_data_health_tracker())


@lru_cache(maxsize=1)
def get_latency_tracker():
    """Return a singleton LatencyTracker for signal pipeline latency metrics."""
    from src.market_intelligence.latency_tracker import LatencyTracker

    return LatencyTracker()


@lru_cache(maxsize=1)
def get_intel_report_store():
    """Return a singleton IntelReportStore for intel report persistence."""
    from src.intelligence_hub.report_store import IntelReportStore

    return IntelReportStore()


@lru_cache(maxsize=1)
def get_intel_report_service():
    """Return a singleton IntelReportService with shared stores."""
    from src.web.services.intel_report_service import IntelReportService

    return IntelReportService(
        report_store=get_intel_report_store(),
        info_store=get_info_store(),
    )


@lru_cache(maxsize=1)
def get_info_store():
    """Return a singleton InfoStore for intelligence hub persistence."""
    from src.intelligence_hub.info_store import InfoStore

    return InfoStore()


@lru_cache(maxsize=1)
def get_source_registry():
    """Return a singleton SourceRegistry from intelligence_hub config."""
    from src.intelligence_hub.source_registry import SourceRegistry
    from src.utils.config import load_config

    try:
        config = load_config("intelligence_hub")
    except Exception:
        config = {}

    sources_cfg = config.get("sources", {})
    sources_list = [
        {"source_id": sid, **scfg}
        for sid, scfg in sources_cfg.items()
        if scfg.get("enabled", True)
    ]
    health_cfg = config.get("health", {})
    return SourceRegistry(
        sources_list,
        warn_after=health_cfg.get("warn_after_failures", 3),
        down_after=health_cfg.get("down_after_failures", 8),
    )


@lru_cache(maxsize=1)
def get_content_scorer():
    """Return a singleton ContentScorer with shared SourceRegistry."""
    from src.intelligence_hub.scorer import ContentScorer
    from src.utils.config import load_config

    try:
        config = load_config("intelligence_hub")
    except Exception:
        config = {}

    return ContentScorer(
        registry=get_source_registry(),
        scoring_config=config.get("scoring"),
    )


@lru_cache(maxsize=1)
def get_social_guardrails():
    """Return a singleton SocialGuardrails for L5 priority enforcement."""
    from src.intelligence_hub.social_guardrails import SocialGuardrails

    return SocialGuardrails(registry=get_source_registry())


@lru_cache(maxsize=1)
def get_event_clusterer():
    """Return a singleton EventClusterer for cross-verification scoring."""
    from src.intelligence_hub.event_cluster import EventClusterer

    return EventClusterer()


@lru_cache(maxsize=1)
def get_diversity_reranker():
    """Return a singleton DiversityReranker for anti-filter-bubble feed diversity."""
    from src.intelligence_hub.diversity import DiversityReranker
    from src.utils.config import load_config

    try:
        config = load_config("intelligence_hub")
    except Exception:
        config = {}

    return DiversityReranker(
        registry=get_source_registry(),
        config=config.get("anti_filter_bubble"),
    )


@lru_cache(maxsize=1)
def get_refresh_scheduler():
    """Return a singleton RefreshScheduler for trading-day-aware intervals."""
    from src.intelligence_hub.scheduler import RefreshScheduler

    return RefreshScheduler(trading_calendar=get_trading_calendar())


@lru_cache(maxsize=1)
def get_delivery_tracker():
    """Return a singleton DeliveryTracker for delivery event persistence."""
    from src.intelligence_hub.delivery_tracker import DeliveryTracker

    return DeliveryTracker()


@lru_cache(maxsize=1)
def get_symbol_extractor():
    """Return a singleton SymbolExtractor for A-share stock code extraction.

    Reads extra_names from WatchlistService + PortfolioStore (SQLite),
    consistent with the Celery pipeline approach.
    """
    from src.intelligence_hub.symbol_extractor import SymbolExtractor

    extra_names: dict[str, str] = {}

    # From watchlist (SQLite)
    try:
        from src.web.services.watchlist_service import WatchlistService

        for item in WatchlistService().list_all():
            code = item.get("symbol", "")
            name = item.get("name", "")
            if code and name:
                extra_names[code] = name
    except Exception:
        pass

    # From portfolio (SQLite)
    try:
        from src.web.services.portfolio_store import PortfolioStore

        for pos in PortfolioStore(capital_service=None).list_positions():
            sym = pos.get("symbol", "")
            name = pos.get("name", "")
            if sym and name and sym not in extra_names:
                extra_names[sym] = name
    except Exception:
        pass

    return SymbolExtractor(extra_names=extra_names)


@lru_cache(maxsize=1)
def get_info_aggregator():
    """Return a singleton InfoAggregator with shared InfoStore, registry, scorer, dedup, guardrails, clusterer, and symbol extractor."""
    from src.intelligence_hub.aggregator import InfoAggregator
    from src.intelligence_hub.dedup import DedupChecker
    from src.utils.config import load_config

    try:
        config = load_config("intelligence_hub")
    except Exception:
        config = {}

    from src.intelligence_hub.simhash import FuzzyDedupChecker

    return InfoAggregator(
        store=get_info_store(),
        config=config,
        source_registry=get_source_registry(),
        scorer=get_content_scorer(),
        dedup_checker=DedupChecker(fuzzy_checker=FuzzyDedupChecker()),
        social_guardrails=get_social_guardrails(),
        event_clusterer=get_event_clusterer(),
        symbol_extractor=get_symbol_extractor(),
    )


@lru_cache(maxsize=1)
def get_intelligence_hub_service():
    """Return a singleton IntelligenceHubService with shared store, aggregator, reranker, and delivery tracker."""
    from src.web.services.intelligence_hub_service import IntelligenceHubService

    return IntelligenceHubService(
        store=get_info_store(),
        aggregator=get_info_aggregator(),
        source_registry=get_source_registry(),
        diversity_reranker=get_diversity_reranker(),
        delivery_tracker=get_delivery_tracker(),
        event_clusterer=get_event_clusterer(),
        symbol_extractor=get_symbol_extractor(),
    )


@lru_cache(maxsize=1)
def get_macro_flow_fetcher():
    """Return a singleton MacroFlowFetcher instance."""
    from src.data.macro_flow_fetcher import MacroFlowFetcher

    return MacroFlowFetcher()


@lru_cache(maxsize=1)
def get_capital_flow_scorer():
    """Return a singleton CapitalFlowScorer with shared MacroFlowFetcher."""
    from src.analysis.capital_flow_scorer import CapitalFlowScorer

    return CapitalFlowScorer(fetcher=get_macro_flow_fetcher())


@lru_cache(maxsize=1)
def get_sector_flow_fetcher():
    """Return a singleton SectorFlowFetcher instance."""
    from src.data.sector_flow_fetcher import SectorFlowFetcher

    return SectorFlowFetcher()


@lru_cache(maxsize=1)
def get_capital_flow_service():
    """Return a singleton CapitalFlowService with shared fetcher and scorer."""
    from src.web.services.capital_flow_service import CapitalFlowService

    return CapitalFlowService(
        macro_fetcher=get_macro_flow_fetcher(),
        scorer=get_capital_flow_scorer(),
        sector_fetcher=get_sector_flow_fetcher(),
    )


@lru_cache(maxsize=1)
def get_recommendation_service():
    """Return None — recommendation module removed in v38.0 AI-first refactor."""
    return None


@lru_cache(maxsize=1)
def get_qlib_adapter():
    """Return a singleton QlibAdapter (gracefully degrades when Qlib is absent)."""
    from src.prediction.qlib_adapter import QlibAdapter

    return QlibAdapter()


@lru_cache(maxsize=1)
def get_signal_fusion_engine():
    """Return a singleton SignalFusionEngine for multi-source signal fusion."""
    from src.prediction.signal_fusion import SignalFusionEngine

    return SignalFusionEngine(qlib_adapter=get_qlib_adapter())


@lru_cache(maxsize=1)
def get_extreme_market_conference():
    """Return a singleton ExtremeMarketConference for emergency evaluation."""
    from src.orchestration.extreme_market_conference import ExtremeMarketConference

    return ExtremeMarketConference(
        signal_store=get_signal_store(),
        global_market_fetcher=get_global_market_fetcher(),
        stock_service=get_stock_service(),
    )


@lru_cache(maxsize=1)
def get_signal_bridge():
    """Return a singleton SignalBridge for cross-process signal transport."""
    from src.market_intelligence.signal_bridge import SignalBridge

    return SignalBridge(redis_client=get_redis())


@lru_cache(maxsize=1)
def get_macro_radar_service():
    """Return a singleton MacroRadarService for global macro scanning."""
    from src.market_intelligence.macro_radar import MacroRadarService

    return MacroRadarService(
        global_fetcher=get_global_market_fetcher(),
        info_store=get_info_store(),
    )


@lru_cache(maxsize=1)
def get_trading_constraints_engine():
    """Return a singleton TradingConstraintsEngine for A-share rule enforcement."""
    from src.trading.constraints import TradingConstraintsEngine

    return TradingConstraintsEngine()


@lru_cache(maxsize=1)
def get_black_swan_detector():
    """Return a singleton BlackSwanDetector for extreme market event detection."""
    from src.intelligence.black_swan_detector import BlackSwanDetector

    return BlackSwanDetector()


@lru_cache(maxsize=1)
def get_impact_chain_engine():
    """Return a singleton ImpactChainEngine for event-to-asset transmission chains."""
    from src.intelligence.impact_chain import ImpactChainEngine

    return ImpactChainEngine()


@lru_cache(maxsize=1)
def get_position_macro_mapper():
    """Return a singleton PositionMacroMapper for holding-macro correlation."""
    from src.intelligence.position_macro_mapper import PositionMacroMapper

    return PositionMacroMapper()


@lru_cache(maxsize=1)
def get_rotation_engine():
    """Return a singleton RotationEngine for active portfolio rotation."""
    from src.intelligence.rotation_engine import RotationEngine

    return RotationEngine()


@lru_cache(maxsize=1)
def get_munger_checklist():
    """Return a singleton MungerChecklist for Buffett/Munger mental model checks."""
    from src.intelligence.munger_checklist import MungerChecklist

    return MungerChecklist()


@lru_cache(maxsize=1)
def get_relevance_scorer():
    """Return a singleton IntelRelevanceScorer for intel-to-holding mapping."""
    from src.intelligence.relevance_scorer import IntelRelevanceScorer

    return IntelRelevanceScorer()


@lru_cache(maxsize=1)
def get_debate_memory():
    """Return a singleton DebateMemory for debate history retrieval."""
    from src.intelligence.debate_memory import DebateMemory

    return DebateMemory()


@lru_cache(maxsize=1)
def get_debate_engine():
    """Return LLMDebateEngine (Phase 2) with Phase 1 fallback.

    Uses the LLM gateway for multi-round adversarial debate.
    Falls back to rule-based DebateEngine if LLM unavailable.
    """
    from src.intelligence.debate_engine import DebateEngine, LLMDebateEngine

    fallback = DebateEngine()
    try:
        gateway = get_llm_gateway()
        memory = get_debate_memory()
        return LLMDebateEngine(
            gateway=gateway,
            memory=memory,
            fallback_engine=fallback,
        )
    except Exception as exc:
        logger.warning("LLMDebateEngine init failed, using Phase 1: %s", exc)
        return fallback


@lru_cache(maxsize=1)
def get_macro_calendar_fetcher():
    """Return a singleton MacroCalendarFetcher instance."""
    from src.data.macro_calendar import MacroCalendarFetcher

    return MacroCalendarFetcher()


@lru_cache(maxsize=1)
def get_geopolitical_monitor():
    """Return a singleton GeopoliticalMonitor instance."""
    from src.data.geopolitical_monitor import GeopoliticalMonitor

    return GeopoliticalMonitor()


@lru_cache(maxsize=1)
def get_competitor_benchmark():
    """Return a singleton CompetitorBenchmark for peer comparison analysis."""
    from src.intelligence.competitor_benchmark import CompetitorBenchmark

    return CompetitorBenchmark()


@lru_cache(maxsize=1)
def get_qlib_alpha_engine():
    """Return a singleton QlibAlphaEngine with shared QlibAdapter."""
    from src.quant.qlib_alpha import QlibAlphaEngine

    return QlibAlphaEngine(qlib_adapter=get_qlib_adapter())


@lru_cache(maxsize=1)
def get_qlib_portfolio_optimizer():
    """Return a singleton QlibPortfolioOptimizer."""
    from src.quant.qlib_portfolio import QlibPortfolioOptimizer

    return QlibPortfolioOptimizer()


@lru_cache(maxsize=1)
def get_thesis_store():
    """Return a singleton ThesisStore for investment thesis persistence."""
    from src.agent_loop.thesis_store import ThesisStore

    return ThesisStore()


@lru_cache(maxsize=1)
def get_thesis_tracker():
    """Return a singleton ThesisTracker for thesis lifecycle management."""
    from src.agent_loop.thesis_tracker import ThesisTracker

    return ThesisTracker()


@lru_cache(maxsize=1)
def get_thesis_service():
    """Return a singleton ThesisService wrapping the ThesisTracker."""
    from src.web.services.thesis_service import ThesisService

    return ThesisService(tracker=get_thesis_tracker())


@lru_cache(maxsize=1)
def get_signal_aggregator():
    """Return a singleton SignalAggregator for multi-source signal merge."""
    from src.agent_loop.signal_aggregator import SignalAggregator
    from src.utils.config import load_config

    try:
        config = load_config("trading_loop").get("trading_loop", {})
    except Exception:
        config = {}

    return SignalAggregator(config=config)


@lru_cache(maxsize=1)
def get_confidence_calibrator():
    """Return a singleton ConfidenceCalibrator for adaptive learning."""
    from src.agent_loop.confidence_calibrator import ConfidenceCalibrator
    from src.utils.config import load_config

    try:
        config = load_config("trading_loop").get("trading_loop", {})
    except Exception:
        config = {}

    return ConfidenceCalibrator(config=config)


@lru_cache(maxsize=1)
def get_ashare_constraint_checker():
    """Return a singleton AShareConstraintChecker for T+1/price-limit/lot checks."""
    from src.agent_loop.ashare_constraints import AShareConstraintChecker
    from src.utils.config import load_config

    try:
        config = load_config("trading_loop").get("trading_loop", {})
    except Exception:
        config = {}

    return AShareConstraintChecker(config=config)


@lru_cache(maxsize=1)
def get_sentiment_cycle_detector():
    """Return a singleton SentimentCycleDetector."""
    from src.agent_loop.sentiment_cycle import SentimentCycleDetector

    return SentimentCycleDetector()


@lru_cache(maxsize=1)
def get_reflexivity_detector():
    """Return a singleton ReflexivityDetector."""
    from src.agent_loop.reflexivity_detector import ReflexivityDetector

    return ReflexivityDetector()


@lru_cache(maxsize=1)
def get_sector_correlation_monitor():
    """Return a singleton SectorCorrelationMonitor."""
    from src.data.sector_correlation import SectorCorrelationMonitor

    return SectorCorrelationMonitor()


@lru_cache(maxsize=1)
def get_mtf_engine():
    """Return a singleton MultiTimeframeEngine."""
    from src.quant.multi_timeframe import MultiTimeframeEngine

    return MultiTimeframeEngine()


@lru_cache(maxsize=1)
def get_minute_bar_fetcher():
    """Return a singleton MinuteBarFetcher backed by Redis."""
    from src.data.minute_bar import MinuteBarFetcher

    return MinuteBarFetcher(redis_client=get_redis())


@lru_cache(maxsize=1)
def get_leader_detector():
    """Return a singleton LeaderDetector."""
    from src.agent_loop.leader_detector import LeaderDetector

    return LeaderDetector()


@lru_cache(maxsize=1)
def get_llm_budget_tracker():
    """Return a singleton LLMBudgetTracker backed by Redis."""
    from src.llm.llm_budget import LLMBudgetTracker
    from src.utils.config import load_config

    try:
        budget_config = load_config("llm").get("budget", {})
    except Exception:
        budget_config = {}

    return LLMBudgetTracker(redis_client=get_redis(), config=budget_config)


@lru_cache(maxsize=1)
def get_decision_pipeline():
    """Return a singleton DecisionPipeline for signal-to-proposal conversion."""
    from src.agent_loop.bayesian_belief import BayesianBeliefEngine, CalibrationStore
    from src.agent_loop.decision_pipeline import DecisionPipeline
    from src.utils.config import load_config

    try:
        config = load_config("trading_loop").get("trading_loop", {})
    except Exception:
        config = {}

    from src.risk.position_sizer import PositionSizer, PositionSizingConfig

    sizer = PositionSizer(
        PositionSizingConfig(
            max_single_weight=config.get("max_position_pct", 0.30),
            kelly_fraction=config.get("kelly_fraction", 0.25),
            target_volatility=config.get("target_volatility", 0.15),
        )
    )

    calibration_store = CalibrationStore()
    loaded = calibration_store.load_empirical_tables()
    if loaded > 0:
        logger.info("Loaded %d empirical Bayesian calibration buckets", loaded)

    return DecisionPipeline(
        debate_engine=get_debate_engine(),
        calibrator=get_confidence_calibrator(),
        constraint_checker=get_ashare_constraint_checker(),
        position_sizer=sizer,
        bayesian_engine=BayesianBeliefEngine(calibration_store=calibration_store),
        sentiment_detector=get_sentiment_cycle_detector(),
        budget_tracker=get_llm_budget_tracker(),
        thesis_tracker=get_thesis_tracker(),
        leader_detector=get_leader_detector(),
        config=config,
    )


@lru_cache(maxsize=1)
def get_trading_loop():
    """Return a singleton AutonomousTradingLoop — the agent's brain."""
    from src.agent_loop.trading_loop import AutonomousTradingLoop
    from src.utils.config import load_config

    try:
        config = load_config("trading_loop").get("trading_loop", {})
    except Exception:
        config = {}

    loop = AutonomousTradingLoop(
        thesis_store=get_thesis_store(),
        signal_aggregator=get_signal_aggregator(),
        decision_pipeline=get_decision_pipeline(),
        portfolio_store=get_portfolio_store(),
        capital_service=get_capital_service(),
        notification_dispatcher=get_notification_dispatcher(),
        regime_detector=get_regime_detector(),
        debate_engine=get_debate_engine(),
        recommendation_service=get_recommendation_service(),
        signal_store=get_signal_store(),
        rotation_engine=get_rotation_engine(),
        black_swan_detector=get_black_swan_detector(),
        global_market_fetcher=get_global_market_fetcher(),
        position_macro_mapper=get_position_macro_mapper(),
        decision_log=get_decision_log(),
        intel_bridge=get_intel_bridge(),
        reflexivity_detector=get_reflexivity_detector(),
        sentiment_cycle_detector=get_sentiment_cycle_detector(),
        sector_correlation_monitor=get_sector_correlation_monitor(),
        mtf_engine=get_mtf_engine(),
        minute_bar_fetcher=get_minute_bar_fetcher(),
        leader_detector=get_leader_detector(),
        calibrator=get_confidence_calibrator(),
        action_queue_service=get_action_queue_service(),
        config=config,
    )

    # Wire OutcomeTracker with a real price fetcher so the LEARN phase works
    try:
        from src.agent_loop.outcome_tracker import OutcomeTracker

        async def _price_fetcher(symbol: str, date_str: str) -> float | None:
            """Fetch closing price for outcome evaluation."""
            from src.data.fetcher import DataFetcher

            try:
                fetcher = DataFetcher()
                date_compact = date_str.replace("-", "")
                df = fetcher.fetch_daily_ohlcv(
                    symbol, start_date=date_compact, end_date=date_compact
                )
                if df is not None and not df.empty and "close" in df.columns:
                    return float(df.iloc[-1]["close"])
            except Exception:
                pass
            return None

        loop.set_outcome_tracker(OutcomeTracker(), _price_fetcher)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning(
            "Failed to wire OutcomeTracker into trading loop: %s", exc
        )

    return loop


@lru_cache(maxsize=1)
def get_decision_log():
    """Return a singleton DecisionLog for outcome tracking."""
    from src.agent_loop.decision_log import DecisionLog

    return DecisionLog()


@lru_cache(maxsize=1)
def get_intel_bridge():
    """Return a singleton IntelBridge for intel→thesis→signal pipeline."""
    from src.agent_loop.intel_bridge import IntelBridge

    return IntelBridge(
        info_store=get_info_store(),
        impact_chain_engine=get_impact_chain_engine(),
        thesis_store=get_thesis_store(),
    )


@lru_cache(maxsize=1)
def get_signal_generation_service():
    """Return a singleton SignalGenerationService for the signal pipeline."""
    from src.web.services.signal_generation_service import SignalGenerationService

    return SignalGenerationService(
        stock_service=get_stock_service(),
        signal_library=get_signal_library(),
        policy_fetcher=get_policy_news_fetcher(),
        macro_classifier=get_macro_classifier(),
        phase_engine=get_phase_engine(),
        signal_store=get_signal_store(),
        notification_orchestrator=get_notification_orchestrator(),
        user_config_service=get_user_config_service(),
        macro_radar=get_macro_radar_service(),
    )


@lru_cache(maxsize=1)
def get_action_queue_service():
    """Return a singleton ActionQueueService instance."""
    from src.web.services.action_queue_service import ActionQueueService

    return ActionQueueService()


@lru_cache(maxsize=1)
def get_shared_belief_state():
    """Return a singleton SharedBeliefState backed by Redis."""
    from src.agent_loop.shared_belief_state import SharedBeliefState

    belief = SharedBeliefState(redis_client=get_redis())
    belief.load_from_redis()
    return belief


@lru_cache(maxsize=1)
def get_convergence_engine():
    """Return a singleton ConvergenceEngine."""
    from src.agent_loop.convergence_engine import ConvergenceEngine

    return ConvergenceEngine()


@lru_cache(maxsize=1)
def get_call_auction_provider():
    """Return a singleton CallAuctionCollector."""
    from src.data.call_auction import CallAuctionCollector

    return CallAuctionCollector()


@lru_cache(maxsize=1)
def get_signal_collector_factory():
    """Return a singleton SignalCollectorFactory with all data sources."""
    from src.agent_loop.signal_collector_factory import SignalCollectorFactory

    return SignalCollectorFactory(
        signal_store=get_signal_store(),
        sector_flow_fetcher=get_sector_flow_fetcher(),
        macro_flow_fetcher=get_macro_flow_fetcher(),
        leader_detector=get_leader_detector(),
        minute_bar_fetcher=get_minute_bar_fetcher(),
        info_store=get_info_store(),
    )


@lru_cache(maxsize=1)
def get_investment_director():
    """Return a singleton InvestmentDirector — the top-level orchestrator."""
    from src.agent_loop.investment_director import InvestmentDirector
    from src.utils.config import load_config

    try:
        config = load_config("trading_loop").get("trading_loop", {})
    except Exception:
        config = {}

    return InvestmentDirector(
        belief_state=get_shared_belief_state(),
        signal_aggregator=get_signal_aggregator(),
        decision_pipeline=get_decision_pipeline(),
        portfolio_store=get_portfolio_store(),
        capital_service=get_capital_service(),
        notification_dispatcher=get_notification_dispatcher(),
        regime_detector=get_regime_detector(),
        debate_engine=get_debate_engine(),
        thesis_store=get_thesis_store(),
        global_market_fetcher=get_global_market_fetcher(),
        decision_log=get_decision_log(),
        calibrator=get_confidence_calibrator(),
        convergence_engine=get_convergence_engine(),
        thesis_tracker=get_thesis_tracker(),
        call_auction_provider=get_call_auction_provider(),
        action_queue_service=get_action_queue_service(),
        signal_collector=get_signal_collector_factory(),
        risk_agent=get_risk_agent(),
        config=config,
    )


@lru_cache(maxsize=1)
def get_risk_agent():
    """Return a singleton RiskAgent — independent veto power over buy decisions."""
    from src.agent_loop.multi_agent_risk import RiskAgent

    try:
        return RiskAgent(
            gateway=get_llm_gateway(),
            tool_registry=get_tool_registry(),
            kill_switch=get_kill_switch(),
            circuit_breaker=get_circuit_breaker(),
        )
    except Exception as exc:
        logger.warning("RiskAgent init failed (will skip risk review): %s", exc)
        return None


@lru_cache(maxsize=1)
def get_factor_validator():
    """Return a singleton FactorValidator instance."""
    from src.agent_loop.factor_validator import FactorValidator

    return FactorValidator()


@lru_cache(maxsize=1)
def get_knowledge_graph():
    """Return a singleton KnowledgeGraph — temporal entity-relationship world model."""
    from src.intelligence.knowledge_graph import KnowledgeGraph

    return KnowledgeGraph()


@lru_cache(maxsize=1)
def get_impact_engine():
    """Return a singleton EventImpactEngine with CausalChainConstructor."""
    from src.intelligence.causal_chain import CausalChainConstructor
    from src.intelligence.impact_engine import EventImpactEngine

    constructor = CausalChainConstructor()
    return EventImpactEngine(chain_constructor=constructor)
