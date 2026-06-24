"""Event Understanding Agent — Analyst Team member for LLM semantic analysis.

Uses LLM to deeply understand events: type, entities, sentiment, certainty,
reversal risk, A-share relevance, and affected sectors.

Replaces keyword-based sentiment classification with semantic understanding.

Per PRD v39.0 FR-GIT006.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from functools import lru_cache

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("intelligence.agents.event_understanding")


@dataclass
class EventUnderstanding:
    """Structured understanding of a news event."""

    event_type: str = ""  # ceasefire|escalation|product_launch|policy_change|...
    entities: list[str] = field(default_factory=list)
    affected_domains: list[str] = field(default_factory=list)
    sentiment: str = "neutral"  # positive|negative|mixed
    certainty: float = 0.5  # 0-1
    reversal_risk: str = "medium"  # high|medium|low
    reversal_scenario: str = ""
    a_share_relevance: float = 0.0  # 0-1
    key_sectors: list[str] = field(default_factory=list)
    time_horizon: str = "1-3d"  # immediate|1-3d|1-2w|1-3m
    one_line_summary: str = ""
    source_title: str = ""
    source_url: str = ""
    source_layer: str = "L4"
    analyzed_at: str = ""
    model_used: str = ""
    # v54: Source attention weighting (BlackRock BGRI pattern)
    source_weight: float = 1.0  # L1=3.0, L2=2.0, L3=1.0, L4=0.5, L5=0.3
    # v54: Stock impact extraction (auto-KG population)
    stock_impacts: list[dict[str, str]] = field(default_factory=list)
    # [{symbol, name, direction}]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "entities": self.entities,
            "affected_domains": self.affected_domains,
            "sentiment": self.sentiment,
            "certainty": self.certainty,
            "reversal_risk": self.reversal_risk,
            "reversal_scenario": self.reversal_scenario,
            "a_share_relevance": self.a_share_relevance,
            "key_sectors": self.key_sectors,
            "time_horizon": self.time_horizon,
            "one_line_summary": self.one_line_summary,
            "source_title": self.source_title,
            "source_url": self.source_url,
            "source_layer": self.source_layer,
            "analyzed_at": self.analyzed_at,
            "model_used": self.model_used,
            "source_weight": self.source_weight,
            "stock_impacts": self.stock_impacts,
        }


UNDERSTANDING_SYSTEM_PROMPT = """\
你是全球事件分析专家，专门评估事件对A股市场的影响。

## 评分标准（必须严格遵守）
certainty（事件确定性）:
- 0.8-1.0: 官方声明/已发生的事实
- 0.6-0.8: 多家独立媒体确认
- 0.3-0.6: 单一来源报道
- 0.1-0.3: 市场传闻/自媒体

a_share_relevance（A股关联度）:
- 0.8-1.0: 直接影响A股特定板块（如央行降准→银行股）
- 0.4-0.8: 间接影响（如美联储加息→人民币汇率→北向资金）
- 0.0-0.4: 无明确传导路径

reversal_risk（事件反转概率）:
- high: 事件处于早期，可能被否认/逆转（如和谈传闻、政策征求意见稿）
- medium: 事件基本确认但仍有变数
- low: 既成事实，不可逆转

## 约束
- key_sectors 只列A股板块中文名（军工/石油/黄金/半导体/银行/新能源等）
- one_line_summary 中文，50字以内
- 不确定的领域标低分，不要为了显得有用而虚高评分
- 输出严格 JSON，无附加文本"""

UNDERSTANDING_PROMPT_TEMPLATE = """\
## 待分析事件
标题: {title}
摘要: {summary}
来源层级: {layer}（T1=官方/主流, T2=专业媒体, T3=自媒体/论坛）

## 输出 JSON（所有文本用中文）
{{
  "event_type": "ceasefire|escalation|product_launch|policy_change|data_release|earnings|disaster|tech_breakthrough|regulatory|trade|monetary|market_move",
  "entities": ["相关实体1", "相关实体2"],
  "affected_domains": ["geopolitics", "energy", "tech", "finance", "trade", "regulatory", "monetary", "industry", "disaster"],
  "sentiment": "positive|negative|mixed",
  "certainty": 0.0-1.0,
  "reversal_risk": "high|medium|low",
  "reversal_scenario": "可能的反转情景（一句话中文）",
  "a_share_relevance": 0.0-1.0,
  "key_sectors": ["受影响A股板块（中文）"],
  "time_horizon": "immediate|1-3d|1-2w|1-3m",
  "one_line_summary": "50字以内的中文摘要",
  "already_priced_in": "是否已被市场消化: yes|partial|no",
  "stock_impacts": [{{"symbol": "6位股票代码", "name": "公司简称", "direction": "positive|negative|neutral"}}]
}}
注意: stock_impacts 只列能明确关联到具体A股代码的影响，不确定的不要列。无则返回空数组。"""


class EventUnderstandingAgent:
    """Analyst team: LLM-based semantic event understanding.

    Analyzes news items using LLM to extract structured event
    understanding including type, entities, A-share relevance,
    and reversal risk assessment.
    """

    # Source attention weights (BlackRock BGRI pattern)
    _DEFAULT_SOURCE_WEIGHTS: dict[str, float] = {
        "L1": 3.0,  # Official (CSRC, PBOC, Fed)
        "L2": 2.0,  # Professional (broker research, EIA)
        "L3": 1.0,  # Quality media (BBC, FT, SCMP)
        "L4": 0.5,  # Aggregators (RSS, reposts)
        "L5": 0.3,  # Social (Weibo, Guba)
    }

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        llm_router: Any | None = None,
        knowledge_graph: Any | None = None,
    ) -> None:
        self._config = config or self._load_config()
        self._llm_router = llm_router
        self._kg = knowledge_graph
        analyst_cfg = self._config.get("analyst", {}).get("event_understanding", {})
        self._score_threshold = analyst_cfg.get("score_threshold", 40)
        self._relevance_threshold = analyst_cfg.get("relevance_threshold", 0.3)
        self._max_calls = analyst_cfg.get("max_llm_calls_per_cycle", 20)
        self._batch_size = analyst_cfg.get("batch_size", 5)
        # Model routing now handled by LLMGateway caller_model_map (config/llm.yaml)
        # Source weights from config or defaults
        self._source_weights = self._config.get(
            "source_weights", self._DEFAULT_SOURCE_WEIGHTS
        )
        self._call_count = 0
        logger.info("EventUnderstandingAgent initialized")

    @staticmethod
    def _load_config() -> dict[str, Any]:
        try:
            return load_config("global_intelligence")
        except FileNotFoundError:
            return {}

    def analyze_item(
        self,
        title: str,
        summary: str = "",
        layer: str = "L4",
        url: str = "",
    ) -> EventUnderstanding | None:
        """Analyze a single news item.

        Args:
            title: News headline.
            summary: News summary/body text.
            layer: Source credibility layer (L1-L5).
            url: Source URL.

        Returns:
            EventUnderstanding or None if LLM call fails or budget exceeded.
        """
        if not self._llm_router:
            logger.warning("No LLM router configured")
            return None

        if self._call_count >= self._max_calls:
            logger.debug(
                "LLM call budget exceeded (%d/%d)", self._call_count, self._max_calls
            )
            return None

        prompt = UNDERSTANDING_PROMPT_TEMPLATE.format(
            title=title,
            summary=summary[:500] if summary else "(无摘要)",
            layer=layer,
        )

        try:
            from src.llm.base import LLMMessage

            messages = [
                LLMMessage(role="system", content=UNDERSTANDING_SYSTEM_PROMPT),
                LLMMessage(role="user", content=prompt),
            ]

            # Routing handled by LLMGateway caller_model_map:
            # "event_understanding" → "deepseek:deepseek-chat" (config/llm.yaml)
            llm_response = self._llm_router.complete(
                messages=messages,
                caller="event_understanding",
                max_tokens=500,
            )
            response = llm_response.text
            self._call_count += 1

            understanding = self._parse_response(
                response, title, url, layer, llm_response.model
            )
            if understanding:
                # v54: Apply source attention weight
                understanding.source_weight = self._source_weights.get(layer, 1.0)

                # v54: Populate knowledge graph
                self._populate_knowledge_graph(understanding)

                logger.debug(
                    "Analyzed: %s → type=%s, relevance=%.2f, sectors=%s, weight=%.1f",
                    title[:40],
                    understanding.event_type,
                    understanding.a_share_relevance,
                    understanding.key_sectors,
                    understanding.source_weight,
                )
            return understanding

        except Exception as exc:
            logger.warning("Event understanding failed for '%s': %s", title[:40], exc)
            self._call_count += 1
            return None

    def analyze_batch(
        self,
        items: list[dict[str, Any]],
    ) -> list[EventUnderstanding]:
        """Analyze a batch of news items with tiered processing.

        Tier 1 (L1/L2): Individual analysis with Claude Sonnet
        Tier 2 (L3): Individual analysis with Gemini Flash
        Tier 3 (L4/L5): Only analyze if title seems significant

        Args:
            items: List of dicts with keys: title, summary, layer, url

        Returns:
            List of EventUnderstanding (only items with relevance > threshold).
        """
        results: list[EventUnderstanding] = []
        self._call_count = 0  # Reset per batch

        # Sort by priority
        tier1 = [i for i in items if i.get("layer", "L4") in ("L1", "L2")]
        tier2 = [i for i in items if i.get("layer", "L4") == "L3"]
        tier3 = [i for i in items if i.get("layer", "L4") in ("L4", "L5")]

        # Tier 1: Full analysis
        for item in tier1:
            u = self.analyze_item(
                title=item.get("title", ""),
                summary=item.get("summary", ""),
                layer=item.get("layer", "L1"),
                url=item.get("url", ""),
            )
            if u and u.a_share_relevance >= self._relevance_threshold:
                results.append(u)

        # Tier 2: Full analysis
        for item in tier2:
            u = self.analyze_item(
                title=item.get("title", ""),
                summary=item.get("summary", ""),
                layer=item.get("layer", "L3"),
                url=item.get("url", ""),
            )
            if u and u.a_share_relevance >= self._relevance_threshold:
                results.append(u)

        # Tier 3: Only analyze items with potentially relevant titles
        for item in tier3:
            title = item.get("title", "")
            if self._quick_relevance_check(title):
                u = self.analyze_item(
                    title=title,
                    summary=item.get("summary", ""),
                    layer=item.get("layer", "L4"),
                    url=item.get("url", ""),
                )
                if u and u.a_share_relevance >= self._relevance_threshold:
                    results.append(u)

        logger.info(
            "Batch analysis: %d items → %d relevant (used %d/%d LLM calls)",
            len(items),
            len(results),
            self._call_count,
            self._max_calls,
        )
        return results

    def _parse_response(
        self,
        response: str | Any,
        title: str,
        url: str,
        layer: str,
        model: str,
    ) -> EventUnderstanding | None:
        """Parse LLM response into EventUnderstanding."""
        text = str(response)

        # Extract JSON from response
        try:
            # Try direct parse first
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON in response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    data = json.loads(text[start:end])
                except json.JSONDecodeError:
                    logger.warning("Failed to parse LLM response as JSON")
                    return None
            else:
                return None

        try:
            return EventUnderstanding(
                event_type=data.get("event_type", "unknown"),
                entities=data.get("entities", []),
                affected_domains=data.get("affected_domains", []),
                sentiment=data.get("sentiment", "neutral"),
                certainty=float(data.get("certainty", 0.5)),
                reversal_risk=data.get("reversal_risk", "medium"),
                reversal_scenario=data.get("reversal_scenario", ""),
                a_share_relevance=float(data.get("a_share_relevance", 0.0)),
                key_sectors=data.get("key_sectors", []),
                time_horizon=data.get("time_horizon", "1-3d"),
                one_line_summary=data.get("one_line_summary", title[:50]),
                source_title=title,
                source_url=url,
                source_layer=layer,
                analyzed_at=datetime.now(UTC).isoformat(),
                model_used=model,
                stock_impacts=data.get("stock_impacts", []),
            )
        except (TypeError, ValueError) as exc:
            logger.warning("Failed to construct EventUnderstanding: %s", exc)
            return None

    @staticmethod
    def _quick_relevance_check(title: str) -> bool:
        """Quick keyword check to filter L4/L5 items before LLM call."""
        relevance_keywords = [
            # Geopolitics
            "战争",
            "冲突",
            "制裁",
            "停火",
            "关税",
            "贸易战",
            "Iran",
            "Russia",
            "China",
            "Taiwan",
            "tariff",
            # Markets
            "央行",
            "降息",
            "加息",
            "降准",
            "美联储",
            "Fed",
            "CPI",
            "PMI",
            "GDP",
            "非农",
            # Tech
            "AI",
            "芯片",
            "半导体",
            "算力",
            "大模型",
            # Energy
            "原油",
            "油价",
            "OPEC",
            "天然气",
            # A-share specific
            "A股",
            "沪深",
            "创业板",
            "科创板",
            "北向",
            # Policy
            "房地产",
            "新能源",
            "碳中和",
            "双碳",
        ]
        title_lower = title.lower()
        return any(kw.lower() in title_lower for kw in relevance_keywords)

    def _populate_knowledge_graph(self, understanding: EventUnderstanding) -> None:
        """Auto-populate KnowledgeGraph from LLM extraction results.

        Connections C1+C8: Entity linking + automated relationship discovery.
        Creates event node, links to sectors, and links to specific stocks
        if the LLM identified stock_impacts.
        """
        if self._kg is None:
            return

        try:
            import hashlib

            event_id = hashlib.md5(understanding.source_title.encode()).hexdigest()[:16]

            # Normalized confidence = certainty × source_weight (capped at 1.0)
            weight_factor = min(understanding.source_weight / 3.0, 1.0)
            confidence = understanding.certainty * weight_factor

            # Add event node
            self._kg.add_event(
                event_id,
                title=understanding.one_line_summary or understanding.source_title[:50],
                event_type=understanding.event_type,
                severity=understanding.a_share_relevance,
            )

            # Link event → sectors
            for sector in understanding.key_sectors:
                self._kg.add_sector(sector, name=sector)
                self._kg.add_edge(
                    event_id,
                    sector,
                    relation="impacts_sector",
                    confidence=confidence,
                )

            # Link stocks → event (from LLM stock_impacts extraction)
            for impact in understanding.stock_impacts:
                symbol = impact.get("symbol", "")
                if symbol and len(symbol) == 6 and symbol.isdigit():
                    self._kg.add_stock(symbol, name=impact.get("name", ""))
                    self._kg.add_edge(
                        symbol,
                        event_id,
                        relation="affected_by",
                        confidence=confidence,
                    )

            logger.debug(
                "KG populated: event=%s, sectors=%d, stocks=%d",
                event_id,
                len(understanding.key_sectors),
                len(understanding.stock_impacts),
            )

        except Exception as exc:
            logger.debug("KG population failed: %s", exc)

    def reset_budget(self) -> None:
        """Reset the LLM call budget for a new cycle."""
        self._call_count = 0


# ---------------------------------------------------------------------------
# DI singleton
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_event_understanding_agent() -> EventUnderstandingAgent:
    from src.web.dependencies import get_llm_gateway

    # v54: Inject KnowledgeGraph for auto-population
    kg = None
    try:
        from src.web.dependencies import get_knowledge_graph

        kg = get_knowledge_graph()
    except Exception:
        pass

    return EventUnderstandingAgent(
        config=load_config("global_intelligence"),
        llm_router=get_llm_gateway(),
        knowledge_graph=kg,
    )
