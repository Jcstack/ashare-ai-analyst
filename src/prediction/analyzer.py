"""Multi-LLM stock analyzer for the A-share prediction layer.

Orchestrates prompt building, LLM API calls via the router, and
response parsing to produce structured stock analysis predictions.

Per PRD FR-P002: LLM engine with config-driven parameters.
Supports Anthropic Claude, OpenAI GPT, and Google Gemini via the
``src.llm`` abstraction layer.
"""

import json
import re
import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from src.llm.base import LLMMessage, LLMProviderError, ProviderName
from src.llm.consensus import ConsensusAnalyzer, ConsensusResult
from src.prediction.prompts import PromptBuilder
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger("prediction.analyzer")


class AnalyzerError(Exception):
    """Raised when stock analysis fails after all retries."""


class ResponseParsingError(Exception):
    """Raised when the LLM response cannot be parsed into valid JSON."""


class StockAnalyzer:
    """Multi-LLM powered A-share stock analyzer.

    Orchestrates the full analysis pipeline: builds a structured prompt
    from stock data, calls an LLM via the router with retry logic, and
    parses the response into a validated prediction dictionary.

    Attributes:
        config: Parsed prediction.yaml configuration dictionary.
        prompt_builder: PromptBuilder instance for constructing API messages.
    """

    def __init__(
        self,
        config_path: str = "prediction",
        router: Any | None = None,
    ) -> None:
        """Initialize the analyzer with LLM router/gateway.

        Args:
            config_path: Config file name without extension, resolved
                by ``load_config`` to ``config/<name>.yaml``.
            router: Optional pre-configured LLMRouter/LLMGateway instance.
                If not provided, the shared LLMGateway singleton is used.

        Raises:
            LLMProviderError: If no LLM providers are available.
        """
        self.config: dict[str, Any] = load_config(config_path)
        self._model_cfg: dict[str, Any] = self.config.get("model", {})
        self._retry_cfg: dict[str, Any] = self.config.get("retry", {})
        self._schema_cfg: dict[str, Any] = self.config.get("output_schema", {})
        self._required_fields: list[str] = self._schema_cfg.get("required_fields", [])

        if router is None:
            from src.web.dependencies import get_llm_gateway

            router = get_llm_gateway()
        self._router = router
        self.prompt_builder = PromptBuilder(config_path)

        logger.info(
            "StockAnalyzer initialized: providers=%s, max_tokens=%d",
            [p.value for p in self._router.available_providers],
            self._model_cfg.get("max_tokens", 4096),
        )

    def analyze(
        self,
        symbol: str,
        ohlcv_df: pd.DataFrame,
        indicators: dict[str, Any],
        patterns: list[dict[str, Any]],
        sr_levels: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Perform a full stock analysis using the LLM router.

        Orchestrates the pipeline: build prompt -> call LLM -> parse
        response -> add metadata.

        Args:
            symbol: 6-digit stock code (e.g. ``"000001"``).
            ohlcv_df: DataFrame with OHLCV data (date, open, high, low,
                close, volume, amount).
            indicators: Dictionary of technical indicator values.
            patterns: List of detected candlestick pattern dicts.
            sr_levels: List of support/resistance level dicts.

        Returns:
            Prediction dictionary containing all required fields plus
            metadata (symbol, timestamp, model).

        Raises:
            AnalyzerError: If the LLM call fails after all retries.
            ResponseParsingError: If the response cannot be parsed.
        """
        logger.info("Starting analysis for %s", symbol)

        messages = self.prompt_builder.build_analysis_prompt(
            symbol=symbol,
            ohlcv_df=ohlcv_df,
            indicators=indicators,
            patterns=patterns,
            sr_levels=sr_levels,
        )

        raw_text = self._call_llm(messages, symbol=symbol)
        prediction = self._parse_response(raw_text)

        # Add metadata
        prediction["symbol"] = symbol
        prediction["timestamp"] = datetime.now(timezone.utc).isoformat()
        prediction["model"] = self._model_cfg.get("name", "unknown")

        logger.info(
            "Analysis complete for %s: trend=%s, signal=%s, confidence=%.2f",
            symbol,
            prediction.get("trend", "unknown"),
            prediction.get("signal", "unknown"),
            prediction.get("confidence", 0.0),
        )
        return prediction

    def batch_analyze(
        self,
        symbols: list[str],
        ohlcv_map: dict[str, pd.DataFrame],
        indicators_map: dict[str, dict[str, Any]],
        patterns_map: dict[str, list[dict[str, Any]]],
        sr_map: dict[str, list[dict[str, Any]]],
    ) -> dict[str, dict[str, Any]]:
        """Analyze multiple symbols sequentially with rate limiting.

        Calls ``analyze()`` for each symbol. Per-symbol errors are logged
        and skipped. A configurable delay (default 1s) is applied between
        API calls to respect rate limits.

        Args:
            symbols: List of 6-digit stock codes to analyze.
            ohlcv_map: Mapping of symbol to its OHLCV DataFrame.
            indicators_map: Mapping of symbol to its indicator dict.
            patterns_map: Mapping of symbol to its pattern list.
            sr_map: Mapping of symbol to its support/resistance list.

        Returns:
            Dict mapping each successful symbol to its prediction dict.
        """
        results: dict[str, dict[str, Any]] = {}
        rate_limit_delay = self.config.get("batch", {}).get("rate_limit_delay", 1.0)

        for idx, symbol in enumerate(symbols):
            try:
                logger.info(
                    "Batch analyze %d/%d: %s",
                    idx + 1,
                    len(symbols),
                    symbol,
                )
                prediction = self.analyze(
                    symbol=symbol,
                    ohlcv_df=ohlcv_map.get(symbol, pd.DataFrame()),
                    indicators=indicators_map.get(symbol, {}),
                    patterns=patterns_map.get(symbol, []),
                    sr_levels=sr_map.get(symbol, []),
                )
                results[symbol] = prediction
            except Exception as exc:
                logger.error("Batch analyze failed for %s: %s", symbol, exc)
                continue

            # Respect API rate limits between calls
            if idx < len(symbols) - 1:
                time.sleep(rate_limit_delay)

        logger.info(
            "Batch analysis complete: %d/%d succeeded",
            len(results),
            len(symbols),
        )
        return results

    def analyze_market(
        self,
        index_data: dict[str, pd.DataFrame],
        market_indicators: dict[str, Any],
    ) -> dict[str, Any]:
        """Perform a broad market overview analysis using the LLM router.

        Args:
            index_data: Mapping of index code to OHLCV DataFrame.
            market_indicators: Market-wide indicator dict.

        Returns:
            Dict with market_trend, risk_assessment, sector_outlook,
            reasoning, key_risks, timestamp, and model fields.

        Raises:
            AnalyzerError: If the LLM call fails after all retries.
            ResponseParsingError: If the response cannot be parsed.
        """
        logger.info("Starting market overview analysis")

        messages = self.prompt_builder.build_market_prompt(
            index_data=index_data,
            market_indicators=market_indicators,
        )

        raw_text = self._call_llm(messages, analysis_type="market_overview")
        result = self._parse_market_response(raw_text)

        result["timestamp"] = datetime.now(timezone.utc).isoformat()
        result["model"] = self._model_cfg.get("name", "unknown")

        logger.info(
            "Market analysis complete: trend=%s, risk=%s",
            result.get("market_trend", "unknown"),
            result.get("risk_assessment", "unknown"),
        )
        return result

    def analyze_with_consensus(
        self,
        symbol: str,
        ohlcv_df: pd.DataFrame,
        indicators: dict[str, Any],
        patterns: list[dict[str, Any]],
        sr_levels: list[dict[str, Any]],
        providers: list[ProviderName] | None = None,
    ) -> ConsensusResult:
        """Analyze a stock using multiple LLM providers for consensus.

        Args:
            symbol: 6-digit stock code.
            ohlcv_df: OHLCV DataFrame.
            indicators: Technical indicator values.
            patterns: Candlestick patterns.
            sr_levels: Support/resistance levels.
            providers: Specific providers to use (defaults to all).

        Returns:
            ConsensusResult with weighted consensus and agreement score.
        """
        logger.info("Starting consensus analysis for %s", symbol)

        messages = self.prompt_builder.build_analysis_prompt(
            symbol=symbol,
            ohlcv_df=ohlcv_df,
            indicators=indicators,
            patterns=patterns,
            sr_levels=sr_levels,
        )

        llm_messages = _dict_messages_to_llm(messages)
        consensus_analyzer = ConsensusAnalyzer(
            providers={
                name: self._router.get_provider(name)
                for name in self._router.available_providers
                if self._router.get_provider(name) is not None
            },
            parse_fn=self._safe_parse,
        )

        return consensus_analyzer.analyze_with_consensus(
            messages=llm_messages,
            provider_names=providers,
        )

    def _safe_parse(self, raw_text: str) -> dict[str, Any]:
        """Parse LLM response text, returning empty dict on failure.

        Args:
            raw_text: Raw response text.

        Returns:
            Parsed prediction dict or empty dict on failure.
        """
        try:
            return self._parse_response(raw_text)
        except (ResponseParsingError, Exception):
            return {}

    def _parse_market_response(self, raw_text: str) -> dict[str, Any]:
        """Parse and validate the market analysis response into a dict.

        Raises:
            ResponseParsingError: If JSON extraction or validation fails.
        """
        json_str = _extract_json_from_text(raw_text)

        try:
            result = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise ResponseParsingError(
                f"Failed to parse market analysis JSON: {exc}. "
                f"Extracted text: {json_str[:200]}"
            ) from exc

        if not isinstance(result, dict):
            raise ResponseParsingError(
                f"Expected JSON object (dict), got {type(result).__name__}"
            )

        required_market_fields = [
            "market_trend",
            "risk_assessment",
            "sector_outlook",
        ]
        missing = [f for f in required_market_fields if f not in result]
        if missing:
            raise ResponseParsingError(f"Missing required market fields: {missing}")

        logger.debug("Parsed market response with %d fields", len(result))
        return result

    def _call_llm(
        self,
        messages: list[dict[str, str]],
        symbol: str = "",
        analysis_type: str = "stock_analysis",
    ) -> str:
        """Call an LLM provider via the router.

        Converts prompt dict messages to LLMMessage format and routes
        the request through the LLM router with fallback support.

        Args:
            messages: List of message dicts with ``role`` and ``content``.
            symbol: Stock symbol for usage tracking.
            analysis_type: Analysis type for usage tracking.

        Returns:
            Raw text content from the LLM response.

        Raises:
            AnalyzerError: If all providers fail.
        """
        max_tokens = self._model_cfg.get("max_tokens", 4096)
        temperature = self._model_cfg.get("temperature", 0.3)

        llm_messages = _dict_messages_to_llm(messages)

        try:
            response = self._router.complete(
                messages=llm_messages,
                caller=f"stock_analyzer.{analysis_type}",
                max_tokens=max_tokens,
                temperature=temperature,
                symbol=symbol,
                analysis_type=analysis_type,
            )

            # Retry once with doubled max_tokens on suspiciously short truncation
            if (
                response.finish_reason == "length"
                and response.output_tokens < max_tokens // 2
            ):
                retry_tokens = max_tokens * 2
                logger.warning(
                    "Response truncated at %d/%d tokens for %s, "
                    "retrying with max_tokens=%d",
                    response.output_tokens,
                    max_tokens,
                    symbol,
                    retry_tokens,
                )
                response = self._router.complete(
                    messages=llm_messages,
                    caller=f"stock_analyzer.{analysis_type}",
                    max_tokens=retry_tokens,
                    temperature=temperature,
                    symbol=symbol,
                    analysis_type=analysis_type,
                )

            logger.debug(
                "LLM response received: %d chars from %s",
                len(response.text),
                response.provider.value,
            )
            return response.text
        except LLMProviderError as exc:
            raise AnalyzerError(f"LLM call failed: {exc}") from exc

    def _parse_response(self, raw_text: str) -> dict[str, Any]:
        """Parse and validate LLM response text into a prediction dict.

        Handles responses that may contain markdown code blocks
        (``````json ... ``````) or raw JSON text.

        Args:
            raw_text: Raw text response from LLM.

        Returns:
            Parsed and validated prediction dictionary with all required
            fields from the output schema.

        Raises:
            ResponseParsingError: If JSON extraction or validation fails.
        """
        json_str = _extract_json_from_text(raw_text)

        try:
            prediction = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise ResponseParsingError(
                f"Failed to parse JSON from LLM response: {exc}. "
                f"Extracted text: {json_str[:200]}"
            ) from exc

        if not isinstance(prediction, dict):
            raise ResponseParsingError(
                f"Expected JSON object (dict), got {type(prediction).__name__}"
            )

        # Validate required fields
        missing_fields = [
            field for field in self._required_fields if field not in prediction
        ]
        if missing_fields:
            raise ResponseParsingError(
                f"Missing required fields in prediction: {missing_fields}"
            )

        logger.debug("Parsed prediction with %d fields", len(prediction))
        return prediction


def _dict_messages_to_llm(
    messages: list[dict[str, str]],
) -> list[LLMMessage]:
    """Convert dict-format messages to LLMMessage objects.

    Args:
        messages: List of {"role": ..., "content": ...} dicts.

    Returns:
        List of LLMMessage instances.
    """
    return [LLMMessage(role=msg["role"], content=msg["content"]) for msg in messages]


def _extract_json_from_text(text: str) -> str:
    """Extract JSON from text (```json block, ``` block, or raw braces).

    Raises:
        ResponseParsingError: If no JSON content can be found.
    """
    # Strategy 1: ```json ... ``` block
    match = re.search(r"```json\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Strategy 2: generic ``` ... ``` block
    match = re.search(r"```\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Strategy 2b: unclosed markdown fence (truncated response) — strip
    # the opening fence so brace-matching below can still find JSON.
    fence_match = re.search(r"```(?:json)?\s*\n?", text)
    if fence_match:
        text = text[fence_match.end() :]

    # Strategy 3: raw JSON object (first { to last })
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        return text[first_brace : last_brace + 1]

    # Strategy 4: truncated JSON recovery — close open braces/brackets
    if first_brace != -1:
        fragment = text[first_brace:]
        repaired = _repair_truncated_json(fragment)
        if repaired:
            return repaired

    raise ResponseParsingError(
        f"No JSON content found in LLM response. Response preview: {text[:200]}"
    )


def _repair_truncated_json(fragment: str) -> str | None:
    """Attempt to repair truncated JSON by closing open braces and brackets.

    Returns repaired JSON string or None if repair is not feasible.
    """
    # Strip trailing incomplete string values (cut mid-string)
    fragment = re.sub(r',\s*"[^"]*$', "", fragment)
    fragment = re.sub(r':\s*"[^"]*$', ': ""', fragment)

    # Count open/close braces and brackets
    open_braces = fragment.count("{") - fragment.count("}")
    open_brackets = fragment.count("[") - fragment.count("]")

    if open_braces <= 0 and open_brackets <= 0:
        return None

    # Strip trailing comma before closing
    fragment = fragment.rstrip().rstrip(",")

    # Close in reverse order (brackets first, then braces)
    fragment += "]" * open_brackets + "}" * open_braces

    # Validate the repair actually produces parseable JSON
    try:
        json.loads(fragment)
        logger.warning(
            "Repaired truncated JSON: closed %d braces, %d brackets",
            open_braces,
            open_brackets,
        )
        return fragment
    except json.JSONDecodeError:
        return None
