"""AI structured sentiment report generator.

Per PRD v3.2 FR-TN004: generate 6-part structured sentiment analysis from
aggregated trend news, resonance events, global market data, and cross-market
correlations via LLM.

Output structure:
1. core_trends — top trending topics with sentiment/stock links
2. policy_signals — government/regulatory policy impacts
3. global_linkage — US/HK/commodity/forex market summary
4. risk_alerts — risk warnings by type and severity
5. sector_outlook — bullish/bearish/neutral sector classification
6. overall_outlook — summary assessment paragraph
"""

import json
import time
from typing import Any

from src.llm.base import LLMMessage, LLMProviderError
from src.llm.router import RoutingStrategy
from src.prediction.realtime_analyzer import RealtimeAnalyzer
from src.utils.logger import get_logger

logger = get_logger("prediction.sentiment_report")

_DISCLAIMER = "舆情分析仅供参考，不构成投资建议。"

_SENTIMENT_SYSTEM_PROMPT = """\
You are an A-share market sentiment analyst. Based on multi-platform trending news, \
cross-platform resonance events, global market linkages, and user portfolio information, \
generate a structured sentiment analysis report.

All text values in the output must be in Chinese.

## Report Structure

### 1. Core Trends (core_trends)
- Identify the 3-5 most important trending topics
- Tag each with resonance_level (L1/L2/L3) and sentiment (positive/negative/neutral)
- Link affected stock codes (related_stocks)

### 2. Policy Signals (policy_signals)
- Identify central bank, regulatory, and fiscal policy news
- Assess impact direction and confidence for affected sectors

### 3. Global Market Linkage (global_linkage)
- US, HK, commodity, and forex transmission effects on A-shares
- Quantify linkage strength

### 4. Risk Alerts (risk_alerts)
- Sector valuation risk, liquidity risk, geopolitical risk, regulatory risk
- Tag severity (low/medium/high) with mitigation advice

### 5. Sector Outlook (sector_outlook)
- Classify as bullish / bearish / neutral

### 6. Overall Outlook (overall_outlook)
- One paragraph comprehensive assessment in Chinese

Output strict JSON:

```json
{
  "core_trends": [
    {
      "topic": "topic title in Chinese",
      "resonance_level": "L1|L2|L3",
      "sentiment": "positive|negative|neutral",
      "related_stocks": ["code1", "code2"],
      "summary": "one-line summary in Chinese"
    }
  ],
  "policy_signals": [
    {
      "title": "policy title in Chinese",
      "impact": "positive|negative|neutral",
      "affected_sectors": ["sector1", "sector2"],
      "confidence": 0.0-1.0,
      "summary": "impact description in Chinese"
    }
  ],
  "global_linkage": {
    "us_market_summary": "US market summary in Chinese",
    "commodity_impact": "commodity market impact in Chinese",
    "forex_impact": "forex impact in Chinese"
  },
  "risk_alerts": [
    {
      "type": "risk_type",
      "title": "risk title in Chinese",
      "severity": "low|medium|high",
      "mitigation": "mitigation advice in Chinese"
    }
  ],
  "sector_outlook": {
    "bullish": ["sector1"],
    "bearish": ["sector2"],
    "neutral": ["sector3"]
  },
  "overall_outlook": "overall assessment text in Chinese"
}
```"""


class SentimentReportGenerator:
    """Generate structured 6-part sentiment analysis reports (FR-TN004).

    Combines trend news, resonance events, global data, and cross-market
    correlations to produce comprehensive market sentiment analysis via LLM.

    Args:
        router: LLM router/gateway instance for API calls.
    """

    def __init__(self, router: Any | None = None, cache: Any | None = None) -> None:
        if router is None:
            from src.web.dependencies import get_llm_gateway

            router = get_llm_gateway()
        self._router = router
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._llm_cache = cache  # LLMResultCache (L1+L2) or None

    def generate_report(
        self,
        *,
        trend_items: list[dict[str, Any]] | None = None,
        resonance_events: list[dict[str, Any]] | None = None,
        global_snapshot: dict[str, Any] | None = None,
        cross_market_data: dict[str, dict[str, Any]] | None = None,
        watchlist: list[str] | None = None,
        positions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Generate a full structured sentiment report.

        Args:
            trend_items: Aggregated trend news items.
            resonance_events: Cross-platform resonance events.
            global_snapshot: Global market snapshot (indices/commodities/currencies).
            cross_market_data: Per-symbol cross-market analysis.
            watchlist: User watchlist symbols for relevance matching.
            positions: User positions for impact assessment.

        Returns:
            Structured sentiment report dict.
        """
        cache_key = "sentiment_report"
        cached = self._get_cached(cache_key, 1800)  # 30min
        if cached is not None:
            return cached

        # Build prompt
        prompt_sections = ["## 市场舆情综合研判"]

        # Trending topics
        if trend_items:
            lines = []
            for item in trend_items[:20]:
                title = item.get("title", "")
                platform = item.get("platform", "")
                heat = item.get("heat_score", 0)
                lines.append(f"[{platform}] {title} (热度: {heat:.2f})")
            prompt_sections.append("\n### 热点话题\n" + "\n".join(lines))

        # Resonance events
        if resonance_events:
            lines = []
            for evt in resonance_events[:10]:
                title = evt.get("title", "")
                level = evt.get("resonance_level", "L1")
                platforms = ", ".join(evt.get("platforms", []))
                sentiment = evt.get("sentiment", "neutral")
                related = ", ".join(evt.get("related_stocks", []))
                lines.append(
                    f"[{level}] {title} — 平台: {platforms} | "
                    f"情绪: {sentiment} | 关联: {related or '无'}"
                )
            prompt_sections.append("\n### 跨平台共振事件\n" + "\n".join(lines))

        # Global market
        if global_snapshot:
            indices = global_snapshot.get("indices", [])
            if indices:
                idx_lines = [
                    f"{idx.get('name', '')}: {idx.get('pct_change', 0):+.2f}%"
                    for idx in indices[:8]
                ]
                prompt_sections.append("\n### 全球市场\n" + " | ".join(idx_lines))

            commodities = global_snapshot.get("commodities", [])
            if commodities:
                com_lines = [
                    f"{c.get('name', '')}: {c.get('pct_change', 0):+.2f}%"
                    for c in commodities[:5]
                ]
                prompt_sections.append("商品: " + " | ".join(com_lines))

            currencies = global_snapshot.get("currencies", [])
            if currencies:
                fx_lines = [
                    f"{c.get('name', '')}: {c.get('price', 0)}" for c in currencies[:3]
                ]
                prompt_sections.append("汇率: " + " | ".join(fx_lines))

        # Cross-market correlations
        if cross_market_data:
            lines = []
            for sym, data in list(cross_market_data.items())[:10]:
                direction = data.get("impact_direction", "neutral")
                score = data.get("combined_impact_score", 0)
                tags = ", ".join(data.get("tags", []))
                lines.append(f"{sym} ({tags}): 跨市场影响 {direction} ({score:+.2f})")
            prompt_sections.append("\n### 跨市场关联\n" + "\n".join(lines))

        # User context
        if positions:
            sym_list = [
                f"{p.get('symbol', '')}({p.get('name', '')})" for p in positions[:15]
            ]
            prompt_sections.append("\n### 用户持仓\n" + ", ".join(sym_list))

        if watchlist:
            prompt_sections.append("\n### 自选股\n" + ", ".join(watchlist[:20]))

        prompt_text = "\n".join(prompt_sections)

        messages = [
            LLMMessage(role="system", content=_SENTIMENT_SYSTEM_PROMPT),
            LLMMessage(role="user", content=prompt_text),
        ]

        try:
            response = self._router.complete(
                messages=messages,
                caller="sentiment_report.generate_report",
                strategy=RoutingStrategy.QUALITY,
                max_tokens=16384,
                temperature=0.3,
                analysis_type="sentiment_report",
            )
            result = self._parse_report(response.text)
            result["model_used"] = response.model
            result["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            result["disclaimer"] = _DISCLAIMER
            self._set_cached(cache_key, result, ttl=1800)
            return result
        except (LLMProviderError, Exception) as exc:
            logger.error("Sentiment report generation failed: %s", exc)
            return _empty_report(str(exc))

    def _parse_report(self, text: str) -> dict[str, Any]:
        """Parse the 6-part structured report from LLM response."""
        json_str = RealtimeAnalyzer._extract_json(text)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("Failed to parse sentiment report JSON")
            return _empty_report("JSON parse error")

        # Normalize core_trends
        core_trends = data.get("core_trends", [])
        if not isinstance(core_trends, list):
            core_trends = []
        for trend in core_trends:
            if not isinstance(trend, dict):
                continue
            trend.setdefault("topic", "")
            trend.setdefault("resonance_level", "L1")
            trend.setdefault("sentiment", "neutral")
            trend.setdefault("related_stocks", [])
            trend.setdefault("summary", "")

        # Normalize policy_signals
        policy_signals = data.get("policy_signals", [])
        if not isinstance(policy_signals, list):
            policy_signals = []

        # Normalize global_linkage
        global_linkage = data.get("global_linkage", {})
        if not isinstance(global_linkage, dict):
            global_linkage = {}
        global_linkage.setdefault("us_market_summary", "")
        global_linkage.setdefault("commodity_impact", "")
        global_linkage.setdefault("forex_impact", "")

        # Normalize risk_alerts
        risk_alerts = data.get("risk_alerts", [])
        if not isinstance(risk_alerts, list):
            risk_alerts = []

        # Normalize sector_outlook
        sector_outlook = data.get("sector_outlook", {})
        if not isinstance(sector_outlook, dict):
            sector_outlook = {}
        sector_outlook.setdefault("bullish", [])
        sector_outlook.setdefault("bearish", [])
        sector_outlook.setdefault("neutral", [])

        overall = str(data.get("overall_outlook", ""))

        return {
            "status": "success",
            "core_trends": core_trends,
            "policy_signals": policy_signals,
            "global_linkage": global_linkage,
            "risk_alerts": risk_alerts,
            "sector_outlook": sector_outlook,
            "overall_outlook": overall,
        }

    def _get_cached(self, key: str, ttl: float) -> dict[str, Any] | None:
        # L1 in-process check
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < ttl:
                return data
        # L2 Redis check (backfills L1 on hit)
        if self._llm_cache is not None:
            l2 = self._llm_cache.get(key, ttl)
            if l2 is not None:
                self._cache[key] = (time.time(), l2)
                return l2
        return None

    def _set_cached(self, key: str, data: dict[str, Any], ttl: int = 0) -> None:
        self._cache[key] = (time.time(), data)
        if self._llm_cache is not None and ttl > 0:
            self._llm_cache.set(key, data, ttl)


def _empty_report(message: str = "") -> dict[str, Any]:
    """Return a safe empty sentiment report."""
    return {
        "status": "error",
        "core_trends": [],
        "policy_signals": [],
        "global_linkage": {
            "us_market_summary": "",
            "commodity_impact": "",
            "forex_impact": "",
        },
        "risk_alerts": [],
        "sector_outlook": {"bullish": [], "bearish": [], "neutral": []},
        "overall_outlook": "舆情分析暂时不可用",
        "disclaimer": _DISCLAIMER,
        "message": message,
    }
