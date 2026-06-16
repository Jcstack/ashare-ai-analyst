"""Munger Mental Model Checklist — pre-decision safety checks.

Per PRD v34.0 FR-AD002: Forces every investment decision through
Munger/Buffett-inspired psychological bias checks.

Checks:
1. Safety Margin — is there enough margin of safety?
2. Circle of Competence — is this within the user's experience?
3. Inversion — what if we're wrong?
4. Incentive Bias — are all signals suspiciously aligned?
5. Anchoring — is the decision anchored to recent price moves?
6. Availability Bias — is there excessive media coverage?
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CheckItem:
    """Result of a single checklist check."""

    name: str
    question: str
    passed: bool
    severity: str  # "block" | "warn" | "info" | "pass"
    finding: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "question": self.question,
            "passed": self.passed,
            "severity": self.severity,
            "finding": self.finding,
            "details": self.details,
        }


@dataclass
class ChecklistResult:
    """Aggregate result of all checklist checks."""

    symbol: str
    name: str
    checks: list[CheckItem] = field(default_factory=list)
    overall_passed: bool = True
    block_count: int = 0
    warn_count: int = 0
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "checks": [c.to_dict() for c in self.checks],
            "overall_passed": self.overall_passed,
            "block_count": self.block_count,
            "warn_count": self.warn_count,
            "summary": self.summary,
        }


class MungerChecklist:
    """Applies Munger's mental model checklist to investment decisions.

    This is a rule-based safety check, not LLM-dependent.
    Each check uses quantitative thresholds where possible.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self._min_safety_margin_pct = cfg.get("min_safety_margin_pct", 10.0)
        self._max_recent_gain_pct = cfg.get("max_recent_gain_pct", 15.0)
        self._recent_gain_days = cfg.get("recent_gain_days", 5)
        self._max_news_count_24h = cfg.get("max_news_count_24h", 20)
        self._consensus_signal_threshold = cfg.get("consensus_signal_threshold", 5)
        self._max_worst_case_loss_pct = cfg.get("max_worst_case_loss_pct", 5.0)
        logger.info("MungerChecklist initialized")

    def check_safety_margin(
        self,
        current_price: float | None = None,
        fair_value: float | None = None,
    ) -> CheckItem:
        """Check 1: Is there enough margin of safety?"""
        if current_price is None or fair_value is None or fair_value <= 0:
            return CheckItem(
                name="安全边际",
                question="当前价格距离合理估值有多少安全边际？",
                passed=True,
                severity="info",
                finding="无估值数据，跳过安全边际检查",
            )

        margin_pct = (fair_value - current_price) / fair_value * 100

        if margin_pct >= self._min_safety_margin_pct:
            return CheckItem(
                name="安全边际",
                question="当前价格距离合理估值有多少安全边际？",
                passed=True,
                severity="pass",
                finding=f"安全边际{margin_pct:.1f}%，高于阈值{self._min_safety_margin_pct}%",
                details={"margin_pct": margin_pct},
            )

        severity = "block" if margin_pct < 0 else "warn"
        return CheckItem(
            name="安全边际",
            question="当前价格距离合理估值有多少安全边际？",
            passed=False,
            severity=severity,
            finding=(
                f"安全边际仅{margin_pct:.1f}%（阈值{self._min_safety_margin_pct}%），"
                f"{'已高于估值' if margin_pct < 0 else '安全边际不足'}"
            ),
            details={
                "margin_pct": margin_pct,
                "current_price": current_price,
                "fair_value": fair_value,
            },
        )

    def check_circle_of_competence(
        self,
        sector: str = "",
        traded_sectors: list[str] | None = None,
    ) -> CheckItem:
        """Check 2: Has the user traded this sector before?"""
        if not traded_sectors or not sector:
            return CheckItem(
                name="能力圈",
                question="用户是否理解这个行业？",
                passed=True,
                severity="info",
                finding="无交易历史数据，跳过能力圈检查",
            )

        if sector in traded_sectors:
            return CheckItem(
                name="能力圈",
                question="用户是否理解这个行业？",
                passed=True,
                severity="pass",
                finding=f"用户有{sector}行业交易经验",
            )

        return CheckItem(
            name="能力圈",
            question="用户是否理解这个行业？",
            passed=False,
            severity="warn",
            finding=f"用户未交易过{sector}行业，请确认是否理解该行业逻辑",
            details={"sector": sector, "known_sectors": traded_sectors},
        )

    def check_inversion(
        self,
        worst_case_loss_pct: float | None = None,
    ) -> CheckItem:
        """Check 3: What if we're wrong? (inversion thinking)"""
        if worst_case_loss_pct is None:
            return CheckItem(
                name="逆向思维",
                question="如果判断错误，最坏情况是什么？",
                passed=True,
                severity="info",
                finding="无风险数据，需手动评估最坏情况",
            )

        if abs(worst_case_loss_pct) <= self._max_worst_case_loss_pct:
            return CheckItem(
                name="逆向思维",
                question="如果判断错误，最坏情况是什么？",
                passed=True,
                severity="pass",
                finding=f"最坏损失{worst_case_loss_pct:.1f}%，在可接受范围内",
                details={"worst_case_loss_pct": worst_case_loss_pct},
            )

        return CheckItem(
            name="逆向思维",
            question="如果判断错误，最坏情况是什么？",
            passed=False,
            severity="warn",
            finding=(
                f"最坏损失{worst_case_loss_pct:.1f}%，超过单笔风险阈值"
                f"{self._max_worst_case_loss_pct}%，建议设置强制止损"
            ),
            details={"worst_case_loss_pct": worst_case_loss_pct},
        )

    def check_incentive_bias(
        self,
        bullish_signals: int = 0,
        bearish_signals: int = 0,
    ) -> CheckItem:
        """Check 4: Are all signals pointing the same direction?"""
        total = bullish_signals + bearish_signals
        if total == 0:
            return CheckItem(
                name="激励偏差",
                question="是否所有信号都指向同一方向？",
                passed=True,
                severity="info",
                finding="无信号数据",
            )

        if total >= self._consensus_signal_threshold and bearish_signals == 0:
            return CheckItem(
                name="激励偏差",
                question="是否所有信号都指向同一方向？",
                passed=False,
                severity="warn",
                finding=(
                    f"全部{total}个信号均看多，零看空信号。"
                    "警惕共识陷阱——当所有人都看多时，风险最大"
                ),
                details={"bullish": bullish_signals, "bearish": bearish_signals},
            )

        if total >= self._consensus_signal_threshold and bullish_signals == 0:
            return CheckItem(
                name="激励偏差",
                question="是否所有信号都指向同一方向？",
                passed=False,
                severity="warn",
                finding=(
                    f"全部{total}个信号均看空。是否存在过度恐慌？考虑逆向投资机会"
                ),
                details={"bullish": bullish_signals, "bearish": bearish_signals},
            )

        return CheckItem(
            name="激励偏差",
            question="是否所有信号都指向同一方向？",
            passed=True,
            severity="pass",
            finding=f"信号多空分化: {bullish_signals}多 vs {bearish_signals}空",
            details={"bullish": bullish_signals, "bearish": bearish_signals},
        )

    def check_anchoring(
        self,
        recent_gain_pct: float | None = None,
    ) -> CheckItem:
        """Check 5: Is the decision anchored to recent price moves?"""
        if recent_gain_pct is None:
            return CheckItem(
                name="锚定效应",
                question="是否被近期价格锚定？",
                passed=True,
                severity="info",
                finding="无近期涨幅数据",
            )

        if abs(recent_gain_pct) <= self._max_recent_gain_pct:
            return CheckItem(
                name="锚定效应",
                question="是否被近期价格锚定？",
                passed=True,
                severity="pass",
                finding=f"近{self._recent_gain_days}日涨幅{recent_gain_pct:.1f}%，正常范围",
            )

        direction = "上涨" if recent_gain_pct > 0 else "下跌"
        return CheckItem(
            name="锚定效应",
            question="是否被近期价格锚定？",
            passed=False,
            severity="warn",
            finding=(
                f"近{self._recent_gain_days}日{direction}{abs(recent_gain_pct):.1f}%，"
                f"动量可能衰竭或反转，避免被近期走势锚定"
            ),
            details={"recent_gain_pct": recent_gain_pct},
        )

    def check_availability_bias(
        self,
        news_count_24h: int = 0,
    ) -> CheckItem:
        """Check 6: Is there excessive media coverage (availability bias)?"""
        if news_count_24h <= 5:
            return CheckItem(
                name="可得性偏差",
                question="是否被热门新闻过度影响？",
                passed=True,
                severity="pass",
                finding="新闻关注度正常",
            )

        if news_count_24h >= self._max_news_count_24h:
            return CheckItem(
                name="可得性偏差",
                question="是否被热门新闻过度影响？",
                passed=False,
                severity="warn",
                finding=(
                    f"24小时内{news_count_24h}条相关新闻，"
                    "媒体关注度过高，警惕信息泡沫和跟风效应"
                ),
                details={"news_count_24h": news_count_24h},
            )

        return CheckItem(
            name="可得性偏差",
            question="是否被热门新闻过度影响？",
            passed=True,
            severity="info",
            finding=f"24小时内{news_count_24h}条新闻，关注度中等",
            details={"news_count_24h": news_count_24h},
        )

    # ------------------------------------------------------------------
    # Full checklist
    # ------------------------------------------------------------------

    def run_checklist(
        self,
        symbol: str,
        name: str = "",
        *,
        current_price: float | None = None,
        fair_value: float | None = None,
        sector: str = "",
        traded_sectors: list[str] | None = None,
        worst_case_loss_pct: float | None = None,
        bullish_signals: int = 0,
        bearish_signals: int = 0,
        recent_gain_pct: float | None = None,
        news_count_24h: int = 0,
    ) -> ChecklistResult:
        """Run the full Munger checklist for a stock.

        Returns ChecklistResult with all check outcomes.
        """
        checks = [
            self.check_safety_margin(current_price, fair_value),
            self.check_circle_of_competence(sector, traded_sectors),
            self.check_inversion(worst_case_loss_pct),
            self.check_incentive_bias(bullish_signals, bearish_signals),
            self.check_anchoring(recent_gain_pct),
            self.check_availability_bias(news_count_24h),
        ]

        block_count = sum(1 for c in checks if c.severity == "block")
        warn_count = sum(1 for c in checks if c.severity == "warn")
        overall_passed = block_count == 0

        # Build summary
        if block_count:
            summary = f"芒格检查未通过: {block_count}项阻断, {warn_count}项警告"
        elif warn_count:
            summary = f"芒格检查通过但有{warn_count}项警告，请审慎决策"
        else:
            summary = "芒格检查全部通过"

        result = ChecklistResult(
            symbol=symbol,
            name=name,
            checks=checks,
            overall_passed=overall_passed,
            block_count=block_count,
            warn_count=warn_count,
            summary=summary,
        )

        logger.info(
            "Munger checklist for %s: %s (blocks=%d, warns=%d)",
            symbol,
            "PASS" if overall_passed else "FAIL",
            block_count,
            warn_count,
        )
        return result
