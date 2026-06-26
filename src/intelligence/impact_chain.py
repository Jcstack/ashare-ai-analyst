"""Impact Chain Engine — builds event-to-asset transmission chains.

Per PRD v34.0 FR-GI002: maps macro events to affected sectors and stocks using
hand-authored, keyword-matched transmission **templates** (a curated rule base).
These are domain-knowledge templates, NOT statistically inferred causality — the
edge confidences are fixed constants, not estimated from data.

Example chain:
  中东战争 → 原油↑ → 航运成本↑ → 航运股↓
                   → 避险情绪↑ → 黄金↑ → 黄金股↑
                   → 通胀预期↑ → 美联储推迟降息
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.utils.config import load_config

logger = logging.getLogger(__name__)


@dataclass
class TransmissionPath:
    """A single cause-effect link in the impact chain."""

    cause: str
    effect: str
    direction: str  # "positive" | "negative"
    magnitude: str  # "strong" | "moderate" | "weak"
    affected_sectors: list[str] = field(default_factory=list)
    affected_stocks: list[str] = field(default_factory=list)
    lag: str = "immediate"  # "immediate" | "1-3d" | "1-2w" | "1-3m"

    def to_dict(self) -> dict[str, Any]:
        return {
            "cause": self.cause,
            "effect": self.effect,
            "direction": self.direction,
            "magnitude": self.magnitude,
            "affected_sectors": self.affected_sectors,
            "affected_stocks": self.affected_stocks,
            "lag": self.lag,
        }


@dataclass
class ImpactChain:
    """Complete impact chain from a trigger event."""

    chain_id: str
    trigger_event: str
    trigger_type: str  # "geopolitical" | "monetary" | "commodity" | "regulatory"
    timestamp: datetime
    transmission_paths: list[TransmissionPath] = field(default_factory=list)
    confidence: float = 0.5
    time_horizon: str = "short_term"
    historical_analogies: list[str] = field(default_factory=list)
    source: str = "template"  # "template" | "llm" | "hybrid"

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "trigger_event": self.trigger_event,
            "trigger_type": self.trigger_type,
            "timestamp": self.timestamp.isoformat(),
            "transmission_paths": [p.to_dict() for p in self.transmission_paths],
            "confidence": self.confidence,
            "time_horizon": self.time_horizon,
            "historical_analogies": self.historical_analogies,
            "source": self.source,
        }

    @property
    def all_affected_sectors(self) -> list[str]:
        sectors = []
        for p in self.transmission_paths:
            sectors.extend(p.affected_sectors)
        return list(dict.fromkeys(sectors))  # dedupe preserving order

    @property
    def all_affected_stocks(self) -> list[str]:
        stocks = []
        for p in self.transmission_paths:
            stocks.extend(p.affected_stocks)
        return list(dict.fromkeys(stocks))

    def get_stock_impact(self, symbol: str) -> str | None:
        """Get impact direction for a specific stock code."""
        for p in self.transmission_paths:
            if symbol in p.affected_stocks:
                return p.direction
        return None


# ---------------------------------------------------------------------------
# Template-based chain construction (rule engine, no LLM needed)
# ---------------------------------------------------------------------------

# Pre-built impact chain templates for common macro events
CHAIN_TEMPLATES: dict[str, dict[str, Any]] = {
    "oil_surge": {
        "trigger_type": "commodity",
        "paths": [
            {
                "cause": "原油价格大涨",
                "effect": "航运成本上升",
                "direction": "negative",
                "magnitude": "moderate",
                "affected_sectors": ["航运", "物流"],
                "affected_stocks": ["601919", "601872"],  # 中远海控, 招商轮船
                "lag": "1-3d",
            },
            {
                "cause": "原油价格大涨",
                "effect": "化工原材料成本上升",
                "direction": "negative",
                "magnitude": "moderate",
                "affected_sectors": ["化工"],
                "affected_stocks": ["600309"],  # 万华化学
                "lag": "1-3d",
            },
            {
                "cause": "原油价格大涨",
                "effect": "炼化利润空间扩大",
                "direction": "positive",
                "magnitude": "moderate",
                "affected_sectors": ["炼化", "石油"],
                "affected_stocks": ["600028", "601857"],  # 中国石化, 中国石油
                "lag": "immediate",
            },
            {
                "cause": "原油价格大涨",
                "effect": "新能源替代预期增强",
                "direction": "positive",
                "magnitude": "weak",
                "affected_sectors": ["光伏", "风电", "新能源"],
                "affected_stocks": ["601012"],  # 隆基绿能
                "lag": "1-2w",
            },
        ],
    },
    "usd_strengthen": {
        "trigger_type": "monetary",
        "paths": [
            {
                "cause": "美元走强",
                "effect": "黄金承压",
                "direction": "negative",
                "magnitude": "strong",
                "affected_sectors": ["黄金", "贵金属"],
                "affected_stocks": ["002155", "600489", "600547"],
                "lag": "immediate",
            },
            {
                "cause": "美元走强",
                "effect": "人民币贬值压力",
                "direction": "negative",
                "magnitude": "moderate",
                "affected_sectors": ["航空", "造纸"],
                "affected_stocks": ["600115", "601111"],  # 东方航空, 中国国航
                "lag": "1-3d",
            },
            {
                "cause": "美元走强",
                "effect": "出口企业受益",
                "direction": "positive",
                "magnitude": "moderate",
                "affected_sectors": ["纺织服装", "家电", "电子"],
                "affected_stocks": ["000726", "600398"],  # 鲁泰纺织, 海澜之家
                "lag": "1-3d",
            },
            {
                "cause": "美元走强",
                "effect": "外资流出风险",
                "direction": "negative",
                "magnitude": "moderate",
                "affected_sectors": ["大盘蓝筹", "外资重仓"],
                "affected_stocks": ["600519", "000858"],  # 贵州茅台, 五粮液
                "lag": "1-3d",
            },
        ],
    },
    "usd_weaken": {
        "trigger_type": "monetary",
        "paths": [
            {
                "cause": "美元走弱",
                "effect": "黄金上涨",
                "direction": "positive",
                "magnitude": "strong",
                "affected_sectors": ["黄金", "贵金属"],
                "affected_stocks": ["002155", "600489", "600547"],
                "lag": "immediate",
            },
            {
                "cause": "美元走弱",
                "effect": "人民币升值",
                "direction": "positive",
                "magnitude": "moderate",
                "affected_sectors": ["航空", "造纸"],
                "affected_stocks": ["600115", "601111"],
                "lag": "1-3d",
            },
            {
                "cause": "美元走弱",
                "effect": "外资流入预期",
                "direction": "positive",
                "magnitude": "moderate",
                "affected_sectors": ["大盘蓝筹", "消费"],
                "affected_stocks": ["600519", "000858"],
                "lag": "1-3d",
            },
        ],
    },
    "geopolitical_war": {
        "trigger_type": "geopolitical",
        "paths": [
            {
                "cause": "地缘冲突/战争",
                "effect": "避险情绪升温",
                "direction": "positive",
                "magnitude": "strong",
                "affected_sectors": ["黄金", "军工"],
                "affected_stocks": ["002155", "600489", "600893"],
                "lag": "immediate",
            },
            {
                "cause": "地缘冲突/战争",
                "effect": "原油供应担忧",
                "direction": "positive",
                "magnitude": "strong",
                "affected_sectors": ["石油", "天然气"],
                "affected_stocks": ["601857", "600028"],
                "lag": "immediate",
            },
            {
                "cause": "地缘冲突/战争",
                "effect": "供应链中断风险",
                "direction": "positive",
                "magnitude": "moderate",
                "affected_sectors": ["国产替代", "稀土", "半导体"],
                "affected_stocks": ["600111", "600460"],  # 北方稀土, 士兰微
                "lag": "1-3d",
            },
            {
                "cause": "地缘冲突/战争",
                "effect": "全球风险偏好下降",
                "direction": "negative",
                "magnitude": "moderate",
                "affected_sectors": ["科技", "成长股"],
                "lag": "immediate",
            },
        ],
    },
    "fed_hawkish": {
        "trigger_type": "monetary",
        "paths": [
            {
                "cause": "美联储鹰派/加息",
                "effect": "全球流动性收紧",
                "direction": "negative",
                "magnitude": "strong",
                "affected_sectors": ["成长股", "科技"],
                "lag": "immediate",
            },
            {
                "cause": "美联储鹰派/加息",
                "effect": "美元走强",
                "direction": "negative",
                "magnitude": "moderate",
                "affected_sectors": ["黄金", "贵金属"],
                "affected_stocks": ["002155", "600489"],
                "lag": "immediate",
            },
            {
                "cause": "美联储鹰派/加息",
                "effect": "美债收益率上升",
                "direction": "negative",
                "magnitude": "moderate",
                "affected_sectors": ["高估值", "科技"],
                "lag": "1-3d",
            },
        ],
    },
    "fed_dovish": {
        "trigger_type": "monetary",
        "paths": [
            {
                "cause": "美联储鸽派/降息",
                "effect": "全球流动性宽松",
                "direction": "positive",
                "magnitude": "strong",
                "affected_sectors": ["成长股", "科技", "新能源"],
                "lag": "immediate",
            },
            {
                "cause": "美联储鸽派/降息",
                "effect": "美元走弱",
                "direction": "positive",
                "magnitude": "moderate",
                "affected_sectors": ["黄金", "贵金属"],
                "affected_stocks": ["002155", "600489"],
                "lag": "immediate",
            },
        ],
    },
    "gold_surge": {
        "trigger_type": "commodity",
        "paths": [
            {
                "cause": "黄金价格大涨",
                "effect": "黄金矿业股受益",
                "direction": "positive",
                "magnitude": "strong",
                "affected_sectors": ["黄金", "贵金属"],
                "affected_stocks": ["002155", "600489", "600547", "600988"],
                "lag": "immediate",
            },
            {
                "cause": "黄金价格大涨",
                "effect": "避险情绪反映",
                "direction": "negative",
                "magnitude": "weak",
                "affected_sectors": ["风险资产"],
                "lag": "1-3d",
            },
        ],
    },
}

# Keyword -> template mapping for automatic event detection
EVENT_KEYWORDS: dict[str, list[str]] = {
    "oil_surge": ["原油", "油价", "OPEC", "石油", "oil"],
    "usd_strengthen": ["美元走强", "美元升值", "DXY上涨", "dollar rally"],
    "usd_weaken": ["美元走弱", "美元贬值", "DXY下跌"],
    "geopolitical_war": [
        "战争",
        "冲突",
        "军事",
        "袭击",
        "制裁",
        "入侵",
        "伊朗",
        "以色列",
        "俄罗斯",
        "乌克兰",
        "朝鲜",
        "war",
        "conflict",
        "sanction",
    ],
    "fed_hawkish": ["加息", "鹰派", "紧缩", "hawkish", "rate hike"],
    "fed_dovish": ["降息", "鸽派", "宽松", "dovish", "rate cut"],
    "gold_surge": ["黄金大涨", "金价飙升", "gold surge", "gold rally"],
}


def _build_sector_stock_map(
    templates: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    """Invert the curated CHAIN_TEMPLATES into a ``sector -> [stocks]`` map.

    Engine B (``CausalChainConstructor``) resolves only *sectors* —
    ``ImpactChainLink.affected_stocks`` is always empty. To preserve Engine A's
    ``find_stock_impact`` contract we re-use the hand-authored stock bindings
    that live in ``CHAIN_TEMPLATES``: each path binds ``affected_sectors`` to
    ``affected_stocks``, so inverting gives a sector → stock lookup we can use to
    re-populate the bridged chain's stocks.
    """
    sector_stocks: dict[str, list[str]] = {}
    for template in templates.values():
        for path in template.get("paths", []):
            stocks = path.get("affected_stocks", [])
            if not stocks:
                continue
            for sector in path.get("affected_sectors", []):
                bucket = sector_stocks.setdefault(sector, [])
                for stock in stocks:
                    if stock not in bucket:
                        bucket.append(stock)
    return sector_stocks


# Map a chain link's order to a human-readable transmission lag.
_LAG_BY_ORDER: dict[int, str] = {0: "immediate", 1: "1-3d", 2: "1-2w"}


def _magnitude_from_confidence(confidence: float) -> str:
    """Bucket a link confidence into Engine A's magnitude vocabulary."""
    if confidence >= 0.7:
        return "strong"
    if confidence >= 0.4:
        return "moderate"
    return "weak"


class ImpactChainEngine:
    """Adapter exposing Engine A's API on top of Engine B.

    This class used to own its own ``CHAIN_TEMPLATES`` rule base. It is now a
    thin adapter over :class:`~src.intelligence.causal_chain.CausalChainConstructor`
    (Engine B), which loads the canonical YAML templates
    (``config/impact_chain_templates.yaml``) and matches events via regex.

    The public surface — ``detect_event_type``, ``build_chain``,
    ``build_chains_for_event``, ``find_stock_impact`` and ``persist_chain`` —
    and the ``ImpactChain`` / ``TransmissionPath`` dataclasses are preserved for
    existing callers (relevance_scorer, rotation_engine, tool_registry, the web
    API).

    Engine B resolves sectors but leaves ``affected_stocks`` empty, so this
    adapter re-binds stocks using a ``sector -> [stocks]`` map inverted from the
    legacy ``CHAIN_TEMPLATES`` (kept in this module solely as that data source).
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or self._load_config()
        # CHAIN_TEMPLATES / EVENT_KEYWORDS are retained ONLY as the data source
        # for the sector -> stock map used to defuse Engine B's empty
        # affected_stocks. Chain construction itself is delegated to Engine B.
        templates = self._config.get("templates", CHAIN_TEMPLATES)
        self._sector_stocks = _build_sector_stock_map(templates)

        from src.intelligence.causal_chain import CausalChainConstructor

        self._constructor = CausalChainConstructor()
        logger.info(
            "ImpactChainEngine initialized (adapter over CausalChainConstructor); "
            "%d sectors in stock map",
            len(self._sector_stocks),
        )

    @staticmethod
    def _load_config() -> dict[str, Any]:
        try:
            return load_config("impact_chains")
        except FileNotFoundError:
            return {}

    def _resolve_stocks(self, sectors: list[str]) -> list[str]:
        """Resolve a list of sectors to stock codes via the inverted map."""
        stocks: list[str] = []
        for sector in sectors:
            for stock in self._sector_stocks.get(sector, []):
                if stock not in stocks:
                    stocks.append(stock)
        return stocks

    def detect_event_type(self, text: str) -> list[str]:
        """Detect which Engine B template matches the given text.

        Delegates to ``CausalChainConstructor``'s regex template matching.

        Args:
            text: News headline, alert summary, or event description.

        Returns:
            ``[template_name]`` if a template matches, else ``[]``. Engine B
            returns a single best match (first matching regex), so this is at
            most one element — a semantic change from the old multi-template,
            keyword-count-ranked behaviour.
        """
        match = self._constructor._match_template(text)
        return [match[0]] if match else []

    def build_chain(
        self,
        event_text: str,
        template_key: str | None = None,
    ) -> ImpactChain | None:
        """Build an impact chain from an event description.

        Delegates construction to Engine B and bridges the resulting
        ``CausalChain`` into Engine A's ``ImpactChain`` shape, re-binding stocks
        from the sector → stock map (Engine B leaves ``affected_stocks`` empty).

        Args:
            event_text: The event description/headline.
            template_key: Accepted for backward compatibility but ignored —
                Engine B selects the template from the event text itself.

        Returns:
            ImpactChain or None if Engine B finds no matching template.
        """
        causal = self._constructor.construct_chain({"title": event_text})
        if causal is None:
            logger.debug("No matching template for event: %s", event_text[:50])
            return None

        paths: list[TransmissionPath] = []
        previous_impact = event_text
        for link in causal.chain:
            affected_stocks = link.affected_stocks or self._resolve_stocks(link.sectors)
            paths.append(
                TransmissionPath(
                    cause=previous_impact,
                    effect=link.impact,
                    direction="positive" if link.direction == "bullish" else "negative",
                    magnitude=_magnitude_from_confidence(link.confidence),
                    affected_sectors=link.sectors,
                    affected_stocks=affected_stocks,
                    lag=_LAG_BY_ORDER.get(link.order, "1-3m"),
                )
            )
            previous_impact = link.impact

        chain = ImpactChain(
            chain_id=str(uuid.uuid4()),
            trigger_event=event_text,
            trigger_type=causal.event_type,
            timestamp=datetime.now(UTC),
            transmission_paths=paths,
            confidence=causal.base_confidence,
            time_horizon="short_term",
            source="template",
        )

        logger.info(
            "Built impact chain for '%s' via Engine B template '%s': "
            "%d paths, %d sectors",
            event_text[:40],
            causal.event_type,
            len(paths),
            len(chain.all_affected_sectors),
        )

        # Persist to SQLite for historical analysis
        self.persist_chain(chain)

        return chain

    def build_chains_for_event(self, event_text: str) -> list[ImpactChain]:
        """Build matching impact chains for an event.

        Semantic shift: Engine A used to return one chain per matched keyword
        template (a compound event like "中东战争导致油价飙升" could yield two
        chains). Engine B returns a single best-match chain per event, so this
        now returns ``[chain]`` (or ``[]`` if no template matches).
        """
        chain = self.build_chain(event_text)
        return [chain] if chain is not None else []

    def persist_chain(self, chain: ImpactChain) -> None:
        """Persist an impact chain to SQLite for historical analysis."""
        import json
        import sqlite3

        try:
            from src.utils.config import get_project_root

            db_path = get_project_root() / "data" / "impact_chains.db"
            db_path.parent.mkdir(parents=True, exist_ok=True)

            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS impact_chains (
                    chain_id TEXT PRIMARY KEY,
                    trigger_event TEXT,
                    trigger_type TEXT,
                    timestamp TEXT,
                    confidence REAL,
                    time_horizon TEXT,
                    source TEXT,
                    paths_json TEXT,
                    sectors_json TEXT,
                    stocks_json TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute(
                """INSERT OR REPLACE INTO impact_chains
                   (chain_id, trigger_event, trigger_type, timestamp,
                    confidence, time_horizon, source,
                    paths_json, sectors_json, stocks_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    chain.chain_id,
                    chain.trigger_event,
                    chain.trigger_type,
                    chain.timestamp.isoformat(),
                    chain.confidence,
                    chain.time_horizon,
                    chain.source,
                    json.dumps(
                        [p.to_dict() for p in chain.transmission_paths],
                        ensure_ascii=False,
                    ),
                    json.dumps(chain.all_affected_sectors, ensure_ascii=False),
                    json.dumps(chain.all_affected_stocks, ensure_ascii=False),
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("Failed to persist impact chain %s: %s", chain.chain_id, e)

    def find_stock_impact(
        self, symbol: str, chains: list[ImpactChain]
    ) -> list[dict[str, Any]]:
        """Find all impacts on a specific stock across multiple chains.

        Args:
            symbol: Stock code (e.g. "002155").
            chains: List of ImpactChain to search.

        Returns:
            List of impact dicts with chain context.
        """
        impacts = []
        for chain in chains:
            for path in chain.transmission_paths:
                if symbol in path.affected_stocks:
                    impacts.append(
                        {
                            "chain_id": chain.chain_id,
                            "trigger_event": chain.trigger_event,
                            "cause": path.cause,
                            "effect": path.effect,
                            "direction": path.direction,
                            "magnitude": path.magnitude,
                            "lag": path.lag,
                            "confidence": chain.confidence,
                        }
                    )
        return impacts
