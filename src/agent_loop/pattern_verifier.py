"""LLM-powered verification of intraday patterns.

High-severity patterns (>0.7) are verified before pushing to users.
This reduces false positive alerts that erode user trust.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("agent_loop.pattern_verifier")

_VERIFICATION_PROMPT_SYSTEM = """\
你是A股日内形态验证专家。你的工作是判断系统自动检测到的日内形态是否真实可靠。

## 验证维度（按重要性排序）
1. 成交量验证：形态必须有对应的成交量配合（放量突破/缩量回调），无量形态大概率是假信号
2. A股特殊规则：T+1（买入当日不能卖出）、涨跌停板（主板±10%/创业板±20%）、集合竞价
3. 游资/主力操作识别：尾盘突然拉升可能是游资做收盘价，低开高走可能是主力洗盘
4. 大盘环境：个股形态在大盘下跌环境中的可靠性更低
5. 历史完成率：该类形态的历史成功率（如冲高回落后继续下跌的概率）

## 判断标准
- is_genuine=true: 成交量支持 + 非明显操纵 + 环境匹配
- is_genuine=false: 无量异动 / 疑似操纵 / 环境不支持
- adjusted_severity 应该 ≤ 原始severity（验证只会降低不会抬高严重度）

输出严格 JSON，无附加文本。所有文本中文。"""

_VERIFICATION_PROMPT_USER = """\
## 待验证形态
股票: {symbol}
形态名称: {pattern_name}（类型: {pattern_type}）
方向: {direction}
系统检测严重度: {severity:.0%}（0-100%，越高越值得关注）
形态描述: {description}

## 技术因子（系统计算值）
{factors_text}

## 近期分钟线摘要
{minute_data_summary}

## 持仓状态
{held_text}（如果持有该股，建议应考虑T+1约束）

## 输出 JSON
{{
    "is_genuine": true或false,
    "adjusted_severity": 0.0-1.0（不应高于原始{severity:.2f}），
    "action_advice": "具体操作建议，必须包含触发价位（如'若跌破¥XX.XX，建议...'）",
    "reasoning": "判断理由（2-3句话，必须引用至少1个技术因子数值作为依据）",
    "false_signal_risk": "high|medium|low"
}}"""

# Pattern type -> Chinese name
_PATTERN_NAMES: dict[str, str] = {
    "high_reversal": "冲高回落",
    "gap_down_rally": "低开高走",
    "late_rally": "尾盘拉升",
    "late_dump": "尾盘跳水",
    "volume_price_divergence": "量价背离",
    "vwap_rejection": "VWAP压制/支撑",
    "volume_dry_up": "缩量",
    "opening_drive": "开盘冲击",
}


class PatternVerifier:
    """LLM-powered verification of intraday patterns.

    High-severity patterns (>0.7) are verified before pushing to users.
    This reduces false positive alerts that erode user trust.
    """

    def __init__(
        self,
        llm_router: Any | None = None,
        cache_ttl_seconds: int = 7200,
    ) -> None:
        self._llm = llm_router
        self._cache: dict[str, tuple[dict, float]] = {}  # key -> (result, timestamp)
        self._cache_ttl = cache_ttl_seconds

    async def verify(
        self,
        pattern: dict,
        symbol: str,
        minute_data_summary: str,
        portfolio_held: bool = False,
    ) -> dict:
        """Verify a pattern via LLM.

        Args:
            pattern: Pattern dict with keys: pattern_type, name_cn,
                severity, direction, description, factors
            symbol: Stock symbol
            minute_data_summary: Summary of recent minute bars
            portfolio_held: Whether user holds this stock

        Returns:
            dict with: is_genuine (bool), adjusted_severity (float),
            action_advice (str), reasoning (str)
        """
        pattern_type = pattern.get("pattern_type", "unknown")
        severity = pattern.get("severity", 0.0)

        # Check in-memory cache first
        cache_key = self._make_cache_key(symbol, pattern_type)
        cached = self._get_cached(cache_key)
        if cached is not None:
            logger.debug("Pattern verify cache hit: %s %s", symbol, pattern_type)
            return cached

        # Check Redis cache
        redis_result = await self._get_redis_cached(cache_key)
        if redis_result is not None:
            self._set_cached(cache_key, redis_result)
            return redis_result

        # No LLM router available — pass through
        if self._llm is None:
            logger.warning(
                "No LLM router for pattern verification, passing through: %s %s",
                symbol,
                pattern_type,
            )
            return self._passthrough_result(severity)

        # Build prompt
        factors = pattern.get("factors", {})
        factors_text = "\n".join(
            f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}"
            for k, v in factors.items()
        )
        if not factors_text:
            factors_text = "  无附加数据"

        cn_name = _PATTERN_NAMES.get(pattern_type, pattern_type)
        user_prompt = _VERIFICATION_PROMPT_USER.format(
            symbol=symbol,
            pattern_name=cn_name,
            pattern_type=pattern_type,
            direction="看多" if pattern.get("direction") == "bullish" else "看空",
            severity=severity,
            description=pattern.get("description", ""),
            factors_text=factors_text,
            minute_data_summary=minute_data_summary or "无数据",
            held_text="是" if portfolio_held else "否",
        )

        try:
            from src.llm.base import LLMMessage

            messages = [
                LLMMessage(role="system", content=_VERIFICATION_PROMPT_SYSTEM),
                LLMMessage(role="user", content=user_prompt),
            ]

            # Run LLM call with timeout
            response = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._llm.complete(
                        messages=messages,
                        max_tokens=512,
                        temperature=0.2,
                        caller="pattern_verifier",
                        symbol=symbol,
                        analysis_type="pattern_verification",
                    ),
                ),
                timeout=15.0,
            )

            result = self._parse_response(response.text, severity)

            # Cache result
            self._set_cached(cache_key, result)
            await self._set_redis_cached(cache_key, result)

            logger.info(
                "Pattern verified: %s %s — genuine=%s, adjusted_severity=%.2f",
                symbol,
                pattern_type,
                result["is_genuine"],
                result["adjusted_severity"],
            )
            return result

        except TimeoutError:
            logger.warning(
                "Pattern verification timed out for %s %s, passing through",
                symbol,
                pattern_type,
            )
            return self._passthrough_result(severity)
        except Exception as exc:
            logger.warning(
                "Pattern verification failed for %s %s: %s, passing through",
                symbol,
                pattern_type,
                exc,
            )
            return self._passthrough_result(severity)

    def _make_cache_key(self, symbol: str, pattern_type: str) -> str:
        """Build cache key with today's date."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        date_str = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
        return f"pattern_verify:{date_str}:{symbol}:{pattern_type}"

    def _get_cached(self, key: str) -> dict | None:
        """Return cached result if still valid."""
        entry = self._cache.get(key)
        if entry is None:
            return None
        result, ts = entry
        if time.time() - ts > self._cache_ttl:
            del self._cache[key]
            return None
        return result

    def _set_cached(self, key: str, result: dict) -> None:
        """Store result in in-memory cache."""
        self._cache[key] = (result, time.time())

    async def _get_redis_cached(self, key: str) -> dict | None:
        """Try to load cached verification from Redis."""
        try:
            import redis as redis_mod

            from src.utils.config import load_config

            broker = (
                load_config("openclaw")
                .get("celery", {})
                .get("broker_url", "redis://redis:6379/0")
            )
            client = redis_mod.from_url(broker, decode_responses=True)
            raw = client.get(key)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        return None

    async def _set_redis_cached(self, key: str, result: dict) -> None:
        """Store verification result in Redis."""
        try:
            import redis as redis_mod

            from src.utils.config import load_config

            broker = (
                load_config("openclaw")
                .get("celery", {})
                .get("broker_url", "redis://redis:6379/0")
            )
            client = redis_mod.from_url(broker, decode_responses=True)
            client.set(key, json.dumps(result, ensure_ascii=False), ex=self._cache_ttl)
        except Exception as exc:
            logger.debug("Failed to cache verification in Redis: %s", exc)

    @staticmethod
    def _passthrough_result(severity: float) -> dict:
        """Default result when verification is unavailable."""
        return {
            "is_genuine": True,
            "adjusted_severity": severity,
            "action_advice": "",
            "reasoning": "LLM验证不可用，使用原始信号",
        }

    @staticmethod
    def _parse_response(text: str, original_severity: float) -> dict:
        """Parse LLM JSON response, with fallback for malformed output."""
        # Strip markdown code fences if present
        cleaned = text.strip()
        if cleaned.startswith("```"):
            # Remove ```json ... ``` wrapper
            lines = cleaned.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM verification response, passing through")
            return {
                "is_genuine": True,
                "adjusted_severity": original_severity,
                "action_advice": "",
                "reasoning": "LLM返回格式异常，使用原始信号",
            }

        # Validate and clamp fields
        is_genuine = bool(data.get("is_genuine", True))
        adjusted = float(data.get("adjusted_severity", original_severity))
        adjusted = max(0.0, min(1.0, adjusted))

        return {
            "is_genuine": is_genuine,
            "adjusted_severity": adjusted,
            "action_advice": str(data.get("action_advice", "")),
            "reasoning": str(data.get("reasoning", "")),
        }
