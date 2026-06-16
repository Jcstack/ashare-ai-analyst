"""Intelligence Chain Engine for cross-asset/cross-industry reasoning (I-089 Phase 2).

Traverses a configurable association graph to find related intelligence
across assets, sectors, and macro factors. Enables multi-hop reasoning
like: "Gold price surge → USD weakness → Export companies pressured".
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from src.utils.config import load_config

logger = logging.getLogger(__name__)


@dataclass
class IntelChainNode:
    """A node in the intelligence chain."""

    source: str  # What triggered this node (e.g., "国际金价暴涨")
    target_type: str  # "sector" | "commodity" | "concept" | "macro"
    target: str  # e.g., "黄金", "有色金属"
    relation: str  # e.g., "价格传导", "政策利好", "反向关联"
    confidence: float  # 0-1 chain link strength
    intel_items: list[dict] = field(default_factory=list)  # Related news/intel


@dataclass
class IntelChainResult:
    """Result of an intelligence chain traversal."""

    root_symbol: str
    chains: list[list[IntelChainNode]]  # Multiple chain paths
    summary_items: list[dict]  # All discovered intel items (deduplicated)

    def to_context_str(self, max_items: int = 8) -> str:
        """Format as context string for LLM prompt injection."""
        if not self.chains:
            return ""

        parts = [f"### 情报链分析 ({self.root_symbol})"]
        for i, chain in enumerate(self.chains[:3], 1):
            path = " → ".join(
                f"{n.target}({n.relation})" for n in chain
            )
            parts.append(f"链路{i}: {path}")

        if self.summary_items:
            parts.append("\n关联情报:")
            for item in self.summary_items[:max_items]:
                title = item.get("title", "")
                category = item.get("category", "")
                if title:
                    parts.append(f"  - [{category}] {title}")

        return "\n".join(parts)


# Default association graph when config/intel_chain.yaml is absent
_DEFAULT_GRAPH: dict[str, Any] = {
    "commodity_sector_map": {
        "黄金": {
            "sectors": ["贵金属", "黄金"],
            "related_commodities": ["美元"],
            "inverse": False,
        },
        "美元": {
            "sectors": ["纺织服装", "家电"],
            "macro_factors": ["出口", "汇率"],
            "inverse_sectors": ["黄金", "贵金属"],
        },
        "原油": {
            "sectors": ["石油石化", "化工"],
            "inverse_sectors": ["航空运输", "物流"],
            "related_commodities": ["天然气"],
        },
        "铜": {
            "sectors": ["有色金属", "铜"],
            "macro_factors": ["基建", "制造业PMI"],
        },
        "锂": {
            "sectors": ["锂电池", "新能源"],
            "related_commodities": ["钴", "镍"],
        },
    },
    "sector_chain_map": {
        "新能源": ["锂电池", "光伏", "风电", "储能"],
        "半导体": ["消费电子", "AI", "芯片设计", "封装测试"],
        "汽车": ["汽车零部件", "新能源车", "锂电池"],
        "房地产": ["建材", "家居", "银行"],
        "银行": ["保险", "券商", "房地产"],
        "医药": ["医疗器械", "生物制品", "CXO"],
        "白酒": ["食品饮料", "消费"],
        "军工": ["航空航天", "船舶", "特种材料"],
    },
    "macro_transmission": {
        "降息": {
            "beneficiaries": ["房地产", "银行", "消费"],
            "impact": "流动性宽松利好估值修复",
        },
        "加息": {
            "pressured": ["房地产", "成长股"],
            "beneficiaries": ["银行"],
            "impact": "流动性收紧压制高估值",
        },
        "基建": {
            "beneficiaries": ["建材", "钢铁", "有色金属", "工程机械"],
            "impact": "财政刺激拉动需求",
        },
        "贸易战": {
            "pressured": ["消费电子", "纺织服装", "出口"],
            "beneficiaries": ["军工", "国产替代", "半导体"],
            "impact": "关税壁垒重构供应链",
        },
        "通胀": {
            "beneficiaries": ["黄金", "资源股", "消费"],
            "pressured": ["成长股", "科技股"],
            "impact": "实物资产对冲通胀",
        },
    },
}


class IntelChainEngine:
    """Traverse association graphs to find related intelligence."""

    def __init__(
        self,
        info_store: Any | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._info_store = info_store
        if config is None:
            try:
                config = load_config("intel_chain")
            except Exception:
                config = {}
        self._graph = {**_DEFAULT_GRAPH, **config}
        self._commodity_map = self._graph.get("commodity_sector_map", {})
        self._sector_chain = self._graph.get("sector_chain_map", {})
        self._macro_transmission = self._graph.get("macro_transmission", {})

    def trace(
        self,
        symbol: str,
        sector: str = "",
        *,
        max_hops: int = 2,
        deadline: float | None = None,
    ) -> IntelChainResult:
        """Trace intelligence chains for a stock.

        Args:
            symbol: Stock code.
            sector: Stock's sector/industry name.
            max_hops: Maximum chain depth (1=direct, 2=one intermediary).
            deadline: Absolute timestamp deadline.

        Returns:
            IntelChainResult with discovered chains and intel items.
        """
        if deadline is None:
            deadline = time.time() + 5.0

        chains: list[list[IntelChainNode]] = []
        all_intel: list[dict] = []
        seen_titles: set[str] = set()

        # 1. Sector chain: find related sectors
        if sector:
            related_sectors = self._expand_sector(sector, max_hops)
            for rel_sector, relation, confidence in related_sectors:
                if time.time() > deadline:
                    break
                items = self._query_sector_intel(rel_sector, deadline)
                unique_items = [
                    it for it in items
                    if it.get("title") not in seen_titles
                ]
                for it in unique_items:
                    seen_titles.add(it.get("title", ""))
                if unique_items:
                    node = IntelChainNode(
                        source=sector,
                        target_type="sector",
                        target=rel_sector,
                        relation=relation,
                        confidence=confidence,
                        intel_items=unique_items,
                    )
                    chains.append([node])
                    all_intel.extend(unique_items)

        # 2. Commodity chain: check if any commodity affects this sector
        if sector and time.time() < deadline:
            for commodity, mapping in self._commodity_map.items():
                if time.time() > deadline:
                    break
                sectors = mapping.get("sectors", [])
                inverse_sectors = mapping.get("inverse_sectors", [])
                if sector in sectors or sector in inverse_sectors:
                    is_inverse = sector in inverse_sectors
                    relation = "反向关联" if is_inverse else "价格传导"
                    items = self._query_commodity_intel(commodity, deadline)
                    unique_items = [
                        it for it in items
                        if it.get("title") not in seen_titles
                    ]
                    for it in unique_items:
                        seen_titles.add(it.get("title", ""))
                    if unique_items:
                        node = IntelChainNode(
                            source=commodity,
                            target_type="commodity",
                            target=sector,
                            relation=relation,
                            confidence=0.7 if not is_inverse else 0.5,
                            intel_items=unique_items,
                        )
                        chains.append([node])
                        all_intel.extend(unique_items)

                    # Second hop: related commodities
                    if max_hops >= 2 and time.time() < deadline:
                        for rel_commodity in mapping.get("related_commodities", []):
                            rel_items = self._query_commodity_intel(
                                rel_commodity, deadline
                            )
                            rel_unique = [
                                it for it in rel_items
                                if it.get("title") not in seen_titles
                            ]
                            for it in rel_unique:
                                seen_titles.add(it.get("title", ""))
                            if rel_unique:
                                node1 = IntelChainNode(
                                    source=commodity,
                                    target_type="commodity",
                                    target=rel_commodity,
                                    relation="关联商品",
                                    confidence=0.5,
                                    intel_items=rel_unique,
                                )
                                node2 = IntelChainNode(
                                    source=rel_commodity,
                                    target_type="sector",
                                    target=sector,
                                    relation=relation,
                                    confidence=0.4,
                                )
                                chains.append([node1, node2])
                                all_intel.extend(rel_unique)

        # 3. Macro transmission: check if any macro event affects this sector
        if sector and time.time() < deadline:
            for macro_event, transmission in self._macro_transmission.items():
                if time.time() > deadline:
                    break
                beneficiaries = transmission.get("beneficiaries", [])
                pressured = transmission.get("pressured", [])
                if sector in beneficiaries or sector in pressured:
                    is_pressured = sector in pressured
                    items = self._query_macro_intel(macro_event, deadline)
                    unique_items = [
                        it for it in items
                        if it.get("title") not in seen_titles
                    ]
                    for it in unique_items:
                        seen_titles.add(it.get("title", ""))
                    if unique_items:
                        impact = transmission.get("impact", "")
                        node = IntelChainNode(
                            source=macro_event,
                            target_type="macro",
                            target=sector,
                            relation=f"{'利空' if is_pressured else '利好'}: {impact}",
                            confidence=0.6,
                            intel_items=unique_items,
                        )
                        chains.append([node])
                        all_intel.extend(unique_items)

        # Sort chains by confidence (highest first)
        chains.sort(
            key=lambda c: min(n.confidence for n in c) if c else 0,
            reverse=True,
        )

        return IntelChainResult(
            root_symbol=symbol,
            chains=chains,
            summary_items=all_intel,
        )

    def _expand_sector(
        self, sector: str, max_hops: int
    ) -> list[tuple[str, str, float]]:
        """Expand a sector to related sectors via chain map.

        Returns list of (related_sector, relation_type, confidence).
        """
        result: list[tuple[str, str, float]] = []
        # Direct relations (hop 1)
        related = self._sector_chain.get(sector, [])
        for r in related:
            result.append((r, "产业链关联", 0.7))

        # Reverse lookup: which sectors list this sector as related?
        for parent, children in self._sector_chain.items():
            if sector in children and parent != sector:
                result.append((parent, "上游关联", 0.6))

        if max_hops >= 2:
            # Second hop: related sectors' relations
            hop1_sectors = [r[0] for r in result]
            for s in hop1_sectors:
                for r in self._sector_chain.get(s, []):
                    if r != sector and r not in hop1_sectors:
                        result.append((r, f"间接关联(经{s})", 0.4))

        return result

    def _query_sector_intel(
        self, sector: str, deadline: float
    ) -> list[dict]:
        """Query InfoStore for sector-related intel."""
        if not self._info_store or time.time() > deadline:
            return []
        try:
            items = self._info_store.get_feed(
                category="industry", search=sector, limit=3, days=3
            )
            return items or []
        except Exception:
            return []

    def _query_commodity_intel(
        self, commodity: str, deadline: float
    ) -> list[dict]:
        """Query InfoStore for commodity-related intel."""
        if not self._info_store or time.time() > deadline:
            return []
        try:
            items = self._info_store.get_feed(
                search=commodity, limit=3, days=3
            )
            return items or []
        except Exception:
            return []

    def _query_macro_intel(
        self, macro_event: str, deadline: float
    ) -> list[dict]:
        """Query InfoStore for macro event intel."""
        if not self._info_store or time.time() > deadline:
            return []
        try:
            items = self._info_store.query_by_keywords(
                [macro_event], hours=72, limit=3
            )
            return items or []
        except Exception:
            return []
