"""Tests for the trade service."""

import tempfile
import time
from pathlib import Path

from src.web.services.capital_service import CapitalService
from src.web.services.trade_service import TradeService


def _make_service() -> TradeService:
    """Create a TradeService with a temporary database."""
    tmp = tempfile.mkdtemp()
    return TradeService(db_path=Path(tmp) / "test_agent.db")


def _make_service_with_capital() -> tuple[TradeService, CapitalService]:
    """Create a TradeService wired to a CapitalService (shared DB)."""
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_agent.db"
    capital_svc = CapitalService(db_path=db_path)
    trade_svc = TradeService(db_path=db_path, capital_service=capital_svc)
    return trade_svc, capital_svc


class TestExecuteTrade:
    """Test trade execution."""

    def test_execute_trade_basic(self):
        """Execute a basic buy trade."""
        svc = _make_service()
        trade = svc.execute_trade(
            symbol="600519",
            stock_name="贵州茅台",
            action="buy",
            shares=100,
            price=1920.0,
            reasoning="技术面转强",
        )

        assert trade.id
        assert trade.symbol == "600519"
        assert trade.stock_name == "贵州茅台"
        assert trade.action == "buy"
        assert trade.shares == 100
        assert trade.price == 1920.0
        assert trade.amount == 192000.0
        assert trade.source == "manual"  # no recommendation_id
        assert trade.status == "executed"
        assert trade.executed_at is not None

    def test_execute_trade_with_recommendation(self):
        """Trade with recommendation_id is marked as agent source."""
        svc = _make_service()
        trade = svc.execute_trade(
            symbol="600519",
            stock_name="贵州茅台",
            action="buy",
            shares=100,
            price=1920.0,
            recommendation_id="rec-123",
        )
        assert trade.source == "agent"
        assert trade.agent_recommendation_id == "rec-123"

    def test_execute_trade_sell(self):
        """Execute a sell trade."""
        svc = _make_service()
        trade = svc.execute_trade(
            symbol="300750",
            stock_name="宁德时代",
            action="sell",
            shares=200,
            price=250.0,
        )
        assert trade.action == "sell"
        assert trade.amount == 50000.0

    def test_execute_trade_with_thread(self):
        """Trade linked to a chat thread."""
        svc = _make_service()
        trade = svc.execute_trade(
            symbol="600519",
            stock_name="贵州茅台",
            action="add",
            shares=100,
            price=1900.0,
            thread_id="thread-abc",
        )
        assert trade.thread_id == "thread-abc"


class TestRecordManualTrade:
    """Test manual trade recording."""

    def test_record_manual_trade(self):
        """Record a manual trade."""
        svc = _make_service()
        trade = svc.record_manual_trade(
            symbol="601318",
            stock_name="中国平安",
            action="buy",
            shares=500,
            price=45.0,
            reasoning="手动买入",
        )
        assert trade.source == "manual"
        assert trade.reasoning == "手动买入"
        assert trade.thread_id is None


class TestTradeHistory:
    """Test trade history queries."""

    def test_empty_history(self):
        """Empty database returns empty list."""
        svc = _make_service()
        trades = svc.get_trade_history()
        assert trades == []

    def test_get_all_trades(self):
        """Get all trades in desc order."""
        svc = _make_service()
        svc.execute_trade("600519", "贵州茅台", "buy", 100, 1920.0)
        svc.execute_trade("300750", "宁德时代", "buy", 200, 250.0)
        svc.execute_trade("600519", "贵州茅台", "sell", 100, 1950.0)

        trades = svc.get_trade_history()
        assert len(trades) == 3
        # Most recent first
        assert trades[0].action == "sell"
        assert trades[1].symbol == "300750"
        assert trades[2].action == "buy"

    def test_filter_by_symbol(self):
        """Filter trades by symbol."""
        svc = _make_service()
        svc.execute_trade("600519", "贵州茅台", "buy", 100, 1920.0)
        svc.execute_trade("300750", "宁德时代", "buy", 200, 250.0)
        svc.execute_trade("600519", "贵州茅台", "sell", 100, 1950.0)

        trades = svc.get_trade_history(symbol="600519")
        assert len(trades) == 2
        assert all(t.symbol == "600519" for t in trades)

    def test_trade_count(self):
        """Count trades."""
        svc = _make_service()
        assert svc.get_trade_count() == 0

        svc.execute_trade("600519", "贵州茅台", "buy", 100, 1920.0)
        svc.execute_trade("300750", "宁德时代", "buy", 200, 250.0)

        assert svc.get_trade_count() == 2
        assert svc.get_trade_count(symbol="600519") == 1

    def test_limit_and_offset(self):
        """Pagination with limit and offset."""
        svc = _make_service()
        for i in range(5):
            svc.execute_trade("600519", "贵州茅台", "buy", 100, 1920.0 + i)

        page1 = svc.get_trade_history(limit=2, offset=0)
        page2 = svc.get_trade_history(limit=2, offset=2)

        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0].id != page2[0].id


class TestRecommendations:
    """Test recommendation CRUD."""

    def test_save_and_get_recommendation(self):
        """Save and retrieve a recommendation."""
        svc = _make_service()
        rec = svc.save_recommendation(
            thread_id="thread-1",
            symbol="600519",
            action="buy",
            confidence=0.75,
            reasoning="技术面转强，资金净流入",
            risk_warnings=["估值偏高", "大盘不确定"],
            stop_loss=1850.0,
        )

        assert rec.id
        assert rec.user_decision == "pending"
        assert rec.risk_warnings == ["估值偏高", "大盘不确定"]
        assert rec.stop_loss == 1850.0

        loaded = svc.get_recommendation(rec.id)
        assert loaded is not None
        assert loaded.symbol == "600519"
        assert loaded.risk_warnings == ["估值偏高", "大盘不确定"]

    def test_update_recommendation_decision(self):
        """Accept a recommendation."""
        svc = _make_service()
        rec = svc.save_recommendation(
            thread_id="thread-1",
            symbol="600519",
            action="buy",
            confidence=0.75,
            reasoning="测试",
        )

        updated = svc.update_recommendation_decision(rec.id, "accepted", "价格合理")
        assert updated is True

        loaded = svc.get_recommendation(rec.id)
        assert loaded is not None
        assert loaded.user_decision == "accepted"
        assert loaded.user_feedback == "价格合理"

    def test_reject_recommendation(self):
        """Reject a recommendation with feedback."""
        svc = _make_service()
        rec = svc.save_recommendation(
            thread_id="thread-1",
            symbol="600519",
            action="buy",
            confidence=0.5,
            reasoning="测试",
        )

        svc.update_recommendation_decision(rec.id, "rejected", "价格太高了")

        loaded = svc.get_recommendation(rec.id)
        assert loaded is not None
        assert loaded.user_decision == "rejected"
        assert loaded.user_feedback == "价格太高了"

    def test_update_nonexistent_recommendation(self):
        """Updating a nonexistent recommendation returns False."""
        svc = _make_service()
        result = svc.update_recommendation_decision("nonexistent", "accepted")
        assert result is False

    def test_list_recommendations_by_thread(self):
        """List recommendations filtered by thread."""
        svc = _make_service()
        svc.save_recommendation("t1", "600519", "buy", 0.7, "r1")
        svc.save_recommendation("t1", "300750", "sell", 0.6, "r2")
        svc.save_recommendation("t2", "600519", "buy", 0.8, "r3")

        recs = svc.get_recommendations(thread_id="t1")
        assert len(recs) == 2

    def test_list_recommendations_by_symbol(self):
        """List recommendations filtered by symbol."""
        svc = _make_service()
        svc.save_recommendation("t1", "600519", "buy", 0.7, "r1")
        svc.save_recommendation("t1", "300750", "sell", 0.6, "r2")

        recs = svc.get_recommendations(symbol="600519")
        assert len(recs) == 1
        assert recs[0].symbol == "600519"


class TestTradingProfile:
    """Test trading profile computation."""

    def test_empty_profile(self):
        """Empty trade history produces default profile."""
        svc = _make_service()
        profile = svc.compute_trading_profile()

        assert profile.total_trades == 0
        assert profile.risk_tolerance == "moderate"
        assert profile.agent_adoption_rate == 0.0

    def test_profile_with_trades(self):
        """Profile computed from trades."""
        svc = _make_service()
        for _ in range(6):
            svc.execute_trade("600519", "贵州茅台", "buy", 100, 1920.0)
        svc.execute_trade("600519", "贵州茅台", "sell", 100, 1950.0)

        profile = svc.compute_trading_profile()
        assert profile.total_trades == 7
        # 6 buys vs 1 sell → aggressive
        assert profile.risk_tolerance == "aggressive"

    def test_profile_adoption_rate(self):
        """Adoption rate calculated from recommendations."""
        svc = _make_service()
        svc.execute_trade("600519", "贵州茅台", "buy", 100, 1920.0)

        r1 = svc.save_recommendation("t1", "600519", "buy", 0.7, "r1")
        r2 = svc.save_recommendation("t1", "300750", "sell", 0.6, "r2")
        r3 = svc.save_recommendation("t1", "601318", "buy", 0.8, "r3")

        svc.update_recommendation_decision(r1.id, "accepted")
        svc.update_recommendation_decision(r2.id, "rejected")
        svc.update_recommendation_decision(r3.id, "accepted")

        profile = svc.compute_trading_profile()
        # 2 accepted / 3 decided = 0.67
        assert abs(profile.agent_adoption_rate - 0.67) < 0.01


class TestProfileWinRate:
    """Test win rate and holding days computation."""

    def test_win_rate_profitable_pair(self):
        """Buy low, sell high → 100% win rate."""
        svc = _make_service()
        svc.execute_trade("600519", "贵州茅台", "buy", 100, 1900.0)
        # Small sleep to ensure different timestamps
        time.sleep(0.01)
        svc.execute_trade("600519", "贵州茅台", "sell", 100, 2000.0)

        profile = svc.compute_trading_profile()
        assert profile.win_rate == 1.0

    def test_win_rate_losing_pair(self):
        """Buy high, sell low → 0% win rate."""
        svc = _make_service()
        svc.execute_trade("600519", "贵州茅台", "buy", 100, 2000.0)
        time.sleep(0.01)
        svc.execute_trade("600519", "贵州茅台", "sell", 100, 1900.0)

        profile = svc.compute_trading_profile()
        assert profile.win_rate == 0.0

    def test_win_rate_mixed_pairs(self):
        """One profitable, one losing → 50% win rate."""
        svc = _make_service()
        # Pair 1: profitable
        svc.execute_trade("600519", "贵州茅台", "buy", 100, 1900.0)
        time.sleep(0.01)
        svc.execute_trade("600519", "贵州茅台", "sell", 100, 2000.0)
        time.sleep(0.01)
        # Pair 2: losing
        svc.execute_trade("600519", "贵州茅台", "buy", 100, 2100.0)
        time.sleep(0.01)
        svc.execute_trade("600519", "贵州茅台", "sell", 100, 2000.0)

        profile = svc.compute_trading_profile()
        assert profile.win_rate == 0.5

    def test_win_rate_only_buys_no_sells(self):
        """Buys without sells → no pairs → win_rate 0."""
        svc = _make_service()
        svc.execute_trade("600519", "贵州茅台", "buy", 100, 1900.0)
        svc.execute_trade("300750", "宁德时代", "buy", 200, 250.0)

        profile = svc.compute_trading_profile()
        assert profile.win_rate == 0.0
        assert profile.avg_holding_days == 0.0

    def test_avg_holding_days(self):
        """Holding days computed from buy→sell time difference."""
        svc = _make_service()
        svc.execute_trade("600519", "贵州茅台", "buy", 100, 1900.0)
        time.sleep(0.01)
        svc.execute_trade("600519", "贵州茅台", "sell", 100, 2000.0)

        profile = svc.compute_trading_profile()
        # Within same second, so holding days ≈ 0
        assert profile.avg_holding_days >= 0.0

    def test_fifo_pairing_across_symbols(self):
        """FIFO pairing works per-symbol independently."""
        svc = _make_service()
        svc.execute_trade("600519", "贵州茅台", "buy", 100, 1900.0)
        time.sleep(0.01)
        svc.execute_trade("300750", "宁德时代", "buy", 100, 200.0)
        time.sleep(0.01)
        # Sell 300750 at profit
        svc.execute_trade("300750", "宁德时代", "sell", 100, 250.0)
        time.sleep(0.01)
        # Sell 600519 at loss
        svc.execute_trade("600519", "贵州茅台", "sell", 100, 1800.0)

        profile = svc.compute_trading_profile()
        # 1 profitable (300750) + 1 loss (600519) = 50%
        assert profile.win_rate == 0.5


class TestProfileBiases:
    """Test common bias detection."""

    def test_no_biases_few_trades(self):
        """Less than 5 trades → no biases detected."""
        svc = _make_service()
        svc.execute_trade("600519", "贵州茅台", "buy", 100, 1920.0)
        svc.execute_trade("600519", "贵州茅台", "buy", 100, 1920.0)

        profile = svc.compute_trading_profile()
        assert profile.common_biases == []

    def test_concentration_bias(self):
        """More than 50% trades in one symbol → 过度集中."""
        svc = _make_service()
        for _ in range(8):
            svc.execute_trade("600519", "贵州茅台", "buy", 100, 1920.0)
        for _ in range(2):
            svc.execute_trade("300750", "宁德时代", "buy", 100, 250.0)

        profile = svc.compute_trading_profile()
        assert "过度集中" in profile.common_biases

    def test_chasing_tendency_bias(self):
        """More than 70% buys → 追涨倾向."""
        svc = _make_service()
        for _ in range(8):
            svc.execute_trade("600519", "贵州茅台", "buy", 100, 1920.0)
        svc.execute_trade("600519", "贵州茅台", "sell", 100, 1920.0)

        profile = svc.compute_trading_profile()
        assert "追涨倾向" in profile.common_biases

    def test_low_adoption_bias(self):
        """Agent adoption rate < 30% with sufficient trades → 偏好观望."""
        svc = _make_service()
        for i in range(6):
            svc.execute_trade("600519", "贵州茅台", "buy", 100, 1920.0 + i)
        svc.execute_trade("600519", "贵州茅台", "sell", 100, 1950.0)

        # Create recommendations all rejected
        for _ in range(5):
            r = svc.save_recommendation("t1", "600519", "buy", 0.7, "test")
            svc.update_recommendation_decision(r.id, "rejected")

        profile = svc.compute_trading_profile()
        assert "偏好观望" in profile.common_biases


class TestProfileSectors:
    """Test preferred sectors extraction."""

    def test_preferred_sectors_fallback_to_board(self):
        """When registry unavailable, falls back to board name."""
        svc = _make_service()
        for _ in range(3):
            svc.execute_trade("600519", "贵州茅台", "buy", 100, 1920.0)
        svc.execute_trade("300750", "宁德时代", "buy", 100, 250.0)

        profile = svc.compute_trading_profile()
        # Should have at least 1 sector (board fallback)
        assert len(profile.preferred_sectors) >= 1


class TestCapitalIntegration:
    """Test trade → capital settlement integration."""

    def test_buy_deducts_capital(self):
        """Executing a buy trade deducts capital."""
        trade_svc, capital_svc = _make_service_with_capital()
        capital_svc.deposit(500000)

        trade_svc.execute_trade("600519", "贵州茅台", "buy", 100, 1920.0)

        balance = capital_svc.get_balance()
        # Balance should be less than 500000 - 192000 (commission subtracted too)
        assert balance < 500000 - 192000
        assert balance > 0

    def test_sell_credits_capital(self):
        """Executing a sell trade credits capital."""
        trade_svc, capital_svc = _make_service_with_capital()
        capital_svc.deposit(500000)

        trade_svc.execute_trade("600519", "贵州茅台", "sell", 100, 2000.0)

        balance = capital_svc.get_balance()
        # Balance should be more than 500000 (proceeds minus fees)
        assert balance > 500000

    def test_manual_trade_settles_capital(self):
        """Manual trades also settle capital."""
        trade_svc, capital_svc = _make_service_with_capital()
        capital_svc.deposit(500000)

        trade_svc.record_manual_trade("600519", "贵州茅台", "buy", 100, 100.0)

        balance = capital_svc.get_balance()
        assert balance < 500000

    def test_trade_without_capital_service(self):
        """Trades work fine without capital_service (no crash)."""
        svc = _make_service()  # no capital_service wired
        trade = svc.execute_trade("600519", "贵州茅台", "buy", 100, 1920.0)
        assert trade.status == "executed"

    def test_capital_transaction_linked_to_trade(self):
        """Capital transaction references the trade_id."""
        trade_svc, capital_svc = _make_service_with_capital()
        capital_svc.deposit(500000)

        trade = trade_svc.execute_trade("600519", "贵州茅台", "buy", 100, 100.0)

        history = capital_svc.get_history(tx_type="trade_buy")
        assert len(history) == 1
        assert history[0].trade_id == trade.id
        assert history[0].symbol == "600519"
