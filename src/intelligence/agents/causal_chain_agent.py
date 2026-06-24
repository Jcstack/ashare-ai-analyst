"""Dynamic Causal Chain Agent — Analyst Team member for impact chain building.

Enhances the existing ImpactChainEngine with:
1. Extended template library (30+ templates from YAML config)
2. LLM fallback for novel events with no matching template
3. Auto-persistence of discovered chains

Per PRD v39.0 FR-GIT007.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from functools import lru_cache

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("intelligence.agents.causal_chain")


class DynamicCausalChainAgent:
    """Analyst team: template-first, LLM-fallback causal chain builder.

    Wraps the existing ImpactChainEngine and extends it with:
    - Extended templates loaded from config/impact_chain_templates.yaml
    - LLM-based chain construction for novel events
    - Auto-persistence of newly discovered chains
    """

    LLM_SYSTEM_PROMPT = (
        "你是A股产业链分析专家。你的工作是将事件分解为因果传导链，"
        "从事件源头追踪到具体受影响的A股板块和个股。\n\n"
        "## 分析原则\n"
        "1. 只构建有明确逻辑因果关系的传导路径，不要构建模糊的关联\n"
        "2. 每一环传导链的置信度必须逐级衰减（链越长越不确定）\n"
        "3. 区分直接影响（一阶）和间接影响（二阶以上）\n"
        "4. 区分确定性高的影响和推测性影响\n"
        "5. 股票代码必须是真实A股代码（6位数字），不确定时不要编造\n\n"
        "输出严格 JSON 格式。所有文本值用中文。"
    )

    LLM_CHAIN_PROMPT = """\
## 事件信息
事件: {event_summary}
类型: {event_type}
涉及领域: {domains}
初始板块线索: {sectors}

## 任务
构建该事件到A股市场的因果传导链。

## 每条路径必须包含
1. cause: 直接原因（中文，一句话）
2. effect: 传导效应（中文，一句话，说明为什么 cause 会导致该效应）
3. direction: positive（利好）或 negative（利空）
4. magnitude: strong(确定性高且影响大) / moderate(有影响但幅度有限) / weak(影响不确定或很小)
5. affected_sectors: 受影响的A股板块名（中文，如"半导体"、"新能源"）
6. affected_stocks: 具体股票代码（6位，如"600519"），不确定的不要编造
7. lag: 影响时滞 immediate(当日) / 1-3d / 1-2w / 1-3m
8. chain_confidence: 该环节的置信度(0-1)，每多一层传导衰减 0.1-0.2

## 输出格式
```json
{{
  "trigger_type": "tech|geopolitical|commodity|monetary|regulatory|industry|disaster|trade",
  "paths": [
    {{
      "cause": "...",
      "effect": "...(解释为什么)",
      "direction": "positive 或 negative",
      "magnitude": "strong/moderate/weak",
      "affected_sectors": ["板块中文名"],
      "affected_stocks": ["6位代码"],
      "lag": "immediate/1-3d/1-2w/1-3m",
      "chain_confidence": 0.0-1.0
    }}
  ],
  "confidence": 0.0-1.0,
  "data_gaps": ["分析中缺失的关键信息"]
}}
```

## 约束
- 最多5条传导路径
- 不确定的股票代码不要写，宁缺勿滥
- 如果事件与A股无明确关联，confidence < 0.3 并说明原因"""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        llm_router: Any | None = None,
    ) -> None:
        self._config = config or self._load_config()
        self._llm_router = llm_router
        self._impact_engine = None  # Lazy init to avoid circular imports
        self._extended_templates: dict[str, Any] = {}
        self._extended_keywords: dict[str, list[str]] = {}
        self._load_extended_templates()

        analyst_cfg = self._config.get("analyst", {}).get("causal_chain", {})
        self._llm_fallback = analyst_cfg.get("llm_fallback", True)
        self._llm_relevance_threshold = analyst_cfg.get("llm_relevance_threshold", 0.4)
        self._auto_persist = analyst_cfg.get("auto_persist_discoveries", True)

        logger.info(
            "DynamicCausalChainAgent initialized: %d extended templates, llm_fallback=%s",
            len(self._extended_templates),
            self._llm_fallback,
        )

    @staticmethod
    def _load_config() -> dict[str, Any]:
        try:
            return load_config("global_intelligence")
        except FileNotFoundError:
            return {}

    def _get_impact_engine(self):
        """Lazy-init ImpactChainEngine to avoid circular imports."""
        if self._impact_engine is None:
            from src.intelligence.impact_chain import ImpactChainEngine

            self._impact_engine = ImpactChainEngine()
        return self._impact_engine

    def _load_extended_templates(self) -> None:
        """Load extended templates from YAML config."""
        try:
            import yaml
            from src.utils.config import get_project_root

            templates_path = (
                get_project_root() / "config" / "impact_chain_templates.yaml"
            )
            if templates_path.exists():
                with open(templates_path) as f:
                    data = yaml.safe_load(f) or {}

                for key, template in data.items():
                    self._extended_templates[key] = template
                    keywords = template.get("keywords", [])
                    if keywords:
                        self._extended_keywords[key] = keywords

                logger.info(
                    "Loaded %d extended impact chain templates",
                    len(self._extended_templates),
                )
            else:
                logger.debug("No extended templates file found at %s", templates_path)
        except Exception as exc:
            logger.warning("Failed to load extended templates: %s", exc)

    def build_chains(
        self,
        event_text: str,
        event_type: str = "",
        domains: list[str] | None = None,
        sectors: list[str] | None = None,
        a_share_relevance: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Build impact chains for an event.

        Strategy:
        1. Try built-in templates (existing ImpactChainEngine)
        2. Try extended templates (from YAML config)
        3. If no match and relevance > threshold, use LLM

        Args:
            event_text: Event description/headline.
            event_type: Event type from EventUnderstanding.
            domains: Affected domains.
            sectors: Hint sectors from EventUnderstanding.
            a_share_relevance: A-share relevance score.

        Returns:
            List of chain dicts (serializable).
        """
        chains: list[dict[str, Any]] = []

        # Step 1: Try built-in templates
        try:
            engine = self._get_impact_engine()
            built_in = engine.build_chains_for_event(event_text)
            for chain in built_in:
                chains.append(chain.to_dict())
        except Exception as exc:
            logger.warning("Built-in template matching failed: %s", exc)

        # Step 2: Try extended templates
        if not chains:
            extended = self._match_extended_templates(event_text)
            chains.extend(extended)

        # Step 3: LLM fallback for novel events
        if not chains and self._llm_fallback and self._llm_router:
            if a_share_relevance >= self._llm_relevance_threshold:
                llm_chain = self._llm_build_chain(
                    event_text,
                    event_type,
                    domains or [],
                    sectors or [],
                )
                if llm_chain:
                    chains.append(llm_chain)
                    if self._auto_persist:
                        self._persist_discovered_chain(event_text, llm_chain)

        logger.info(
            "Built %d chains for: %s (built-in=%s, extended=%s, llm=%s)",
            len(chains),
            event_text[:40],
            any(
                c.get("source") != "llm" and c.get("source") != "extended_template"
                for c in chains
            ),
            any(c.get("source") == "extended_template" for c in chains),
            any(c.get("source") == "llm" for c in chains),
        )
        return chains

    def _match_extended_templates(self, event_text: str) -> list[dict[str, Any]]:
        """Match event text against extended templates."""
        text_lower = event_text.lower()
        matches: list[tuple[str, int]] = []

        for key, keywords in self._extended_keywords.items():
            hit_count = sum(1 for kw in keywords if kw.lower() in text_lower)
            if hit_count > 0:
                matches.append((key, hit_count))

        matches.sort(key=lambda x: x[1], reverse=True)

        results = []
        for key, _hits in matches[:2]:  # Max 2 matching templates
            template = self._extended_templates.get(key)
            if template:
                chain_dict = {
                    "chain_id": str(uuid.uuid4()),
                    "trigger_event": event_text,
                    "trigger_type": template.get("trigger_type", "unknown"),
                    "timestamp": datetime.now(UTC).isoformat(),
                    "transmission_paths": template.get("paths", []),
                    "confidence": 0.7,
                    "time_horizon": "short_term",
                    "source": "extended_template",
                    "template_key": key,
                }
                results.append(chain_dict)

        return results

    def _llm_build_chain(
        self,
        event_text: str,
        event_type: str,
        domains: list[str],
        sectors: list[str],
    ) -> dict[str, Any] | None:
        """Use LLM to dynamically construct a causal chain."""
        if not self._llm_router:
            return None

        prompt = self.LLM_CHAIN_PROMPT.format(
            event_summary=event_text,
            event_type=event_type or "unknown",
            domains=", ".join(domains) if domains else "未知",
            sectors=", ".join(sectors) if sectors else "未指定",
        )

        try:
            response = self._llm_router.generate(
                model="deepseek-chat",
                system=self.LLM_SYSTEM_PROMPT,
                prompt=prompt,
                max_tokens=1000,
            )
            return self._parse_llm_chain(str(response), event_text)
        except Exception as exc:
            logger.warning("LLM chain building failed: %s", exc)
            return None

    def _parse_llm_chain(self, response: str, event_text: str) -> dict[str, Any] | None:
        """Parse LLM response into a chain dict."""
        try:
            # Extract JSON
            start = response.find("{")
            end = response.rfind("}") + 1
            if start < 0 or end <= start:
                return None

            data = json.loads(response[start:end])
            paths = data.get("paths", [])

            if not paths:
                return None

            # Validate stock codes (must be 6 digits)
            for path in paths:
                stocks = path.get("affected_stocks", [])
                path["affected_stocks"] = [
                    s
                    for s in stocks
                    if isinstance(s, str) and len(s) == 6 and s.isdigit()
                ]

            return {
                "chain_id": str(uuid.uuid4()),
                "trigger_event": event_text,
                "trigger_type": data.get("trigger_type", "unknown"),
                "timestamp": datetime.now(UTC).isoformat(),
                "transmission_paths": paths,
                "confidence": min(
                    0.6, float(data.get("confidence", 0.5))
                ),  # Cap LLM confidence
                "time_horizon": "short_term",
                "source": "llm",
            }
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning("Failed to parse LLM chain response: %s", exc)
            return None

    def _persist_discovered_chain(self, event_text: str, chain: dict[str, Any]) -> None:
        """Persist a newly discovered LLM chain for future reference."""
        try:
            import sqlite3
            from src.utils.config import get_project_root

            db_path = get_project_root() / "data" / "discovered_chains.db"
            db_path.parent.mkdir(parents=True, exist_ok=True)

            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS discovered_chains (
                    chain_id TEXT PRIMARY KEY,
                    trigger_event TEXT,
                    trigger_type TEXT,
                    paths_json TEXT,
                    confidence REAL,
                    source TEXT DEFAULT 'llm',
                    reviewed INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute(
                """INSERT OR IGNORE INTO discovered_chains
                   (chain_id, trigger_event, trigger_type, paths_json, confidence, source)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    chain.get("chain_id", ""),
                    event_text,
                    chain.get("trigger_type", ""),
                    json.dumps(chain.get("transmission_paths", []), ensure_ascii=False),
                    chain.get("confidence", 0.5),
                    "llm",
                ),
            )
            conn.commit()
            conn.close()
            logger.info("Persisted discovered chain: %s", event_text[:40])
        except Exception as exc:
            logger.warning("Failed to persist discovered chain: %s", exc)


# ---------------------------------------------------------------------------
# DI singleton
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_causal_chain_agent() -> DynamicCausalChainAgent:
    from src.web.dependencies import get_llm_router

    return DynamicCausalChainAgent(
        config=load_config("global_intelligence"),
        llm_router=get_llm_router(),
    )
