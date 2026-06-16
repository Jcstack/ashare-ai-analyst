"""SignalRuleEngine — L1-L4 hierarchical signal filtering rules.

Evaluates ``MarketSignal`` instances against a prioritised rule hierarchy:

- **L1 (System)**: Cannot be overridden — e.g., noise filter, empty-asset filter.
- **L2 (Risk)**: From ``RiskOverlayEngine`` — e.g., block EXTREME + low confidence.
- **L3 (Phase)**: From ``PhaseEngine`` — e.g., phase-based signal restrictions.
- **L4 (User)**: User preferences — e.g., minimum confidence threshold.

Rules are evaluated top-down (L1 first).  The first blocking rule wins, and
the signal is rejected with a structured result describing which rule
matched and why.

Part of v20.0 Market Intelligence Phase 4.
"""

from __future__ import annotations

from typing import Any, Callable

from src.utils.config import load_config
from src.utils.logger import get_logger
from src.web.schemas.market_signal import MarketSignal, SignalType

logger = get_logger("market_intelligence.signal_rule_engine")

# ---------------------------------------------------------------------------
# Rule level constants
# ---------------------------------------------------------------------------

L1_SYSTEM = "L1_system"
L2_RISK = "L2_risk"
L3_PHASE = "L3_phase"
L4_USER = "L4_user"

_RULE_LEVELS = (L1_SYSTEM, L2_RISK, L3_PHASE, L4_USER)

# Signal types exempt from the empty-assets filter (system / macro scope)
_EMPTY_ASSETS_EXEMPT_TYPES: set[str] = {
    SignalType.SYSTEM_ALERT.value,
    SignalType.S8_MACRO_DRIVEN.value,
    SignalType.S9_REGIME_CHANGE.value,
}


# ---------------------------------------------------------------------------
# Built-in L1 system rule implementations
# ---------------------------------------------------------------------------


def _noise_filter(
    signal: MarketSignal, _context: dict | None, *, min_confidence: float
) -> bool:
    """Return True (block) if confidence is below the noise threshold."""
    return signal.confidence_score < min_confidence


def _empty_assets_filter(
    signal: MarketSignal,
    _context: dict | None,
    *,
    exempt_types: set[str],
) -> bool:
    """Return True (block) if signal has no assets and is not an exempt type."""
    if signal.signal_type.value in exempt_types:
        return False
    return len(signal.assets) == 0


# ---------------------------------------------------------------------------
# SignalRuleEngine
# ---------------------------------------------------------------------------


class SignalRuleEngine:
    """Hierarchical signal filtering engine with L1-L4 rule levels.

    Rules at lower levels have higher priority.  Evaluation stops at the
    first blocking rule (short-circuit), and the result indicates which
    rule caused the block.

    Usage::

        engine = SignalRuleEngine()
        result = engine.evaluate(signal, context)
        if not result["allowed"]:
            logger.info("Blocked by %s: %s", result["rule_level"], result["reason"])
    """

    def __init__(self) -> None:
        """Initialize with default L1 system rules.

        Loads additional rules from ``config/signal_rules.yaml`` if the file
        exists, otherwise uses built-in defaults.
        """
        self._rules: dict[str, list[dict[str, Any]]] = {
            level: [] for level in _RULE_LEVELS
        }
        self._load_system_rules()
        logger.info(
            "SignalRuleEngine initialized with %d rules across %d levels",
            sum(len(r) for r in self._rules.values()),
            len(_RULE_LEVELS),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        signal: MarketSignal,
        context: dict | None = None,
    ) -> dict[str, Any]:
        """Evaluate *signal* against all rules in L1->L2->L3->L4 order.

        The first matching block rule wins (higher-priority levels are checked
        first).  If no rule blocks, the signal is allowed.

        Args:
            signal: The ``MarketSignal`` to evaluate.
            context: Optional context dict that rules may inspect (e.g.,
                ``{"phase": MarketPhase, "risk_level": RiskLevel}``).

        Returns:
            A dict with keys:
            - ``allowed`` (bool): Whether the signal passes all rules.
            - ``blocked_by`` (str | None): Name of the blocking rule.
            - ``rule_level`` (str | None): Level of the blocking rule.
            - ``reason`` (str): Human-readable explanation.
        """
        for level in _RULE_LEVELS:
            for rule in self._rules[level]:
                condition: Callable[..., bool] = rule["condition"]
                try:
                    blocked = condition(signal, context)
                except Exception:
                    logger.warning(
                        "Rule '%s' (%s) raised an exception; treating as non-blocking",
                        rule["name"],
                        level,
                        exc_info=True,
                    )
                    continue

                if blocked:
                    return {
                        "allowed": False,
                        "blocked_by": rule["name"],
                        "rule_level": level,
                        "reason": rule["reason"],
                    }

        return {
            "allowed": True,
            "blocked_by": None,
            "rule_level": None,
            "reason": "all rules passed",
        }

    def add_rule(
        self,
        level: str,
        name: str,
        condition: Callable[[MarketSignal, dict | None], bool],
        reason: str,
    ) -> None:
        """Add a custom rule at the specified level.

        Args:
            level: One of ``"L1_system"``, ``"L2_risk"``, ``"L3_phase"``,
                ``"L4_user"``.
            name: Unique rule name (used in evaluation results).
            condition: A callable ``(signal, context) -> bool``.  Return
                *True* to **block** the signal.
            reason: Human-readable explanation attached when this rule blocks.

        Raises:
            ValueError: If *level* is not a recognised rule level.
        """
        if level not in _RULE_LEVELS:
            raise ValueError(
                f"Invalid rule level '{level}'; expected one of: {', '.join(_RULE_LEVELS)}"
            )

        self._rules[level].append(
            {
                "name": name,
                "condition": condition,
                "reason": reason,
            }
        )
        logger.info("Rule added: %s at level %s", name, level)

    def get_rules(self) -> dict[str, list[dict[str, Any]]]:
        """Return all rules organised by level.

        Returns:
            Dict mapping level strings to lists of rule dicts.  Each rule
            dict has keys: ``name`` (str), ``reason`` (str).  The
            ``condition`` callable is excluded for serialisability.
        """
        result: dict[str, list[dict[str, Any]]] = {}
        for level in _RULE_LEVELS:
            result[level] = [
                {"name": r["name"], "reason": r["reason"]} for r in self._rules[level]
            ]
        return result

    # ------------------------------------------------------------------
    # Internal: system rule loading
    # ------------------------------------------------------------------

    def _load_system_rules(self) -> None:
        """Load L1 system rules from ``config/signal_rules.yaml``, falling
        back to built-in defaults when the file is absent or malformed."""
        min_confidence = 10.0
        exempt_types = set(_EMPTY_ASSETS_EXEMPT_TYPES)

        try:
            raw = load_config("signal_rules")
            rules_cfg = raw.get("signal_rules", {}).get("L1_system", [])

            for rule_cfg in rules_cfg:
                name = rule_cfg.get("name", "")
                if name == "noise_filter":
                    min_confidence = float(rule_cfg.get("min_confidence", 10))
                elif name == "empty_assets_filter":
                    configured_exempt = rule_cfg.get("exempt_types", [])
                    if configured_exempt:
                        exempt_types = set(configured_exempt)

            logger.info("Loaded L1 system rules from config/signal_rules.yaml")
        except FileNotFoundError:
            logger.warning(
                "config/signal_rules.yaml not found; using built-in L1 defaults"
            )
        except Exception:
            logger.warning(
                "Failed to parse config/signal_rules.yaml; using built-in L1 defaults",
                exc_info=True,
            )

        # Register the two default L1 rules
        self._rules[L1_SYSTEM].append(
            {
                "name": "noise_filter",
                "condition": lambda sig, ctx: _noise_filter(
                    sig, ctx, min_confidence=min_confidence
                ),
                "reason": f"Signal confidence below noise threshold ({min_confidence})",
            }
        )

        self._rules[L1_SYSTEM].append(
            {
                "name": "empty_assets_filter",
                "condition": lambda sig, ctx: _empty_assets_filter(
                    sig, ctx, exempt_types=exempt_types
                ),
                "reason": "Non-system signal with empty assets list",
            }
        )
