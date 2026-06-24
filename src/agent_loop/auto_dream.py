"""Post-market memory distillation (autoDream).

Runs at 15:30 CST daily to extract actionable lessons from the day's
trading decisions. Reads decisions from ``data/decisions.db``, fetches
closing prices, evaluates direction correctness, and asks an LLM to
distill 3 executable takeaways.

Part of the feedback loop: decisions -> outcomes -> lessons -> better
future decisions.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("agent_loop.auto_dream")

_DB_PATH = "data/decisions.db"

_DREAM_PROMPT_TEMPLATE = (
    "你是一个交易复盘专家。今天 ({date}) 共做了 {total} 个交易决策，"
    "其中 {wins} 个方向正确，{losses} 个方向错误。\n\n"
    "以下是每个决策的详情：\n{details}\n\n"
    "请分析：\n"
    "1. 哪些决策对了？为什么对了？\n"
    "2. 哪些决策错了？为什么错了？\n"
    "3. 总结 3 条可执行的经验教训（不要空话，要具体到可以改变下次决策的规则）。\n\n"
    "输出格式（JSON）：\n"
    "```json\n"
    "{{\n"
    '  "analysis": "完整分析文本",\n'
    '  "lessons": ["教训1", "教训2", "教训3"]\n'
    "}}\n"
    "```"
)


@dataclass
class DreamResult:
    """Result of a single autoDream distillation session.

    Attributes:
        date: The trading date analyzed (YYYY-MM-DD).
        total_decisions: Number of decisions made that day.
        wins: Number of directionally correct decisions.
        losses: Number of directionally incorrect decisions.
        lessons: Extracted actionable lessons (typically 3).
        raw_analysis: Full LLM analysis text.
    """

    date: str
    total_decisions: int
    wins: int
    losses: int
    lessons: list[str] = field(default_factory=list)
    raw_analysis: str = ""


@dataclass
class _DecisionRow:
    """Internal representation of a decision row from the DB."""

    proposal_id: str
    symbol: str
    action: str
    confidence: float
    entry_price: float
    decided_at: str
    sector: str


class AutoDream:
    """Post-market experience extractor.

    Reads the day's decisions, fetches closing prices, evaluates
    correctness, and distills lessons via LLM.

    Args:
        db_path: Path to decisions.db.
        llm_gateway: LLMGateway instance; lazy-loaded if None.
        quote_manager: RealtimeQuoteManager; lazy-loaded if None.
    """

    def __init__(
        self,
        db_path: str = _DB_PATH,
        llm_gateway: Any | None = None,
        quote_manager: Any | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._gateway = llm_gateway
        self._quote_manager = quote_manager

    def _get_gateway(self) -> Any:
        """Lazy-load LLMGateway."""
        if self._gateway is None:
            from src.web.dependencies import get_llm_gateway

            self._gateway = get_llm_gateway()
        return self._gateway

    def _get_quote_manager(self) -> Any:
        """Lazy-load RealtimeQuoteManager."""
        if self._quote_manager is None:
            from src.web.dependencies import get_realtime_quote_manager

            self._quote_manager = get_realtime_quote_manager()
        return self._quote_manager

    def distill_daily(self, date_str: str) -> DreamResult:
        """Run post-market distillation for a given trading date.

        Steps:
            1. Read all decisions from decisions.db for the given date.
            2. Fetch actual closing prices for each symbol.
            3. Compute direction_correct for each decision.
            4. Call LLM with a structured prompt.
            5. Parse LLM response into lessons.

        Args:
            date_str: Trading date in YYYY-MM-DD format.

        Returns:
            DreamResult with win/loss counts and extracted lessons.
        """
        logger.info("AutoDream distillation starting for %s", date_str)

        # 1. Read decisions
        decisions = self._read_decisions(date_str)
        if not decisions:
            logger.info("No decisions found for %s — nothing to distill", date_str)
            return DreamResult(
                date=date_str,
                total_decisions=0,
                wins=0,
                losses=0,
                raw_analysis="无决策记录",
            )

        # 2. Fetch closing prices
        closing_prices = self._fetch_closing_prices([d.symbol for d in decisions])

        # 3. Compute direction correctness
        wins = 0
        losses = 0
        details_lines: list[str] = []

        for d in decisions:
            close = closing_prices.get(d.symbol, 0.0)
            if close <= 0 or d.entry_price <= 0:
                direction = "未知"
            else:
                price_moved_up = close > d.entry_price
                is_long = d.action in ("buy", "add")
                correct = (is_long and price_moved_up) or (
                    not is_long and not price_moved_up
                )
                if correct:
                    wins += 1
                    direction = "正确"
                else:
                    losses += 1
                    direction = "错误"

            pnl_pct = (
                ((close - d.entry_price) / d.entry_price * 100)
                if d.entry_price > 0 and close > 0
                else 0.0
            )
            details_lines.append(
                f"- {d.symbol} ({d.sector}): {d.action} @ {d.entry_price:.2f}, "
                f"收盘 {close:.2f}, 涨跌 {pnl_pct:+.2f}%, "
                f"信心 {d.confidence:.0%}, 方向{direction}"
            )

        # 4. Call LLM
        total = len(decisions)
        prompt = _DREAM_PROMPT_TEMPLATE.format(
            date=date_str,
            total=total,
            wins=wins,
            losses=losses,
            details="\n".join(details_lines),
        )

        lessons, raw_analysis = self._call_llm(prompt)

        result = DreamResult(
            date=date_str,
            total_decisions=total,
            wins=wins,
            losses=losses,
            lessons=lessons,
            raw_analysis=raw_analysis,
        )

        # Write lessons to Redis for next day's prompt
        if result.lessons:
            try:
                import redis as redis_lib

                r = redis_lib.Redis(
                    host="redis", port=6379, db=0, decode_responses=True
                )
                r.set(
                    "agent:distilled_lessons",
                    json.dumps(result.lessons, ensure_ascii=False),
                    ex=172800,  # 48h TTL
                )
            except Exception:
                pass

        logger.info(
            "AutoDream complete: %d decisions, %d wins, %d losses, %d lessons",
            total,
            wins,
            losses,
            len(lessons),
        )
        return result

    # ── Data access ──────────────────────────────────────────

    def _read_decisions(self, date_str: str) -> list[_DecisionRow]:
        """Read all decisions for a given date from decisions.db.

        Args:
            date_str: Date string in YYYY-MM-DD format.

        Returns:
            List of _DecisionRow objects.
        """
        if not self._db_path.exists():
            logger.warning("decisions.db not found at %s", self._db_path)
            return []

        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT proposal_id, symbol, action, confidence,
                       entry_price, decided_at, sector
                FROM decisions
                WHERE decided_at LIKE ?
                ORDER BY decided_at
                """,
                (f"{date_str}%",),
            ).fetchall()
            conn.close()
        except Exception:
            logger.exception("Failed to read decisions for %s", date_str)
            return []

        results: list[_DecisionRow] = []
        for row in rows:
            results.append(
                _DecisionRow(
                    proposal_id=row["proposal_id"] or "",
                    symbol=row["symbol"] or "",
                    action=row["action"] or "",
                    confidence=float(row["confidence"] or 0),
                    entry_price=float(row["entry_price"] or 0),
                    decided_at=row["decided_at"] or "",
                    sector=row["sector"] or "",
                )
            )

        logger.info("Read %d decisions for %s", len(results), date_str)
        return results

    def _fetch_closing_prices(self, symbols: list[str]) -> dict[str, float]:
        """Fetch current/closing prices for a list of symbols.

        Args:
            symbols: List of 6-digit stock codes.

        Returns:
            Dict mapping symbol -> closing price.
        """
        qm = self._get_quote_manager()
        if qm is None:
            logger.warning("No quote manager — returning empty prices")
            return {}

        prices: dict[str, float] = {}
        unique_symbols = list(set(symbols))

        for sym in unique_symbols:
            try:
                quote = qm.get_single_quote(sym)
                price = float(quote.get("price", 0))
                if price > 0:
                    prices[sym] = price
            except Exception:
                logger.warning("Failed to fetch price for %s", sym)

        logger.info(
            "Fetched closing prices for %d/%d symbols",
            len(prices),
            len(unique_symbols),
        )
        return prices

    # ── LLM integration ──────────────────────────────────────

    def _call_llm(self, prompt: str) -> tuple[list[str], str]:
        """Call LLM to analyze decisions and extract lessons.

        Args:
            prompt: The formatted analysis prompt.

        Returns:
            Tuple of (lessons list, raw analysis text).
        """
        gateway = self._get_gateway()
        if gateway is None:
            logger.warning("No LLM gateway — returning empty analysis")
            return [], "LLM 网关不可用"

        try:
            from src.llm.base import LLMMessage

            messages = [
                LLMMessage(role="system", content="你是交易复盘专家。输出 JSON。"),
                LLMMessage(role="user", content=prompt),
            ]
            response = gateway.complete(
                messages,
                caller="auto_dream",
                max_tokens=2048,
                temperature=0.3,
            )
            raw_text = response.text if hasattr(response, "text") else str(response)
            return self._parse_llm_response(raw_text), raw_text
        except Exception:
            logger.exception("LLM call failed during autoDream")
            return [], "LLM 调用失败"

    @staticmethod
    def _parse_llm_response(text: str) -> list[str]:
        """Parse LLM JSON response to extract lessons list.

        Handles both clean JSON and JSON embedded in markdown code
        fences.

        Args:
            text: Raw LLM response text.

        Returns:
            List of lesson strings. Empty list on parse failure.
        """
        # Strip markdown code fences if present
        cleaned = text.strip()
        if "```json" in cleaned:
            start = cleaned.index("```json") + len("```json")
            end = cleaned.index("```", start)
            cleaned = cleaned[start:end].strip()
        elif "```" in cleaned:
            start = cleaned.index("```") + 3
            end = cleaned.index("```", start)
            cleaned = cleaned[start:end].strip()

        try:
            data = json.loads(cleaned)
            lessons = data.get("lessons", [])
            if isinstance(lessons, list):
                return [str(item) for item in lessons]
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse LLM response as JSON")

        return []
