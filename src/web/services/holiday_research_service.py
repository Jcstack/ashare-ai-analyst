"""Holiday Research Workbench service.

Orchestrates auto-collected data (news, concepts, global market, cross-market
peers, sentiment matching) with user-contributed research notes, then delegates
to the LLM for comprehensive holiday-period analysis and follow-up Q&A.

v3.4 additions: association profile integration, LLM research question
generation, structured evidence collection, and scenario analysis.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from src.utils.logger import get_logger
from src.web.services.stock_service import StockService

logger = get_logger("web.holiday_research_service")

_DISCLAIMER = "AI 分析仅供参考，不构成投资建议。股市有风险，投资需谨慎。"

_NOTE_TYPE_LABELS = {
    "observation": "市场观察",
    "box_office": "票房/销量数据",
    "industry_report": "行业报告",
    "policy": "政策消息",
    "custom": "其他信息",
}

_EVIDENCE_TYPE_LABELS = {
    "data_point": "数据点",
    "observation": "市场观察",
    "source_link": "信息来源",
    "analysis": "分析判断",
}

_IMPACT_LABELS = {
    "bullish": "利好",
    "bearish": "利空",
    "neutral": "中性",
}

_SYSTEM_PROMPT = """\
你是A股假期深度研究专家。在长假期间（如春节、国庆），A股停盘但全球市场持续交易，\
用户需要综合评估持仓在假期期间受到的影响，做出年后开盘操作决策。

你的任务是综合以下自动采集数据和用户补充数据，给出结构化的深度分析。

## 分析方法论
1. **业务因子提取**: 从新闻、用户笔记中识别关键业务因子（票房、销量、政策等）
2. **板块联动**: 分析所属概念板块在假期前后的动态和预期
3. **跨市场传导**: US/HK 同行在假期期间的表现如何传导至 A 股
4. **风险识别**: 概率×影响矩阵评估主要风险
5. **开盘策略**: 综合以上给出具体操作建议

## 输出要求
严格输出 JSON 格式，不要输出其他内容。
"""

_QUESTIONS_SYSTEM_PROMPT = """\
你是A股假期深度研究专家。根据用户提供的个股关联图谱（概念板块、跨市场同行、\
行业特征、关键指标），生成一组针对性强的假期研究问题。

## 要求
1. 生成 8-12 个研究问题
2. 问题必须结合该股票的具体行业特征，不要泛泛而谈
3. 每个问题分类: industry_event | competitor | policy | macro | cross_market | supply_chain
4. 每个问题标注优先级: high | medium | low
5. 每个问题附带 data_hint（告诉用户去哪里找数据）
6. 严格输出 JSON 格式
"""

_SCENARIO_SYSTEM_PROMPT = """\
你是A股假期深度研究专家。根据用户提供的个股关联图谱、已收集的证据材料，\
逐一评估每个情景假设。

## 分析方法
1. 结合证据评估每个情景的发生概率 (low/medium/high)
2. 评估价格影响方向 (up/down/flat) 和幅度 (small/medium/large)
3. 识别关键驱动因子
4. 指出情景特有风险

## 输出要求
严格输出 JSON 格式，不要输出其他内容。
"""


CONVERSATION_MAX_TURNS = 20  # max history turns sent to LLM

_CONVERSATION_SYSTEM_PROMPT = """\
你是A股假期深度研究专家。基于以下研究上下文与用户进行多轮对话。
用中文回答，保持对话上下文的连贯性，引用之前讨论过的要点。
不要重复问题，直接给出分析和建议。
"""


class HolidayResearchService:
    """Orchestrates holiday research data collection and AI analysis.

    Constructor injection follows the AdvisorService pattern.
    Internal components are lazily initialized.
    """

    REDIS_PREFIX = "holiday_research"
    NOTES_TTL = 30 * 86400  # 30 days
    CONVERSATION_TTL = 7 * 86400  # 7 days

    def __init__(
        self,
        stock_service: StockService | None = None,
        advisor_service: Any | None = None,
        association_builder: Any | None = None,
        profile_override_service: Any | None = None,
    ) -> None:
        self._stock_service = stock_service or StockService()
        self._advisor_service = advisor_service
        self._association_builder = association_builder
        self._profile_override_service = profile_override_service
        self._router = None
        self._news_fetcher = None
        self._concept_analyzer = None
        self._global_fetcher = None
        self._cross_market_analyzer = None
        self._trend_aggregator = None
        self._keyword_matcher = None
        self._trading_calendar = None
        self._quote_manager = None
        self._redis = None
        self._redis_checked = False

    # --- Lazy component getters ---

    def _get_router(self):
        if self._router is None:
            from src.web.dependencies import get_llm_gateway

            self._router = get_llm_gateway()
        return self._router

    def _get_news_fetcher(self):
        if self._news_fetcher is None:
            from src.data.news_fetcher import NewsFetcher

            self._news_fetcher = NewsFetcher()
        return self._news_fetcher

    def _get_concept_analyzer(self):
        if self._concept_analyzer is None:
            from src.analysis.concept_analyzer import ConceptAnalyzer
            from src.data.concept_board import ConceptBoardService

            self._concept_analyzer = ConceptAnalyzer(
                concept_service=ConceptBoardService()
            )
        return self._concept_analyzer

    def _get_global_fetcher(self):
        if self._global_fetcher is None:
            from src.data.global_market import GlobalMarketFetcher

            self._global_fetcher = GlobalMarketFetcher()
        return self._global_fetcher

    def _get_cross_market_analyzer(self):
        if self._cross_market_analyzer is None:
            from src.analysis.cross_market import CrossMarketAnalyzer

            self._cross_market_analyzer = CrossMarketAnalyzer(
                global_fetcher=self._get_global_fetcher()
            )
        return self._cross_market_analyzer

    def _get_trend_aggregator(self):
        if self._trend_aggregator is None:
            from src.data.trend_news import TrendNewsAggregator

            self._trend_aggregator = TrendNewsAggregator()
        return self._trend_aggregator

    def _get_keyword_matcher(self):
        if self._keyword_matcher is None:
            from src.data.trend_news import KeywordMatcher

            self._keyword_matcher = KeywordMatcher()
        return self._keyword_matcher

    def _get_trading_calendar(self):
        if self._trading_calendar is None:
            from src.data.trading_calendar import TradingCalendar

            self._trading_calendar = TradingCalendar()
        return self._trading_calendar

    def _get_quote_manager(self):
        if self._quote_manager is None:
            from src.data.realtime import RealtimeQuoteManager

            self._quote_manager = RealtimeQuoteManager()
        return self._quote_manager

    def _get_association_builder(self):
        if self._association_builder is None:
            from src.analysis.association_graph import AssociationProfileBuilder

            self._association_builder = AssociationProfileBuilder(
                concept_analyzer=self._get_concept_analyzer(),
                cross_market_analyzer=self._get_cross_market_analyzer(),
            )
        return self._association_builder

    def _get_redis(self):
        if not self._redis_checked:
            self._redis_checked = True
            try:
                import redis as redis_lib

                from src.utils.config import load_config

                config = load_config("openclaw")
                broker = config.get("celery", {}).get(
                    "broker_url", "redis://redis:6379/0"
                )
                self._redis = redis_lib.from_url(broker, decode_responses=True)
                self._redis.ping()
            except Exception:
                logger.debug("Redis unavailable, notes will use in-memory fallback")
                self._redis = None
        return self._redis

    def _get_holiday_key(self) -> str:
        """Get the holiday key (next trading day ISO date)."""
        try:
            cal = self._get_trading_calendar()
            next_day = cal.next_trading_day()
            if next_day:
                return next_day.isoformat()
        except Exception:
            pass
        return "unknown"

    # --- Data Collection ---

    def collect_context(self, symbol: str) -> dict[str, Any]:
        """Auto-collect research context for a stock during holiday.

        Gathers: stock news, concept sectors, global market, cross-market
        peers, trend sentiment matches, user notes, and association profile.
        """
        holiday_key = self._get_holiday_key()

        news = self._collect_news(symbol)
        concepts = self._collect_concepts(symbol)
        global_market = self._collect_global_market()
        cross_market = self._collect_cross_market(symbol, global_market)
        sentiment_matches = self._collect_sentiment_matches(symbol)
        user_notes = self.get_user_notes(symbol, holiday_key)
        calendar_info = self._collect_calendar_info()
        association_profile = self._collect_association_profile(symbol)
        quote = self._collect_quote(symbol)

        return {
            "status": "success",
            "symbol": symbol,
            "holiday_key": holiday_key,
            "news": news,
            "concepts": concepts,
            "global_market": global_market,
            "cross_market": cross_market,
            "sentiment_matches": sentiment_matches,
            "user_notes": user_notes,
            "calendar_info": calendar_info,
            "association_profile": association_profile,
            "quote": quote,
        }

    def _collect_news(self, symbol: str) -> list[dict[str, Any]]:
        try:
            fetcher = self._get_news_fetcher()
            df = fetcher.fetch_stock_news(symbol)
            if df is not None and not df.empty:
                records = df.head(10).to_dict(orient="records")
                return [
                    {
                        "title": r.get("title", ""),
                        "datetime": str(r.get("datetime", "")),
                        "source": r.get("source", ""),
                        "url": r.get("url", ""),
                    }
                    for r in records
                ]
        except Exception as exc:
            logger.debug("News collection failed for %s: %s", symbol, exc)
        return []

    def _collect_concepts(self, symbol: str) -> list[dict[str, Any]]:
        try:
            analyzer = self._get_concept_analyzer()
            result = analyzer.analyze_stock_concepts(symbol)
            concepts = []
            for c in result.concepts[:5]:
                concepts.append(
                    {
                        "name": c.name,
                        "pct_change": getattr(c, "pct_change", 0.0),
                        "rank_in_concept": getattr(c, "rank_in_concept", 0),
                        "concept_size": getattr(c, "concept_size", 0),
                    }
                )
            return concepts
        except Exception as exc:
            logger.debug("Concept collection failed for %s: %s", symbol, exc)
            return []

    def _collect_global_market(self) -> dict[str, Any]:
        try:
            fetcher = self._get_global_fetcher()
            return fetcher.fetch_global_snapshot() or {}
        except Exception as exc:
            logger.debug("Global market collection failed: %s", exc)
            return {}

    def _collect_cross_market(
        self, symbol: str, global_snapshot: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            analyzer = self._get_cross_market_analyzer()
            return analyzer.assess_cross_market_impact(
                symbol, global_snapshot=global_snapshot
            )
        except Exception as exc:
            logger.debug("Cross-market collection failed for %s: %s", symbol, exc)
            return {}

    def _collect_sentiment_matches(self, symbol: str) -> list[dict[str, Any]]:
        try:
            aggregator = self._get_trend_aggregator()
            matcher = self._get_keyword_matcher()
            trends = aggregator.fetch_all()
            matched = matcher.match_all_stocks(trends, [symbol])
            items = matched.get(symbol, [])
            return [
                {
                    "title": t.title,
                    "platform": t.platform,
                    "heat_score": t.heat_score,
                }
                for t in items[:8]
            ]
        except Exception as exc:
            logger.debug("Sentiment match failed for %s: %s", symbol, exc)
            return []

    def _collect_quote(self, symbol: str) -> dict[str, Any]:
        """Collect real-time quote for a stock to prevent price hallucination."""
        try:
            mgr = self._get_quote_manager()
            quote = mgr.get_single_quote(symbol)
            if quote and quote.get("price") is not None:
                return {
                    "price": quote.get("price"),
                    "change": quote.get("change"),
                    "pct_change": quote.get("pct_change"),
                    "volume": quote.get("volume"),
                    "open": quote.get("open"),
                    "high": quote.get("high"),
                    "low": quote.get("low"),
                    "name": quote.get("name", ""),
                }
        except Exception as exc:
            logger.debug("Quote collection failed for %s: %s", symbol, exc)
        return {}

    def _collect_calendar_info(self) -> dict[str, Any]:
        try:
            cal = self._get_trading_calendar()
            return {
                "is_holiday_period": cal.is_holiday_period(),
                "next_trading_day": str(cal.next_trading_day()),
                "current_session": cal.current_session().value
                if cal.current_session()
                else "unknown",
            }
        except Exception as exc:
            logger.debug("Calendar info failed: %s", exc)
            return {}

    def _collect_association_profile(self, symbol: str) -> dict[str, Any] | None:
        """Build association profile via AssociationProfileBuilder, with overrides."""
        try:
            builder = self._get_association_builder()
            profile = builder.build_profile(symbol)

            # Apply user overrides if available
            if self._profile_override_service is not None:
                overrides = self._profile_override_service.get_override(symbol)
                if overrides:
                    builder.apply_overrides(profile, overrides)

            return profile.to_dict()
        except Exception as exc:
            logger.debug("Association profile failed for %s: %s", symbol, exc)
            return None

    # --- User Notes (Redis-backed) ---

    def get_user_notes(self, symbol: str, holiday_key: str) -> list[dict[str, Any]]:
        """Get user notes from Redis, or empty list if unavailable."""
        r = self._get_redis()
        if r is None:
            return []

        key = f"{self.REDIS_PREFIX}:notes:{symbol}:{holiday_key}"
        try:
            raw = r.get(key)
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.debug("Redis get notes failed: %s", exc)
        return []

    def add_user_note(
        self, symbol: str, holiday_key: str, content: str, note_type: str
    ) -> dict[str, Any]:
        """Add a user research note. Returns the created note."""
        note = {
            "id": str(uuid.uuid4())[:8],
            "content": content,
            "note_type": note_type,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        r = self._get_redis()
        if r is None:
            return note

        key = f"{self.REDIS_PREFIX}:notes:{symbol}:{holiday_key}"
        try:
            existing = self.get_user_notes(symbol, holiday_key)
            existing.append(note)
            r.set(key, json.dumps(existing, ensure_ascii=False), ex=self.NOTES_TTL)
        except Exception as exc:
            logger.debug("Redis add note failed: %s", exc)

        return note

    def delete_user_note(self, symbol: str, holiday_key: str, note_id: str) -> bool:
        """Delete a note by ID. Returns True if found and deleted."""
        r = self._get_redis()
        if r is None:
            return False

        key = f"{self.REDIS_PREFIX}:notes:{symbol}:{holiday_key}"
        try:
            notes = self.get_user_notes(symbol, holiday_key)
            original_len = len(notes)
            notes = [n for n in notes if n.get("id") != note_id]
            if len(notes) < original_len:
                r.set(key, json.dumps(notes, ensure_ascii=False), ex=self.NOTES_TTL)
                return True
        except Exception as exc:
            logger.debug("Redis delete note failed: %s", exc)
        return False

    # --- Structured Evidence (v3.4) ---

    def get_evidence(self, symbol: str, holiday_key: str) -> list[dict[str, Any]]:
        """Get structured evidence items from Redis."""
        r = self._get_redis()
        if r is None:
            return []

        key = f"{self.REDIS_PREFIX}:evidence:{symbol}:{holiday_key}"
        try:
            raw = r.get(key)
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.debug("Redis get evidence failed: %s", exc)
        return []

    def add_evidence(
        self,
        symbol: str,
        holiday_key: str,
        content: str,
        evidence_type: str = "observation",
        linked_question_id: str = "",
        impact: str = "neutral",
        confidence: str = "medium",
        source: str = "",
    ) -> dict[str, Any]:
        """Add a structured evidence item. Returns the created item."""
        item = {
            "id": str(uuid.uuid4())[:8],
            "content": content,
            "evidence_type": evidence_type,
            "linked_question_id": linked_question_id,
            "impact": impact,
            "confidence": confidence,
            "source": source,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        r = self._get_redis()
        if r is None:
            return item

        key = f"{self.REDIS_PREFIX}:evidence:{symbol}:{holiday_key}"
        try:
            existing = self.get_evidence(symbol, holiday_key)
            existing.append(item)
            r.set(key, json.dumps(existing, ensure_ascii=False), ex=self.NOTES_TTL)
        except Exception as exc:
            logger.debug("Redis add evidence failed: %s", exc)

        return item

    def delete_evidence(self, symbol: str, holiday_key: str, evidence_id: str) -> bool:
        """Delete an evidence item by ID. Returns True if found and deleted."""
        r = self._get_redis()
        if r is None:
            return False

        key = f"{self.REDIS_PREFIX}:evidence:{symbol}:{holiday_key}"
        try:
            items = self.get_evidence(symbol, holiday_key)
            original_len = len(items)
            items = [i for i in items if i.get("id") != evidence_id]
            if len(items) < original_len:
                r.set(key, json.dumps(items, ensure_ascii=False), ex=self.NOTES_TTL)
                return True
        except Exception as exc:
            logger.debug("Redis delete evidence failed: %s", exc)
        return False

    # --- LLM Research Question Generation (v3.4) ---

    def generate_research_questions(self, symbol: str) -> dict[str, Any]:
        """Generate targeted research questions based on association profile.

        Returns a checklist dict with LLM-generated questions.
        """
        from src.llm.base import LLMMessage
        from src.llm.router import RoutingStrategy

        # Build association profile
        profile_dict = self._collect_association_profile(symbol) or {}

        # Get stock name
        stock_name = self._get_stock_name(symbol)

        # Build prompt
        prompt_parts = [f"## 个股: {stock_name}（{symbol}）\n"]

        if profile_dict:
            # Concepts
            concepts = profile_dict.get("concepts", [])
            if concepts:
                names = ", ".join(c.get("name", "") for c in concepts[:8])
                prompt_parts.append(f"## 概念板块\n{names}\n")

            # Cross-market peers
            peers = profile_dict.get("cross_market_peers", [])
            if peers:
                peer_str = ", ".join(
                    f"{p.get('symbol', '')}({p.get('market', '')})" for p in peers
                )
                prompt_parts.append(f"## 跨市场同行\n{peer_str}\n")

            # Industry profile
            ip = profile_dict.get("industry_profile")
            if ip:
                prompt_parts.append(f"## 行业: {ip.get('display', '')}")
                metrics = ip.get("key_metrics", [])
                if metrics:
                    prompt_parts.append(f"关键指标: {', '.join(metrics)}")
                vc = ip.get("value_chain", [])
                if vc:
                    prompt_parts.append(f"产业链: {' → '.join(vc)}")
                hints = ip.get("research_hints", {})
                if hints:
                    hints_str = "\n".join(f"- {k}: {v}" for k, v in hints.items())
                    prompt_parts.append(f"数据源提示:\n{hints_str}")
                prompt_parts.append("")

            # Tags
            tags = profile_dict.get("cross_market_tags", [])
            if tags:
                prompt_parts.append(f"## 行业标签: {', '.join(tags)}\n")

        # Calendar
        calendar_info = self._collect_calendar_info()
        if calendar_info:
            prompt_parts.append(
                f"## 假期信息\n下一交易日: {calendar_info.get('next_trading_day', 'N/A')}\n"
            )

        prompt_parts.append(
            "## 请输出 JSON\n"
            "```json\n"
            '{"questions": [\n'
            '  {"id": "q1", "category": "industry_event|competitor|policy|macro|cross_market|supply_chain",\n'
            '   "text": "问题文本", "priority": "high|medium|low",\n'
            '   "data_hint": "数据源提示", "status": "pending"}\n'
            "]}\n"
            "```"
        )

        router = self._get_router()
        messages = [
            LLMMessage(role="system", content=_QUESTIONS_SYSTEM_PROMPT),
            LLMMessage(role="user", content="\n".join(prompt_parts)),
        ]

        try:
            response = router.complete(
                messages=messages,
                caller="holiday_research.questions",
                strategy=RoutingStrategy.QUALITY,
                max_tokens=2048,
                temperature=0.4,
                symbol=symbol,
                analysis_type="holiday_research_questions",
            )
            questions = self._parse_questions(response.text)
            return {
                "status": "success",
                "symbol": symbol,
                "questions": questions,
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        except Exception as exc:
            logger.exception(
                "Research question generation failed for %s: %s", symbol, exc
            )
            return {
                "status": "error",
                "symbol": symbol,
                "questions": [],
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }

    def _parse_questions(self, text: str) -> list[dict[str, Any]]:
        """Parse LLM response into research questions."""
        try:
            cleaned = text.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json", 1)[1]
                cleaned = cleaned.split("```", 1)[0]
            elif "```" in cleaned:
                cleaned = cleaned.split("```", 1)[1]
                cleaned = cleaned.split("```", 1)[0]

            parsed = json.loads(cleaned.strip())
            if isinstance(parsed, dict):
                return parsed.get("questions", [])
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, IndexError) as exc:
            logger.debug("Question JSON parse failed: %s", exc)
        return []

    # --- Scenario Analysis (v3.4) ---

    def analyze_scenarios(
        self,
        symbol: str,
        holiday_key: str,
        scenarios: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Evaluate scenarios using collected evidence + association profile.

        If no scenarios provided, generates default 乐观/基准/悲观 scenarios.
        """
        from src.llm.base import LLMMessage
        from src.llm.router import RoutingStrategy

        stock_name = self._get_stock_name(symbol)
        profile_dict = self._collect_association_profile(symbol) or {}
        evidence = self.get_evidence(symbol, holiday_key)
        notes = self.get_user_notes(symbol, holiday_key)

        # Default scenarios if none provided
        if not scenarios:
            ip = profile_dict.get("industry_profile", {})
            display = ip.get("display", "该行业") if ip else "该行业"
            scenarios = [
                {
                    "name": "乐观情景",
                    "description": f"{display}核心指标超预期，板块情绪回暖",
                    "key_assumptions": ["核心指标超预期", "全球市场偏暖", "无重大利空"],
                },
                {
                    "name": "基准情景",
                    "description": f"{display}核心指标符合预期，市场整体平稳",
                    "key_assumptions": [
                        "核心指标符合预期",
                        "全球市场中性",
                        "无显著变化",
                    ],
                },
                {
                    "name": "悲观情景",
                    "description": f"{display}核心指标不及预期或出现利空",
                    "key_assumptions": [
                        "核心指标低于预期",
                        "全球市场偏弱",
                        "出现负面事件",
                    ],
                },
            ]

        # Build prompt
        prompt_parts = [f"## 分析目标\n{stock_name}（{symbol}）假期情景分析\n"]

        # Association context
        if profile_dict:
            ip = profile_dict.get("industry_profile")
            if ip:
                prompt_parts.append(
                    f"## 行业: {ip.get('display', '')}\n"
                    f"关键指标: {', '.join(ip.get('key_metrics', []))}\n"
                )
            concepts = profile_dict.get("concepts", [])
            if concepts:
                names = ", ".join(c.get("name", "") for c in concepts[:5])
                prompt_parts.append(f"## 概念板块: {names}\n")

        # Evidence
        if evidence:
            evidence_lines = []
            for e in evidence:
                impact_label = _IMPACT_LABELS.get(e.get("impact", ""), "中性")
                evidence_lines.append(
                    f"- [{impact_label}] {e.get('content', '')} "
                    f"(来源: {e.get('source', '用户')}, 置信度: {e.get('confidence', 'medium')})"
                )
            prompt_parts.append("## 已收集证据\n" + "\n".join(evidence_lines) + "\n")

        # Notes
        if notes:
            notes_text = "\n".join(f"- {n.get('content', '')}" for n in notes)
            prompt_parts.append(f"## 用户笔记\n{notes_text}\n")

        # Scenarios
        prompt_parts.append("## 待评估情景")
        for s in scenarios:
            assumptions = ", ".join(s.get("key_assumptions", []))
            prompt_parts.append(
                f"### {s.get('name', '')}\n"
                f"{s.get('description', '')}\n"
                f"关键假设: {assumptions}\n"
            )

        prompt_parts.append(
            "## 请输出 JSON\n"
            "```json\n"
            '{"scenarios": [\n'
            '  {"name": "情景名", "probability": "low|medium|high",\n'
            '   "price_impact": {"direction": "up|down|flat", "magnitude": "small|medium|large"},\n'
            '   "key_drivers": ["驱动因子1"], "risks": ["风险1"],\n'
            '   "reasoning": "推理说明"}\n'
            "]}\n"
            "```"
        )

        router = self._get_router()
        messages = [
            LLMMessage(role="system", content=_SCENARIO_SYSTEM_PROMPT),
            LLMMessage(role="user", content="\n".join(prompt_parts)),
        ]

        try:
            response = router.complete(
                messages=messages,
                caller="holiday_research.scenarios",
                strategy=RoutingStrategy.QUALITY,
                max_tokens=3072,
                temperature=0.3,
                symbol=symbol,
                analysis_type="holiday_research_scenarios",
            )
            scenario_results = self._parse_scenarios(response.text)
            return {
                "status": "success",
                "symbol": symbol,
                "scenarios": scenario_results,
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "disclaimer": _DISCLAIMER,
            }
        except Exception as exc:
            logger.exception("Scenario analysis failed for %s: %s", symbol, exc)
            return {
                "status": "error",
                "symbol": symbol,
                "scenarios": [],
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "disclaimer": _DISCLAIMER,
            }

    def _parse_scenarios(self, text: str) -> list[dict[str, Any]]:
        """Parse LLM response into scenario results."""
        try:
            cleaned = text.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json", 1)[1]
                cleaned = cleaned.split("```", 1)[0]
            elif "```" in cleaned:
                cleaned = cleaned.split("```", 1)[1]
                cleaned = cleaned.split("```", 1)[0]

            parsed = json.loads(cleaned.strip())
            if isinstance(parsed, dict):
                return parsed.get("scenarios", [])
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, IndexError) as exc:
            logger.debug("Scenario JSON parse failed: %s", exc)
        return []

    # --- Conversation (multi-turn) ---

    def get_conversation(self, symbol: str, holiday_key: str) -> list[dict[str, Any]]:
        """Get conversation history from Redis."""
        r = self._get_redis()
        if r is None:
            return []

        key = f"{self.REDIS_PREFIX}:conversation:{symbol}:{holiday_key}"
        try:
            raw = r.get(key)
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.debug("Redis get conversation failed: %s", exc)
        return []

    def _save_conversation(
        self, symbol: str, holiday_key: str, messages: list[dict[str, Any]]
    ) -> None:
        """Persist conversation history to Redis."""
        r = self._get_redis()
        if r is None:
            return

        key = f"{self.REDIS_PREFIX}:conversation:{symbol}:{holiday_key}"
        try:
            r.set(
                key,
                json.dumps(messages, ensure_ascii=False),
                ex=self.CONVERSATION_TTL,
            )
        except Exception as exc:
            logger.debug("Redis save conversation failed: %s", exc)

    def clear_conversation(self, symbol: str, holiday_key: str) -> bool:
        """Clear conversation history. Returns True if deleted."""
        r = self._get_redis()
        if r is None:
            return False

        key = f"{self.REDIS_PREFIX}:conversation:{symbol}:{holiday_key}"
        try:
            return bool(r.delete(key))
        except Exception as exc:
            logger.debug("Redis clear conversation failed: %s", exc)
            return False

    # --- AI Comprehensive Analysis ---

    def analyze_comprehensive(self, symbol: str, holiday_key: str) -> dict[str, Any]:
        """Run comprehensive AI analysis combining auto context + user notes.

        Returns structured analysis result.
        """
        from src.llm.base import LLMMessage
        from src.llm.router import RoutingStrategy

        context = self.collect_context(symbol)
        user_notes = self.get_user_notes(symbol, holiday_key)
        evidence = self.get_evidence(symbol, holiday_key)

        stock_name = self._get_stock_name(symbol)

        user_prompt = self._build_analysis_prompt(
            symbol, stock_name, context, user_notes, evidence
        )

        router = self._get_router()

        messages = [
            LLMMessage(role="system", content=_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]

        try:
            response = router.complete(
                messages=messages,
                caller="holiday_research.analysis",
                strategy=RoutingStrategy.QUALITY,
                max_tokens=4096,
                temperature=0.3,
                symbol=symbol,
                analysis_type="holiday_research",
            )
            result = self._parse_analysis(response.text, symbol)
            result["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            result["disclaimer"] = _DISCLAIMER
            return result
        except Exception as exc:
            logger.exception("Comprehensive analysis failed for %s: %s", symbol, exc)
            return {
                "status": "error",
                "symbol": symbol,
                "business_factors": [],
                "sector_analysis": {},
                "peer_comparison": {},
                "risk_matrix": [],
                "reopening_strategy": {"action": "watch", "confidence": 0.0},
                "key_watch_items": [],
                "overall_assessment": "分析暂时不可用",
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "disclaimer": _DISCLAIMER,
                "evidence_completeness": 0.0,
                "association_context": "",
            }

    def ask_followup(
        self, symbol: str, holiday_key: str, question: str
    ) -> dict[str, Any]:
        """Answer a follow-up question with multi-turn conversation context.

        Loads conversation history from Redis, appends user question,
        sends to LLM with context, saves assistant reply, and returns
        the full conversation history.
        """
        from src.llm.base import LLMMessage
        from src.llm.router import RoutingStrategy

        now = time.strftime("%Y-%m-%d %H:%M:%S")

        # Load existing conversation
        conversation = self.get_conversation(symbol, holiday_key)

        # Append user message
        conversation.append({"role": "user", "content": question, "timestamp": now})

        # Build context summary (only for the first message or periodically)
        context = self.collect_context(symbol)
        user_notes = self.get_user_notes(symbol, holiday_key)
        evidence = self.get_evidence(symbol, holiday_key)
        stock_name = self._get_stock_name(symbol)

        context_summary = self._build_context_summary(
            symbol, stock_name, context, user_notes, evidence
        )

        # Build LLM messages: system + context + history + current question
        llm_messages = [
            LLMMessage(role="system", content=_CONVERSATION_SYSTEM_PROMPT),
            LLMMessage(role="user", content=f"## 研究上下文\n{context_summary}"),
            LLMMessage(
                role="assistant",
                content="好的，我已了解研究上下文。请开始提问。",
            ),
        ]

        # Add conversation history (limit to recent turns)
        history_to_send = conversation[-(CONVERSATION_MAX_TURNS * 2) :]
        for msg in history_to_send:
            llm_messages.append(LLMMessage(role=msg["role"], content=msg["content"]))

        router = self._get_router()

        try:
            response = router.complete(
                messages=llm_messages,
                caller="holiday_research.qa",
                strategy=RoutingStrategy.QUALITY,
                max_tokens=2048,
                temperature=0.4,
                symbol=symbol,
                analysis_type="holiday_research_qa",
            )
            answer = response.text.strip()

            # Append assistant reply to conversation
            conversation.append(
                {"role": "assistant", "content": answer, "timestamp": now}
            )

            # Persist conversation
            self._save_conversation(symbol, holiday_key, conversation)

            return {
                "status": "success",
                "question": question,
                "answer": answer,
                "generated_at": now,
                "disclaimer": _DISCLAIMER,
                "messages": conversation,
            }
        except Exception as exc:
            logger.exception("Followup failed for %s: %s", symbol, exc)
            # Remove the failed user message from conversation
            if conversation and conversation[-1]["role"] == "user":
                conversation.pop()
            return {
                "status": "error",
                "question": question,
                "answer": "追问服务暂时不可用，请稍后重试。",
                "generated_at": now,
                "disclaimer": _DISCLAIMER,
                "messages": conversation,
            }

    # --- Helpers ---

    def _get_stock_name(self, symbol: str) -> str:
        try:
            detail = self._stock_service.get_stock_detail(symbol)
            if detail:
                return detail.get("name", "")
        except Exception:
            pass
        return ""

    # --- Prompt Building ---

    def _build_analysis_prompt(
        self,
        symbol: str,
        stock_name: str,
        context: dict[str, Any],
        user_notes: list[dict[str, Any]],
        evidence: list[dict[str, Any]] | None = None,
    ) -> str:
        sections = [f"## 分析目标\n{stock_name}（{symbol}）假期深度研究\n"]

        # Real-time quote (prevents price hallucination)
        quote = context.get("quote", {})
        if quote and quote.get("price") is not None:
            sections.append(
                f"## 实时行情\n"
                f"最新价: {quote['price']} | "
                f"涨跌幅: {quote.get('pct_change', 'N/A')}% | "
                f"成交量: {quote.get('volume', 'N/A')} | "
                f"今开: {quote.get('open', 'N/A')} | "
                f"最高: {quote.get('high', 'N/A')} | "
                f"最低: {quote.get('low', 'N/A')}\n"
                f"⚠ 所有价格分析必须基于上述实时数据，严禁凭空猜测价格。\n"
            )
        else:
            sections.append(
                "## 实时行情\n注意：当前无法获取实时行情数据，请勿猜测具体价格。\n"
            )

        # v3.4: Association profile context
        assoc = context.get("association_profile")
        if assoc:
            ip = assoc.get("industry_profile")
            if ip:
                sections.append(
                    f"## 行业关联\n"
                    f"行业: {ip.get('display', '')}\n"
                    f"关键指标: {', '.join(ip.get('key_metrics', []))}\n"
                    f"产业链: {' → '.join(ip.get('value_chain', []))}\n"
                )
            concepts = assoc.get("concepts", [])
            if concepts:
                concept_str = ", ".join(
                    f"{c.get('name', '')}({c.get('pct_change', 0):+.2f}%)"
                    for c in concepts[:8]
                )
                sections.append(f"## 概念板块关联\n{concept_str}\n")
                resonance = assoc.get("resonance_level", "none")
                if resonance != "none":
                    sections.append(f"概念共振: {resonance}\n")
            peers = assoc.get("cross_market_peers", [])
            if peers:
                peer_str = ", ".join(
                    f"{p.get('symbol', '')}({p.get('market', '')})" for p in peers
                )
                sections.append(f"## 跨市场同行\n{peer_str}\n")

        # News
        news = context.get("news", [])
        if news:
            items = "\n".join(
                f"- [{n.get('datetime', '')}] {n.get('title', '')} (来源: {n.get('source', '')})"
                for n in news
            )
            sections.append(f"## 个股新闻 (东方财富, top {len(news)})\n{items}\n")

        # Concepts (raw data, kept for backward compat)
        concepts = context.get("concepts", [])
        if concepts:
            items = "\n".join(
                f"- {c.get('name', '')}: 涨跌 {c.get('pct_change', 0):.2f}%, "
                f"个股排名 {c.get('rank_in_concept', 0)}/{c.get('concept_size', 0)}"
                for c in concepts
            )
            sections.append(f"## 所属概念板块 (top {len(concepts)})\n{items}\n")

        # Global market
        gm = context.get("global_market", {})
        if gm:
            indices = gm.get("indices", [])
            commodities = gm.get("commodities", [])
            idx_text = ", ".join(
                f"{i.get('name', '')}: {i.get('pct_change', 0):.2f}%"
                for i in (indices[:6] if indices else [])
            )
            cmd_text = ", ".join(
                f"{c.get('name', '')}: {c.get('pct_change', 0):.2f}%"
                for c in (commodities[:4] if commodities else [])
            )
            sections.append(f"## 全球市场\n指数: {idx_text}\n商品: {cmd_text}\n")

        # Cross-market
        cm = context.get("cross_market", {})
        if cm:
            sections.append(
                f"## 跨市场同行分析\n{json.dumps(cm, ensure_ascii=False, default=str)[:1000]}\n"
            )

        # Sentiment matches
        matches = context.get("sentiment_matches", [])
        if matches:
            items = "\n".join(
                f"- [{m.get('platform', '')}] {m.get('title', '')} (热度: {m.get('heat_score', 0):.0f})"
                for m in matches
            )
            sections.append(f"## 舆情匹配\n{items}\n")

        # v3.4: Structured evidence
        if evidence:
            evidence_lines = []
            for e in evidence:
                impact_label = _IMPACT_LABELS.get(e.get("impact", ""), "中性")
                conf = e.get("confidence", "medium")
                evidence_lines.append(
                    f"- [{impact_label}|{conf}] {e.get('content', '')} "
                    f"(来源: {e.get('source', '用户')})"
                )
            sections.append("## 结构化证据\n" + "\n".join(evidence_lines) + "\n")

        # User notes
        if user_notes:
            by_type: dict[str, list[str]] = {}
            for note in user_notes:
                label = _NOTE_TYPE_LABELS.get(note.get("note_type", ""), "其他")
                by_type.setdefault(label, []).append(note.get("content", ""))
            notes_text = ""
            for label, contents in by_type.items():
                notes_text += f"\n### {label}\n"
                for c in contents:
                    notes_text += f"- {c}\n"
            sections.append(f"## 用户补充数据{notes_text}")

        # Calendar
        cal = context.get("calendar_info", {})
        if cal:
            sections.append(
                f"## 交易日历\n下一交易日: {cal.get('next_trading_day', 'N/A')}\n"
                f"假期状态: {'是' if cal.get('is_holiday_period') else '否'}\n"
            )

        sections.append(
            "## 请输出 JSON\n"
            "```json\n"
            "{\n"
            '  "business_factors": [{"name": "因子名", "impact": "positive|negative|neutral", "weight": 0.0~1.0, "analysis": "分析说明"}],\n'
            '  "sector_analysis": {"summary": "板块摘要", "key_concepts": ["概念1"], "sector_trend": "bullish|bearish|neutral"},\n'
            '  "peer_comparison": {"summary": "同行对比摘要", "us_peers": [{"name": "...", "change_pct": 0.0}], "hk_peers": [{"name": "...", "change_pct": 0.0}]},\n'
            '  "risk_matrix": [{"risk": "风险描述", "probability": "low|medium|high", "impact": "low|medium|high", "mitigation": "应对措施"}],\n'
            '  "reopening_strategy": {"action": "buy|add|hold|reduce|sell|watch", "confidence": 0.0~1.0, "reasoning": "理由", "target_range": [低, 高], "stop_loss": 止损价},\n'
            '  "key_watch_items": ["复盘后关注事项1", "..."],\n'
            '  "overall_assessment": "综合评估文字",\n'
            '  "evidence_completeness": 0.0,\n'
            '  "association_context": "关联数据如何影响分析的说明"\n'
            "}\n"
            "```"
        )

        return "\n".join(sections)

    def _build_context_summary(
        self,
        symbol: str,
        stock_name: str,
        context: dict[str, Any],
        user_notes: list[dict[str, Any]],
        evidence: list[dict[str, Any]] | None = None,
    ) -> str:
        """Build a concise context summary for follow-up questions."""
        parts = [f"## 研究标的: {stock_name}（{symbol}）\n"]

        # Real-time quote
        quote = context.get("quote", {})
        if quote and quote.get("price") is not None:
            parts.append(
                f"实时行情: 最新价 {quote['price']}, "
                f"涨跌幅 {quote.get('pct_change', 'N/A')}%"
            )
        else:
            parts.append("实时行情: 暂无数据，请勿猜测具体价格")

        # Association profile summary
        assoc = context.get("association_profile")
        if assoc:
            ip = assoc.get("industry_profile")
            if ip:
                parts.append(f"行业: {ip.get('display', '')}")
            concepts = assoc.get("concepts", [])
            if concepts:
                names = ", ".join(c.get("name", "") for c in concepts[:5])
                parts.append(f"概念板块: {names}")
            peers = assoc.get("cross_market_peers", [])
            if peers:
                peer_str = ", ".join(p.get("symbol", "") for p in peers[:5])
                parts.append(f"跨市场同行: {peer_str}")

        news = context.get("news", [])
        if news:
            titles = ", ".join(n.get("title", "")[:30] for n in news[:5])
            parts.append(f"近期新闻: {titles}")

        if evidence:
            evidence_summary = "; ".join(
                e.get("content", "")[:50] for e in evidence[:5]
            )
            parts.append(f"证据: {evidence_summary}")

        if user_notes:
            notes_text = "; ".join(n.get("content", "")[:50] for n in user_notes[:5])
            parts.append(f"用户笔记: {notes_text}")

        return "\n".join(parts)

    def _parse_analysis(self, text: str, symbol: str) -> dict[str, Any]:
        """Parse LLM response into structured analysis result."""
        result: dict[str, Any] = {
            "status": "success",
            "symbol": symbol,
            "business_factors": [],
            "sector_analysis": {},
            "peer_comparison": {},
            "risk_matrix": [],
            "reopening_strategy": {"action": "watch", "confidence": 0.0},
            "key_watch_items": [],
            "overall_assessment": "",
            "evidence_completeness": 0.0,
            "association_context": "",
        }

        # Try to extract JSON from the response
        try:
            # Handle markdown code blocks
            cleaned = text.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json", 1)[1]
                cleaned = cleaned.split("```", 1)[0]
            elif "```" in cleaned:
                cleaned = cleaned.split("```", 1)[1]
                cleaned = cleaned.split("```", 1)[0]

            parsed = json.loads(cleaned.strip())

            if isinstance(parsed, dict):
                for key in (
                    "business_factors",
                    "sector_analysis",
                    "peer_comparison",
                    "risk_matrix",
                    "reopening_strategy",
                    "key_watch_items",
                    "overall_assessment",
                    "evidence_completeness",
                    "association_context",
                ):
                    if key in parsed:
                        result[key] = parsed[key]

        except (json.JSONDecodeError, IndexError) as exc:
            logger.debug("JSON parse failed, using raw text: %s", exc)
            result["overall_assessment"] = text.strip()[:2000]

        return result
