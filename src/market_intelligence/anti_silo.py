"""AntiSiloEngine — diversity injection to prevent information echo chambers.

Injects contrarian views, cross-sector signals, and emerging topics into a
user's signal feed to break filter bubbles.  The engine operates on
``MarketSignal`` lists and marks every injected signal with
``is_injection=True`` plus a human-readable ``injection_reason``.

Part of v20.0 Market Intelligence Phase 4.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone

from src.utils.logger import get_logger
from src.web.schemas.market_signal import MarketSignal, SignalType

logger = get_logger("market_intelligence.anti_silo")

# ---------------------------------------------------------------------------
# Diversity-level -> injection percentage mapping
# ---------------------------------------------------------------------------

_DIVERSITY_QUOTAS: dict[str, float] = {
    "low": 0.05,
    "medium": 0.15,
    "high": 0.30,
}

# Signal types that support contrarian view generation
_DIRECTIONAL_TYPES: set[SignalType] = {
    SignalType.S1_TREND,
    SignalType.S2_MOMENTUM_SHIFT,
}

# Signal types considered cross-market / macro scope
_MACRO_TYPES: set[SignalType] = {
    SignalType.S7_POLICY_DRIVEN,
    SignalType.S8_MACRO_DRIVEN,
    SignalType.S9_REGIME_CHANGE,
}


class AntiSiloEngine:
    """Diversity injection engine that augments signal feeds with contrarian
    views, cross-sector insights, and emerging topics.

    Each injected signal is annotated with ``is_injection=True`` and an
    ``injection_reason`` string describing why the signal was added.

    Parameters
    ----------
    diversity_level:
        One of ``"low"`` (5%), ``"medium"`` (15%), ``"high"`` (30%).
        Controls the injection quota as a percentage of the input signal count.
    """

    def __init__(self, diversity_level: str = "medium") -> None:
        """Initialize with diversity level: low (5%), medium (15%), high (30%)."""
        self._diversity_level = self._validate_level(diversity_level)
        logger.info(
            "AntiSiloEngine initialized (diversity_level=%s)", self._diversity_level
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def inject(
        self,
        signals: list[MarketSignal],
        user_follows: dict | None = None,
    ) -> list[MarketSignal]:
        """Augment *signals* with diversity-injected items.

        Determines an injection quota based on the configured diversity level
        (minimum 1 signal), then scans the input list for candidates that
        qualify for injection according to the user's follow profile.  Also
        generates contrarian views for directional signals.

        Args:
            signals: Input signal list (not modified in-place).
            user_follows: Optional user follow config with keys:
                - ``stocks`` (list[str]): Followed stock codes.
                - ``signal_types`` (list[str]): Followed signal type values.
                - ``sectors`` (list[str]): Followed sector labels.

        Returns:
            A new list containing the original signals plus any injected ones.
        """
        if not signals:
            return list(signals)

        quota = max(
            1, math.ceil(len(signals) * _DIVERSITY_QUOTAS[self._diversity_level])
        )
        injected: list[MarketSignal] = []

        for signal in signals:
            if len(injected) >= quota:
                break

            # 1. Contrarian view for directional signals
            if signal.signal_type in _DIRECTIONAL_TYPES:
                contrarian = self.add_contrarian_view(signal)
                if contrarian is not None:
                    injected.append(contrarian)
                    if len(injected) >= quota:
                        break

            # 2. Out-of-interest-zone signals
            if self.should_inject(signal, user_follows):
                tagged = self._tag_injection(signal, user_follows)
                injected.append(tagged)

        logger.info(
            "AntiSiloEngine injected %d signals (quota=%d, diversity=%s)",
            len(injected),
            quota,
            self._diversity_level,
        )

        return list(signals) + injected

    def add_contrarian_view(self, signal: MarketSignal) -> MarketSignal | None:
        """Create a contrarian counterpoint for a directional signal.

        Only ``S1_TREND`` and ``S2_MOMENTUM_SHIFT`` signals support contrarian
        generation.  The counterpoint has its summary flipped and confidence
        discounted by 20%.

        Args:
            signal: The source signal.

        Returns:
            A new ``MarketSignal`` marked as injection, or *None* if the
            signal type does not support contrarian views.
        """
        if signal.signal_type not in _DIRECTIONAL_TYPES:
            return None

        contrarian = signal.model_copy(deep=True)
        contrarian.signal_id = str(uuid.uuid4())
        contrarian.is_injection = True
        contrarian.injection_reason = "contrarian_view"
        contrarian.confidence_score = max(0.0, signal.confidence_score * 0.8)
        contrarian.timestamp = datetime.now(timezone.utc)

        # Flip directional language in summary
        summary = signal.summary_short
        _FLIPS = {
            "bullish": "bearish",
            "bearish": "bullish",
            "up": "down",
            "down": "up",
            "long": "short",
            "short": "long",
        }
        for original, replacement in _FLIPS.items():
            if original in summary.lower():
                # Case-insensitive replacement preserving first-char case
                idx = summary.lower().index(original)
                old_word = summary[idx : idx + len(original)]
                new_word = (
                    replacement if old_word[0].islower() else replacement.capitalize()
                )
                summary = summary[:idx] + new_word + summary[idx + len(original) :]
                break

        prefix = "[counterpoint]"
        contrarian.summary_short = f"{prefix}{summary}"[:50]

        return contrarian

    def should_inject(
        self,
        signal: MarketSignal,
        user_follows: dict | None = None,
    ) -> bool:
        """Return True if *signal* is outside the user's typical interest zone.

        A signal qualifies for injection when:
        - Its assets are NOT in ``user_follows["stocks"]``, OR
        - Its ``signal_type`` is NOT in ``user_follows["signal_types"]``, OR
        - It is a macro/cross-market signal when user follows only domestic stocks.

        When ``user_follows`` is *None* (no profile), every signal qualifies.

        Args:
            signal: The signal to evaluate.
            user_follows: User follow config (see :meth:`inject`).

        Returns:
            *True* if the signal is outside the user's follow profile.
        """
        if user_follows is None:
            return True

        followed_stocks: list[str] = user_follows.get("stocks", [])
        followed_types: list[str] = user_follows.get("signal_types", [])
        followed_sectors: list[str] = user_follows.get("sectors", [])

        # Asset mismatch — signal targets stocks user doesn't follow
        if followed_stocks and signal.assets:
            if not any(asset in followed_stocks for asset in signal.assets):
                return True

        # Signal type mismatch
        if followed_types and signal.signal_type.value not in followed_types:
            return True

        # Cross-market insight — macro signal when user only follows domestic stocks
        if (
            signal.signal_type in _MACRO_TYPES
            and followed_stocks
            and not any(s in followed_sectors for s in ("macro", "global", "policy"))
        ):
            return True

        return False

    def set_diversity_level(self, level: str) -> None:
        """Update the diversity level.

        Args:
            level: One of ``"low"``, ``"medium"``, ``"high"``.

        Raises:
            ValueError: If *level* is not a recognised diversity level.
        """
        self._diversity_level = self._validate_level(level)
        logger.info(
            "AntiSiloEngine diversity_level updated to %s", self._diversity_level
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_level(level: str) -> str:
        """Validate and normalise a diversity level string."""
        normalised = level.lower().strip()
        if normalised not in _DIVERSITY_QUOTAS:
            raise ValueError(
                f"Invalid diversity_level '{level}'; expected one of: "
                f"{', '.join(sorted(_DIVERSITY_QUOTAS))}"
            )
        return normalised

    def _tag_injection(
        self,
        signal: MarketSignal,
        user_follows: dict | None,
    ) -> MarketSignal:
        """Create a copy of *signal* tagged with the appropriate injection reason."""
        tagged = signal.model_copy(deep=True)
        tagged.signal_id = str(uuid.uuid4())
        tagged.is_injection = True
        tagged.injection_reason = self._determine_reason(signal, user_follows)
        return tagged

    @staticmethod
    def _determine_reason(signal: MarketSignal, user_follows: dict | None) -> str:
        """Choose the most specific injection reason for a signal."""
        if user_follows is None:
            return "emerging_topic"

        followed_stocks = user_follows.get("stocks", [])
        followed_types = user_follows.get("signal_types", [])
        followed_sectors = user_follows.get("sectors", [])

        # Cross-market insight — macro signal for domestically-focused user
        if (
            signal.signal_type in _MACRO_TYPES
            and followed_stocks
            and not any(s in followed_sectors for s in ("macro", "global", "policy"))
        ):
            return "cross_market_insight"

        # Sector diversification — assets not in followed stocks
        if followed_stocks and signal.assets:
            if not any(asset in followed_stocks for asset in signal.assets):
                return "sector_diversification"

        # Signal type not followed — treat as emerging topic
        if followed_types and signal.signal_type.value not in followed_types:
            return "emerging_topic"

        return "emerging_topic"
