"""Sentinel capture — Gemini-powered news/sentiment aggregation.

Aggregates NewsFetcher (news, anomalies, hot rank) data and uses
LLMGateway (Gemini) to synthesize a structured sentiment snapshot.

Output: ``data/raw/gemini_sense.json``

When Gemini is unavailable (timeout/rate-limit), writes raw data
with ``fallback_used: true`` marker so downstream consumers can
apply local heuristics instead.

Reuses existing infrastructure:
- ``src/data/news_fetcher.py`` — AKShare data collection
- ``src/llm/gateway.py`` — LLM routing with caller="sentinel_capture"
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("data.sentinel_capture")


class SentinelCapture:
    """Gemini-powered sentinel that scans news, anomalies, and hot stocks.

    Generates a structured JSON snapshot at ``data/raw/gemini_sense.json``
    combining raw market data with LLM-synthesized sentiment scores.

    Args:
        gateway: Optional LLMGateway instance. If None, created from DI.
        news_fetcher: Optional NewsFetcher instance. If None, created fresh.
    """

    def __init__(
        self,
        gateway: Any | None = None,
        news_fetcher: Any | None = None,
    ) -> None:
        self._config: dict[str, Any] = {}
        self._load_config()
        self._gateway = gateway
        self._news_fetcher = news_fetcher

    def _load_config(self) -> None:
        """Load sentinel config from research.yaml."""
        try:
            research_cfg = load_config("research")
            self._config = research_cfg.get("sentinel", {})
        except FileNotFoundError:
            logger.warning("config/research.yaml not found, using defaults")
            self._config = {}

    def _get_gateway(self) -> Any:
        """Lazy-load LLMGateway."""
        if self._gateway is None:
            from src.web.dependencies import get_llm_gateway

            self._gateway = get_llm_gateway()
        return self._gateway

    def _get_news_fetcher(self) -> Any:
        """Lazy-load NewsFetcher."""
        if self._news_fetcher is None:
            from src.data.news_fetcher import NewsFetcher

            self._news_fetcher = NewsFetcher()
        return self._news_fetcher

    def capture(self, symbols: list[str] | None = None) -> dict[str, Any]:
        """Run sentinel capture: fetch data + Gemini sentiment synthesis.

        Args:
            symbols: List of 6-digit stock codes. Defaults to config list.

        Returns:
            Full sentinel output dict (also written to disk).
        """
        symbols = symbols or self._config.get("default_symbols", [])
        if not symbols:
            # Fall back to orchestration defaults
            try:
                research_cfg = load_config("research")
                symbols = research_cfg.get("orchestration", {}).get(
                    "default_symbols", []
                )
            except FileNotFoundError:
                pass

        logger.info("Sentinel capture starting for %d symbols", len(symbols))
        now = datetime.now(timezone.utc)

        # Step 1: Collect raw data from NewsFetcher
        raw_data = self._collect_raw_data(symbols)

        # Step 2: Attempt Gemini sentiment synthesis
        synthesis = self._synthesize_sentiment(symbols, raw_data)

        # Step 3: Assemble output
        output = {
            "timestamp": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "symbols": symbols,
            "fallback_used": synthesis.get("fallback_used", False),
            "raw": raw_data,
            "sentiment": synthesis.get("sentiment", {}),
            "summary": synthesis.get("summary", ""),
        }

        # Step 4: Write to disk
        self._write_output(output)

        logger.info(
            "Sentinel capture complete: %d symbols, fallback=%s",
            len(symbols),
            output["fallback_used"],
        )
        return output

    def _collect_raw_data(self, symbols: list[str]) -> dict[str, Any]:
        """Collect news, anomalies, and hot rank data."""
        fetcher = self._get_news_fetcher()
        raw: dict[str, Any] = {
            "news": {},
            "anomalies": [],
            "hot_rank": [],
        }

        # Fetch news per symbol
        for symbol in symbols[: self._config.get("max_symbols_per_batch", 20)]:
            try:
                news_df = fetcher.fetch_stock_news(symbol)
                if news_df is not None and not news_df.empty:
                    raw["news"][symbol] = news_df.head(10).to_dict(orient="records")
                else:
                    raw["news"][symbol] = []
            except Exception as exc:
                logger.warning("News fetch failed for %s: %s", symbol, exc)
                raw["news"][symbol] = []

        # Fetch market anomalies (batch)
        try:
            anomalies_df = fetcher.fetch_market_anomalies()
            if anomalies_df is not None and not anomalies_df.empty:
                raw["anomalies"] = anomalies_df.head(50).to_dict(orient="records")
        except Exception as exc:
            logger.warning("Anomalies fetch failed: %s", exc)

        # Fetch hot rank
        try:
            hot_limit = self._config.get("hot_rank_limit", 30)
            hot_df = fetcher.fetch_hot_rank()
            if hot_df is not None and not hot_df.empty:
                raw["hot_rank"] = hot_df.head(hot_limit).to_dict(orient="records")
        except Exception as exc:
            logger.warning("Hot rank fetch failed: %s", exc)

        return raw

    def _synthesize_sentiment(
        self, symbols: list[str], raw_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Use Gemini to synthesize sentiment from raw data.

        Returns:
            Dict with 'sentiment' (per-symbol scores), 'summary', and
            'fallback_used' flag.
        """
        if not self._config.get("fallback_on_llm_failure", True):
            # Config says skip LLM
            return {"fallback_used": True, "sentiment": {}, "summary": ""}

        try:
            gateway = self._get_gateway()
        except Exception as exc:
            logger.warning("LLMGateway unavailable: %s", exc)
            return {"fallback_used": True, "sentiment": {}, "summary": ""}

        # Build prompt for Gemini
        prompt = self._build_sentiment_prompt(symbols, raw_data)

        try:
            from src.llm.base import LLMMessage

            messages = [
                LLMMessage(
                    role="system",
                    content=(
                        "You are an A-share market sentiment analyst. "
                        "Write all output text in Chinese."
                    ),
                ),
                LLMMessage(role="user", content=prompt),
            ]
            timeout = self._config.get("timeout_seconds", 30)
            response = gateway.complete(
                messages,
                caller="sentinel_capture",
                timeout=float(timeout),
                max_tokens=2048,
                temperature=0.2,
            )

            # Parse LLM response
            return self._parse_sentiment_response(symbols, response.content)

        except Exception as exc:
            logger.warning("Gemini sentiment synthesis failed: %s", exc)
            return {"fallback_used": True, "sentiment": {}, "summary": ""}

    def _build_sentiment_prompt(
        self, symbols: list[str], raw_data: dict[str, Any]
    ) -> str:
        """Build sentiment analysis prompt from raw data."""
        parts: list[str] = []
        parts.append(
            "Analyze the following A-share market data. For each stock, output a "
            "sentiment score (0-1) and a short assessment. Write all text values in Chinese."
        )
        parts.append("")

        # News summary per symbol
        for symbol in symbols:
            news_list = raw_data.get("news", {}).get(symbol, [])
            if news_list:
                titles = [n.get("title", "") for n in news_list[:5] if n.get("title")]
                if titles:
                    parts.append(f"【{symbol}】新闻: {'; '.join(titles)}")

        # Anomalies summary
        anomalies = raw_data.get("anomalies", [])
        if anomalies:
            anom_text = "; ".join(
                f"{a.get('name', '')}({a.get('change_type', '')})"
                for a in anomalies[:10]
            )
            parts.append(f"\n异动信号: {anom_text}")

        # Hot stocks
        hot = raw_data.get("hot_rank", [])
        if hot:
            hot_text = ", ".join(
                f"{h.get('name', '')}({h.get('symbol', '')})" for h in hot[:10]
            )
            parts.append(f"\n热度排行: {hot_text}")

        parts.append("\nRespond in JSON format (all text values in Chinese):")
        parts.append(
            '{"sentiment": {"SYMBOL": {"score": 0.X, "label": "..."}}, '
            '"summary": "一句话总结"}'
        )

        return "\n".join(parts)

    def _parse_sentiment_response(
        self, symbols: list[str], content: str
    ) -> dict[str, Any]:
        """Parse LLM response into structured sentiment data."""
        try:
            # Try to extract JSON from response
            # Handle potential markdown code blocks
            text = content.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

            parsed = json.loads(text)
            return {
                "fallback_used": False,
                "sentiment": parsed.get("sentiment", {}),
                "summary": parsed.get("summary", ""),
            }
        except (json.JSONDecodeError, AttributeError):
            logger.warning("Failed to parse Gemini sentiment response")
            return {"fallback_used": True, "sentiment": {}, "summary": ""}

    def _write_output(self, output: dict[str, Any]) -> Path:
        """Write sentinel output to data/raw/gemini_sense.json."""
        output_path_str = self._config.get(
            "output_path", "workspace/sentinel/gemini_sense.json"
        )

        # Resolve relative to project root
        if not output_path_str.startswith("/"):
            from src.utils.config import get_project_root

            output_path = get_project_root() / output_path_str
        else:
            output_path = Path(output_path_str)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Serialize with datetime handling
        def _default(obj: Any) -> Any:
            if hasattr(obj, "isoformat"):
                return obj.isoformat()
            if hasattr(obj, "item"):  # numpy scalar
                return obj.item()
            return str(obj)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2, default=_default)

        logger.info("Sentinel output written to %s", output_path)
        return output_path
