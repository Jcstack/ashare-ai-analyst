"""Historical Analogy Agent — finds historical parallels to current events.

Seeded with 10+ major events. Uses keyword matching + LLM similarity scoring.
Stores discovered analogies in SQLite for future reference.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("intelligence.agents.historical_analogy")


@dataclass
class HistoricalEvent:
    """A known historical event for analogy matching."""

    event_id: str
    name: str
    date: str  # YYYY-MM-DD
    description: str
    keywords: list[str]
    event_type: str
    affected_sectors: list[str]
    market_impact: str  # "crash|correction|rally|rotation|volatile"
    recovery_days: int  # days to recover
    key_lesson: str


@dataclass
class HistoricalAnalogy:
    """A matched analogy between current and historical events."""

    current_event_summary: str
    historical_event: HistoricalEvent
    similarity_score: float  # 0-1
    match_dimensions: list[str]  # which dimensions matched
    llm_analysis: str  # LLM explanation of parallels
    predicted_pattern: str  # what happened historically
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ---------------------------------------------------------------------------
# Seed with 10+ major historical events
# ---------------------------------------------------------------------------
SEEDED_EVENTS: list[HistoricalEvent] = [
    HistoricalEvent(
        event_id="russia_ukraine_2022",
        name="俄乌冲突爆发",
        date="2022-02-24",
        description="Russia invades Ukraine, global energy crisis, commodity surge",
        keywords=[
            "俄罗斯",
            "乌克兰",
            "战争",
            "入侵",
            "制裁",
            "能源危机",
            "天然气",
            "Russia",
            "Ukraine",
            "invasion",
        ],
        event_type="geopolitical_conflict",
        affected_sectors=["军工", "石油", "天然气", "黄金", "农产品", "航运"],
        market_impact="correction",
        recovery_days=45,
        key_lesson="能源供应链冲击传导最快，军工短期涨幅最大但持续性差",
    ),
    HistoricalEvent(
        event_id="iran_israel_2024",
        name="伊朗-以色列直接冲突",
        date="2024-04-13",
        description="Iran launches drone/missile attack on Israel, Middle East escalation",
        keywords=[
            "伊朗",
            "以色列",
            "中东",
            "导弹",
            "无人机",
            "Iran",
            "Israel",
            "Middle East",
            "missile",
        ],
        event_type="geopolitical_escalation",
        affected_sectors=["军工", "石油", "黄金", "航运"],
        market_impact="volatile",
        recovery_days=5,
        key_lesson="直接冲突后市场恐慌1-3天，若不扩大则快速修复",
    ),
    HistoricalEvent(
        event_id="covid_outbreak_2020",
        name="COVID-19全球大流行",
        date="2020-01-23",
        description="COVID-19 pandemic, global lockdowns, supply chain disruption",
        keywords=[
            "疫情",
            "新冠",
            "封城",
            "隔离",
            "COVID",
            "pandemic",
            "lockdown",
            "病毒",
        ],
        event_type="pandemic",
        affected_sectors=[
            "医药",
            "口罩",
            "疫苗",
            "在线教育",
            "远程办公",
            "航空",
            "旅游",
        ],
        market_impact="crash",
        recovery_days=90,
        key_lesson="初期恐慌性下跌，之后流动性驱动V型反转",
    ),
    HistoricalEvent(
        event_id="trade_war_2018",
        name="中美贸易战",
        date="2018-03-22",
        description="US-China trade war, tariff escalation, tech decoupling",
        keywords=[
            "贸易战",
            "关税",
            "加征",
            "301",
            "实体清单",
            "trade war",
            "tariff",
            "decoupling",
        ],
        event_type="trade_conflict",
        affected_sectors=["半导体", "通信", "农业", "稀土", "出口"],
        market_impact="correction",
        recovery_days=180,
        key_lesson="贸易战利好国产替代长线逻辑，短期出口股承压",
    ),
    HistoricalEvent(
        event_id="chatgpt_ai_boom_2023",
        name="ChatGPT引爆AI革命",
        date="2023-01-30",
        description="ChatGPT goes viral, AI investment boom, compute demand surge",
        keywords=[
            "ChatGPT",
            "AI",
            "人工智能",
            "大模型",
            "算力",
            "GPU",
            "NVIDIA",
            "OpenAI",
        ],
        event_type="tech_revolution",
        affected_sectors=["AI芯片", "光模块", "服务器", "IDC", "电力", "液冷"],
        market_impact="rally",
        recovery_days=0,
        key_lesson="AI算力需求→芯片→光模块→IDC→电力的传导链，最先涨算力最后涨电力",
    ),
    HistoricalEvent(
        event_id="a_share_crash_2015",
        name="2015年A股股灾",
        date="2015-06-12",
        description="A-share bubble burst, margin call cascade, circuit breakers",
        keywords=[
            "股灾",
            "熔断",
            "去杠杆",
            "融资融券",
            "crash",
            "circuit breaker",
            "margin call",
        ],
        event_type="market_crash",
        affected_sectors=["券商", "银行", "保险"],
        market_impact="crash",
        recovery_days=365,
        key_lesson="杠杆牛市崩塌后监管政策密集出台，底部需要时间确认",
    ),
    HistoricalEvent(
        event_id="fed_hiking_2022",
        name="美联储激进加息",
        date="2022-03-16",
        description="Fed aggressive rate hikes, USD strength, EM capital outflow",
        keywords=[
            "加息",
            "美联储",
            "利率",
            "缩表",
            "Fed",
            "rate hike",
            "tightening",
            "hawkish",
        ],
        event_type="monetary_tightening",
        affected_sectors=["银行", "地产", "科技", "黄金"],
        market_impact="correction",
        recovery_days=120,
        key_lesson="加息周期利空高估值成长股，利好银行；加息末期黄金走强",
    ),
    HistoricalEvent(
        event_id="education_crackdown_2021",
        name="教育双减政策",
        date="2021-07-24",
        description="China education industry crackdown, regulatory storm",
        keywords=[
            "双减",
            "教育",
            "监管",
            "整顿",
            "反垄断",
            "education",
            "crackdown",
            "regulation",
        ],
        event_type="regulatory_storm",
        affected_sectors=["教育", "互联网", "游戏", "医疗"],
        market_impact="crash",
        recovery_days=180,
        key_lesson="政策性打压行业毁灭性，需要等政策底确认后才能入场",
    ),
    HistoricalEvent(
        event_id="japan_carry_trade_2024",
        name="日元套利交易平仓",
        date="2024-08-05",
        description="BOJ rate hike triggers yen carry trade unwind, global risk-off",
        keywords=[
            "日元",
            "套利",
            "BOJ",
            "carry trade",
            "日本央行",
            "yen",
            "unwind",
        ],
        event_type="financial_contagion",
        affected_sectors=["券商", "银行", "科技"],
        market_impact="volatile",
        recovery_days=14,
        key_lesson="外部流动性冲击A股影响有限，北向资金波动是信号",
    ),
    HistoricalEvent(
        event_id="opec_price_war_2020",
        name="OPEC+价格战",
        date="2020-03-06",
        description="Saudi-Russia oil price war, crude oil crash",
        keywords=[
            "OPEC",
            "石油",
            "油价",
            "减产",
            "价格战",
            "oil",
            "crude",
            "Saudi",
        ],
        event_type="commodity_shock",
        affected_sectors=["石油", "石化", "航空", "化工"],
        market_impact="crash",
        recovery_days=60,
        key_lesson="油价暴跌利好航空化工，利空油气开采，传导需要1-2周",
    ),
]


# ---------------------------------------------------------------------------
# SQLite persistence
# ---------------------------------------------------------------------------
class HistoricalAnalogyStore:
    """SQLite persistence for historical analogies."""

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            from src.utils.config import get_project_root

            db_path = str(get_project_root() / "data" / "historical_analogies.db")
        self._db_path = db_path
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _ensure_schema(self) -> None:
        try:
            conn = self._get_conn()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS analogies (
                    id TEXT PRIMARY KEY,
                    current_event TEXT NOT NULL,
                    historical_event_id TEXT NOT NULL,
                    similarity_score REAL NOT NULL,
                    match_dimensions TEXT NOT NULL,
                    llm_analysis TEXT,
                    predicted_pattern TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS custom_events (
                    event_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    date TEXT NOT NULL,
                    description TEXT NOT NULL,
                    keywords TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    affected_sectors TEXT NOT NULL,
                    market_impact TEXT NOT NULL,
                    recovery_days INTEGER NOT NULL,
                    key_lesson TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_analogies_created "
                "ON analogies(created_at)"
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.error("Failed to init historical analogy schema: %s", exc)

    def save_analogy(self, analogy: HistoricalAnalogy) -> str:
        aid = hashlib.md5(
            f"{analogy.current_event_summary}:{analogy.historical_event.event_id}".encode()
        ).hexdigest()[:12]
        try:
            conn = self._get_conn()
            conn.execute(
                "INSERT OR REPLACE INTO analogies VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    aid,
                    analogy.current_event_summary,
                    analogy.historical_event.event_id,
                    analogy.similarity_score,
                    json.dumps(analogy.match_dimensions, ensure_ascii=False),
                    analogy.llm_analysis,
                    analogy.predicted_pattern,
                    analogy.created_at,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning("Failed to save analogy %s: %s", aid, exc)
        return aid

    def save_custom_event(self, event: HistoricalEvent) -> None:
        try:
            conn = self._get_conn()
            conn.execute(
                "INSERT OR REPLACE INTO custom_events VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.name,
                    event.date,
                    event.description,
                    json.dumps(event.keywords, ensure_ascii=False),
                    event.event_type,
                    json.dumps(event.affected_sectors, ensure_ascii=False),
                    event.market_impact,
                    event.recovery_days,
                    event.key_lesson,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning("Failed to save custom event %s: %s", event.event_id, exc)

    def load_custom_events(self) -> list[HistoricalEvent]:
        try:
            conn = self._get_conn()
            rows = conn.execute("SELECT * FROM custom_events").fetchall()
            conn.close()
        except Exception as exc:
            logger.error("Failed to load custom events: %s", exc)
            return []

        events = []
        for row in rows:
            events.append(
                HistoricalEvent(
                    event_id=row[0],
                    name=row[1],
                    date=row[2],
                    description=row[3],
                    keywords=json.loads(row[4]),
                    event_type=row[5],
                    affected_sectors=json.loads(row[6]),
                    market_impact=row[7],
                    recovery_days=row[8],
                    key_lesson=row[9],
                )
            )
        return events

    def get_recent_analogies(self, limit: int = 20) -> list[dict[str, Any]]:
        try:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM analogies ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            conn.close()
        except Exception as exc:
            logger.error("Failed to get recent analogies: %s", exc)
            return []

        return [
            {
                "id": r[0],
                "current_event": r[1],
                "historical_event_id": r[2],
                "similarity_score": r[3],
                "match_dimensions": json.loads(r[4]),
                "llm_analysis": r[5],
                "predicted_pattern": r[6],
                "created_at": r[7],
            }
            for r in rows
        ]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
class HistoricalAnalogyAgent:
    """Analyst team: finds historical parallels to current events."""

    def __init__(
        self,
        event_bus: Any,
        llm_router: Any,
        store: HistoricalAnalogyStore | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._llm_router = llm_router
        self._store = store or HistoricalAnalogyStore()
        self._events: list[HistoricalEvent] = (
            list(SEEDED_EVENTS) + self._store.load_custom_events()
        )
        logger.info(
            "HistoricalAnalogyAgent initialized with %d events", len(self._events)
        )

    async def find_analogies(
        self, event_understanding: dict[str, Any]
    ) -> list[HistoricalAnalogy]:
        """Find historical parallels for an understood event.

        Args:
            event_understanding: Output from EventUnderstandingAgent containing
                one_line_summary, event_type, key_sectors, entities, etc.

        Returns:
            Up to 3 best-matching HistoricalAnalogy objects.
        """
        summary = event_understanding.get("one_line_summary", "")
        keywords_in_event: set[str] = set()
        for field_val in [summary, event_understanding.get("entities", [])]:
            if isinstance(field_val, str):
                keywords_in_event.add(field_val.lower())
            elif isinstance(field_val, list):
                keywords_in_event.update(s.lower() for s in field_val)

        # Score all historical events
        candidates: list[tuple[HistoricalEvent, float, list[str]]] = []
        for hist in self._events:
            score, dimensions = self._compute_similarity(
                event_understanding, hist, keywords_in_event
            )
            if score > 0.3:
                candidates.append((hist, score, dimensions))

        candidates.sort(key=lambda x: x[1], reverse=True)
        top = candidates[:3]

        # LLM-enrich top candidates
        analogies: list[HistoricalAnalogy] = []
        for hist, score, dimensions in top:
            analysis = await self._llm_analyze_parallel(event_understanding, hist)
            analogy = HistoricalAnalogy(
                current_event_summary=summary,
                historical_event=hist,
                similarity_score=score,
                match_dimensions=dimensions,
                llm_analysis=analysis.get("analysis", ""),
                predicted_pattern=analysis.get("predicted_pattern", hist.key_lesson),
            )
            self._store.save_analogy(analogy)
            analogies.append(analogy)

            # Publish to event bus
            await self._event_bus.publish(
                "analyst:historical_analogy",
                {
                    "current_event": summary,
                    "historical_event": hist.name,
                    "similarity_score": score,
                    "match_dimensions": dimensions,
                    "predicted_pattern": analogy.predicted_pattern,
                    "historical_recovery_days": hist.recovery_days,
                    "historical_impact": hist.market_impact,
                },
            )

        logger.info("Found %d analogies for: %s", len(analogies), summary[:60])
        return analogies

    # ------------------------------------------------------------------
    # Similarity scoring
    # ------------------------------------------------------------------
    def _compute_similarity(
        self,
        event: dict[str, Any],
        hist: HistoricalEvent,
        keywords_in_event: set[str],
    ) -> tuple[float, list[str]]:
        """Multi-dimensional similarity scoring."""
        score = 0.0
        dimensions: list[str] = []

        # 1. Keyword overlap (0.4 weight)
        hist_keywords = set(k.lower() for k in hist.keywords)
        overlap = keywords_in_event & hist_keywords
        if overlap:
            keyword_score = min(len(overlap) / max(len(hist_keywords), 1), 1.0)
            score += 0.4 * keyword_score
            dimensions.append(f"keywords({len(overlap)})")

        # 2. Event type match (0.25 weight)
        event_type = event.get("event_type", "")
        type_mapping: dict[str, list[str]] = {
            "ceasefire": ["geopolitical_conflict", "geopolitical_escalation"],
            "escalation": ["geopolitical_conflict", "geopolitical_escalation"],
            "product_launch": ["tech_revolution"],
            "policy_change": ["regulatory_storm", "monetary_tightening"],
            "data_release": ["monetary_tightening"],
            "disaster": ["pandemic"],
            "trade_conflict": ["trade_conflict"],
            "commodity_shock": ["commodity_shock"],
        }
        related_types = type_mapping.get(event_type, [])
        if hist.event_type in related_types or hist.event_type == event_type:
            score += 0.25
            dimensions.append("event_type")

        # 3. Sector overlap (0.2 weight)
        event_sectors = set(event.get("key_sectors", []))
        hist_sectors = set(hist.affected_sectors)
        sector_overlap = event_sectors & hist_sectors
        if sector_overlap:
            sector_score = min(len(sector_overlap) / max(len(hist_sectors), 1), 1.0)
            score += 0.2 * sector_score
            dimensions.append(f"sectors({len(sector_overlap)})")

        # 4. Domain overlap (0.15 weight)
        event_domains = set(event.get("affected_domains", []))
        domain_type_map: dict[str, list[str]] = {
            "geopolitics": ["geopolitical_conflict", "geopolitical_escalation"],
            "energy": ["commodity_shock"],
            "tech": ["tech_revolution"],
            "finance": ["financial_contagion", "market_crash"],
            "trade": ["trade_conflict"],
        }
        for domain in event_domains:
            if hist.event_type in domain_type_map.get(domain, []):
                score += 0.15
                dimensions.append(f"domain({domain})")
                break

        return round(score, 3), dimensions

    # ------------------------------------------------------------------
    # LLM analysis
    # ------------------------------------------------------------------
    async def _llm_analyze_parallel(
        self, event: dict[str, Any], hist: HistoricalEvent
    ) -> dict[str, Any]:
        """Use LLM to analyze historical parallel in depth."""
        prompt = (
            "Analyze the similarity between a current event and a historical event, "
            "and predict likely market trajectory.\n\n"
            f"Current event: {event.get('one_line_summary', '')}\n"
            f"- Type: {event.get('event_type', '')}\n"
            f"- Sectors involved: {', '.join(event.get('key_sectors', []))}\n"
            f"- Certainty: {event.get('certainty', 'N/A')}\n"
            f"- Reversal risk: {event.get('reversal_risk', 'N/A')}\n\n"
            f"Historical event: {hist.name} ({hist.date})\n"
            f"- Description: {hist.description}\n"
            f"- Affected sectors: {', '.join(hist.affected_sectors)}\n"
            f"- Market impact: {hist.market_impact}\n"
            f"- Recovery days: {hist.recovery_days}\n"
            f"- Key lesson: {hist.key_lesson}\n\n"
            "Output JSON (all text values in Chinese):\n"
            "{\n"
            '  "analysis": "2-3 sentences analyzing similarities and differences (Chinese)",\n'
            '  "predicted_pattern": "predicted market trajectory and timeframe based on history (Chinese)",\n'
            '  "key_difference": "biggest difference between current and historical event (Chinese)",\n'
            '  "actionable_insight": "one-line investment advice (Chinese)"\n'
            "}"
        )

        try:
            from src.llm.base import LLMMessage

            response = self._llm_router.complete(
                messages=[
                    LLMMessage(
                        role="system",
                        content="You are a financial history analysis expert. "
                        "Output strict JSON. All text values must be in Chinese.",
                    ),
                    LLMMessage(role="user", content=prompt),
                ],
                max_tokens=500,
                temperature=0.3,
            )
            text = response.text if hasattr(response, "text") else str(response)
            return json.loads(text) if isinstance(text, str) else text
        except Exception as exc:
            logger.warning("LLM analogy analysis failed: %s", exc)
            return {
                "analysis": f"当前事件与{hist.name}有结构性相似",
                "predicted_pattern": hist.key_lesson,
            }


# ---------------------------------------------------------------------------
# DI singletons
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_historical_analogy_store() -> HistoricalAnalogyStore:
    return HistoricalAnalogyStore()


@lru_cache(maxsize=1)
def get_historical_analogy_agent() -> HistoricalAnalogyAgent:
    from src.intelligence.event_bus import EventBus
    from src.web.dependencies import get_llm_router

    return HistoricalAnalogyAgent(
        event_bus=EventBus(),
        llm_router=get_llm_router(),
        store=get_historical_analogy_store(),
    )
