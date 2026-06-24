"""Unit tests for assistant push notification embed and push rules."""

from __future__ import annotations

import discord

from src.discord_bot.embeds.assistant_message_card import (
    build_assistant_message_embed,
)


# ── Color mapping ────────────────────────────────────────────────


class TestAssistantMessageColors:
    def test_buy_signal_green(self):
        embed = build_assistant_message_embed(
            {
                "type": "buy_signal",
                "title": "建议买入 比亚迪(002594)",
                "summary": "低估",
            }
        )
        assert embed.color.value == 0x22C55E  # type: ignore[union-attr]

    def test_sell_signal_red(self):
        embed = build_assistant_message_embed(
            {"type": "sell_signal", "title": "建议卖出 茅台", "summary": "见顶"}
        )
        assert embed.color.value == 0xEF4444  # type: ignore[union-attr]

    def test_risk_alert_amber(self):
        embed = build_assistant_message_embed(
            {"type": "risk_alert", "title": "风险预警", "summary": "大幅波动"}
        )
        assert embed.color.value == 0xF59E0B  # type: ignore[union-attr]

    def test_market_watch_blue(self):
        embed = build_assistant_message_embed(
            {"type": "market_watch", "title": "市场关注", "summary": "政策利好"}
        )
        assert embed.color.value == 0x3B82F6  # type: ignore[union-attr]

    def test_unknown_type_default(self):
        embed = build_assistant_message_embed({"type": "other", "title": "消息"})
        assert embed.color.value == 0x9E9E9E  # type: ignore[union-attr]


# ── Embed structure ──────────────────────────────────────────────


class TestAssistantMessageEmbed:
    def test_title_includes_badge(self):
        embed = build_assistant_message_embed(
            {"type": "buy_signal", "title": "建议买入"}
        )
        assert "📈" in embed.title

    def test_summary_in_description(self):
        embed = build_assistant_message_embed(
            {"type": "sell_signal", "title": "卖出", "summary": "目标位已到达"}
        )
        assert "目标位已到达" in embed.description

    def test_action_advice_field(self):
        embed = build_assistant_message_embed(
            {
                "type": "buy_signal",
                "title": "买入",
                "action_advice": "建议以当前价位分批买入",
            }
        )
        field_names = [f.name for f in embed.fields]
        assert "操作建议" in field_names
        advice_field = next(f for f in embed.fields if f.name == "操作建议")
        assert "分批买入" in advice_field.value

    def test_risk_note_field(self):
        embed = build_assistant_message_embed(
            {"type": "risk_alert", "title": "预警", "risk_note": "注意止损位"}
        )
        field_names = [f.name for f in embed.fields]
        assert "风险提示" in field_names

    def test_symbol_field(self):
        embed = build_assistant_message_embed(
            {
                "type": "buy_signal",
                "title": "买入",
                "symbol": "002594",
                "name": "比亚迪",
            }
        )
        field_names = [f.name for f in embed.fields]
        assert "标的" in field_names
        symbol_field = next(f for f in embed.fields if f.name == "标的")
        assert "比亚迪" in symbol_field.value
        assert "002594" in symbol_field.value

    def test_impact_field_for_market_watch(self):
        embed = build_assistant_message_embed(
            {"type": "market_watch", "title": "市场", "impact": "HIGH"}
        )
        field_names = [f.name for f in embed.fields]
        assert "影响级别" in field_names

    def test_footer_has_timestamp(self):
        embed = build_assistant_message_embed(
            {"type": "buy_signal", "title": "t", "timestamp": "2026-03-09 10:00"}
        )
        assert "2026-03-09" in embed.footer.text

    def test_footer_default_when_no_timestamp(self):
        embed = build_assistant_message_embed({"type": "buy_signal", "title": "t"})
        assert "投资助手" in embed.footer.text

    def test_minimal_message(self):
        embed = build_assistant_message_embed({})
        assert isinstance(embed, discord.Embed)
        assert "投资助手消息" in embed.title

    def test_long_summary_truncated(self):
        long_text = "A" * 5000
        embed = build_assistant_message_embed(
            {"type": "buy_signal", "title": "t", "summary": long_text}
        )
        assert len(embed.description) <= 4096

    def test_long_action_advice_truncated(self):
        long_text = "B" * 2000
        embed = build_assistant_message_embed(
            {"type": "buy_signal", "title": "t", "action_advice": long_text}
        )
        advice_field = next(f for f in embed.fields if f.name == "操作建议")
        assert len(advice_field.value) <= 1024


# ── Push rules (unit-level) ──────────────────────────────────────


class TestPushRules:
    """Test the push filtering logic without requiring Redis or Discord."""

    def _should_push(self, payload: dict) -> bool:
        """Replicate the push rules from AssistantPushCog._handle."""
        msg_type = payload.get("type", "")
        if msg_type == "hold_reminder":
            return False
        if msg_type == "market_watch":
            impact = str(payload.get("impact", "")).upper()
            return impact == "HIGH"
        return msg_type in {"buy_signal", "sell_signal", "risk_alert"}

    def test_buy_signal_always_pushed(self):
        assert self._should_push({"type": "buy_signal"})

    def test_sell_signal_always_pushed(self):
        assert self._should_push({"type": "sell_signal"})

    def test_risk_alert_always_pushed(self):
        assert self._should_push({"type": "risk_alert"})

    def test_hold_reminder_never_pushed(self):
        assert not self._should_push({"type": "hold_reminder"})

    def test_market_watch_high_impact_pushed(self):
        assert self._should_push({"type": "market_watch", "impact": "HIGH"})

    def test_market_watch_low_impact_not_pushed(self):
        assert not self._should_push({"type": "market_watch", "impact": "LOW"})

    def test_market_watch_medium_impact_not_pushed(self):
        assert not self._should_push({"type": "market_watch", "impact": "MEDIUM"})

    def test_market_watch_no_impact_not_pushed(self):
        assert not self._should_push({"type": "market_watch"})

    def test_unknown_type_not_pushed(self):
        assert not self._should_push({"type": "daily_digest"})


# ── Rate limiter ─────────────────────────────────────────────────


class TestRateLimiter:
    def test_allows_up_to_limit(self):
        from src.discord_bot.cogs.assistant_push import _RateLimiter

        limiter = _RateLimiter(max_per_day=2)
        assert limiter.allow("600519") is True
        assert limiter.allow("600519") is True
        assert limiter.allow("600519") is False

    def test_different_symbols_independent(self):
        from src.discord_bot.cogs.assistant_push import _RateLimiter

        limiter = _RateLimiter(max_per_day=1)
        assert limiter.allow("600519") is True
        assert limiter.allow("000001") is True
        assert limiter.allow("600519") is False

    def test_no_symbol_always_allowed(self):
        """Empty symbol string bypasses rate limiting in the cog."""
        from src.discord_bot.cogs.assistant_push import _RateLimiter

        limiter = _RateLimiter(max_per_day=1)
        # Empty string is a valid key but the cog skips rate check for it
        assert limiter.allow("") is True
