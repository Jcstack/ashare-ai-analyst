"""Tests for SealStateMachine -- limit-up board lifecycle tracking."""

from __future__ import annotations

import pytest


class TestSealState:
    def test_enum_values(self):
        from src.agent_loop.seal_state_machine import SealState

        assert SealState.NONE == "none"
        assert SealState.SEALED == "sealed"
        assert SealState.BROKEN == "broken"
        assert SealState.APPROACHING == "approaching"
        assert SealState.RESEALED == "resealed"
        assert SealState.FAILED == "failed"


class TestSealLifecycle:
    def test_quality_score_neutral(self):
        from src.agent_loop.seal_state_machine import SealLifecycle

        lc = SealLifecycle(
            symbol="test", board_type="main", limit_up_price=11.0, prev_close=10.0
        )
        assert 0.0 <= lc.seal_quality_score <= 1.0

    def test_next_day_prediction_failed(self):
        from src.agent_loop.seal_state_machine import SealLifecycle, SealState

        lc = SealLifecycle(
            symbol="test", board_type="main", limit_up_price=11.0, prev_close=10.0
        )
        lc.state = SealState.FAILED
        pred = lc.next_day_prediction
        assert pred["prediction"] == "弱势"

    def test_next_day_prediction_many_breaks(self):
        from src.agent_loop.seal_state_machine import SealLifecycle

        lc = SealLifecycle(
            symbol="test", board_type="main", limit_up_price=11.0, prev_close=10.0
        )
        lc.break_count = 5
        pred = lc.next_day_prediction
        assert pred["prediction"] == "偏弱"

    def test_quality_score_no_breaks_bonus(self):
        from src.agent_loop.seal_state_machine import SealLifecycle

        lc = SealLifecycle(
            symbol="test", board_type="main", limit_up_price=11.0, prev_close=10.0
        )
        lc.break_count = 0
        score_no_break = lc.seal_quality_score

        lc2 = SealLifecycle(
            symbol="test", board_type="main", limit_up_price=11.0, prev_close=10.0
        )
        lc2.break_count = 3
        score_breaks = lc2.seal_quality_score

        assert score_no_break > score_breaks


class TestSealStateMachine:
    @pytest.fixture()
    def machine(self):
        from src.agent_loop.seal_state_machine import SealStateMachine

        return SealStateMachine()

    def test_init(self, machine):
        assert machine.get_all_active() == {}

    def test_approaching(self, machine):
        from src.agent_loop.seal_state_machine import SealState

        lc = machine.update(
            "600519", price=10.85, volume=100000, prev_close=10.0, seal_volume=0
        )
        assert lc.state == SealState.APPROACHING

    def test_sealed(self, machine):
        from src.agent_loop.seal_state_machine import SealState

        lc = machine.update(
            "600519", price=11.0, volume=100000, prev_close=10.0, seal_volume=50000
        )
        assert lc.state == SealState.SEALED
        assert lc.first_seal_time is not None

    def test_seal_then_break(self, machine):
        from src.agent_loop.seal_state_machine import SealState

        machine.update(
            "600519",
            price=11.0,
            volume=100000,
            prev_close=10.0,
            seal_volume=50000,
            timestamp=1000.0,
        )
        lc = machine.update(
            "600519",
            price=10.5,
            volume=120000,
            prev_close=10.0,
            seal_volume=0,
            timestamp=1010.0,
        )
        assert lc.state == SealState.BROKEN
        assert lc.break_count == 1

    def test_break_then_reseal(self, machine):
        from src.agent_loop.seal_state_machine import SealState

        machine.update(
            "600519",
            price=11.0,
            volume=100000,
            prev_close=10.0,
            seal_volume=50000,
            timestamp=1000.0,
        )
        machine.update(
            "600519",
            price=10.5,
            volume=120000,
            prev_close=10.0,
            seal_volume=0,
            timestamp=1010.0,
        )
        lc = machine.update(
            "600519",
            price=11.0,
            volume=130000,
            prev_close=10.0,
            seal_volume=40000,
            timestamp=1020.0,
        )
        assert lc.state == SealState.RESEALED

    def test_failed_from_approaching(self, machine):
        from src.agent_loop.seal_state_machine import SealState

        machine.update(
            "600519", price=10.85, volume=50000, prev_close=10.0, timestamp=1000.0
        )
        lc = machine.update(
            "600519", price=10.5, volume=60000, prev_close=10.0, timestamp=1010.0
        )
        assert lc.state == SealState.FAILED

    def test_multiple_symbols(self, machine):
        machine.update(
            "600519", price=11.0, volume=100000, prev_close=10.0, seal_volume=50000
        )
        machine.update(
            "000001", price=5.5, volume=200000, prev_close=5.0, seal_volume=30000
        )
        active = machine.get_all_active()
        assert len(active) == 2

    def test_reset(self, machine):
        machine.update(
            "600519", price=11.0, volume=100000, prev_close=10.0, seal_volume=50000
        )
        machine.reset("600519")
        assert machine.get_lifecycle("600519") is None

    def test_reset_all(self, machine):
        machine.update(
            "600519", price=11.0, volume=100000, prev_close=10.0, seal_volume=50000
        )
        machine.update(
            "000001", price=5.5, volume=200000, prev_close=5.0, seal_volume=30000
        )
        machine.reset_all()
        assert machine.get_all_active() == {}

    def test_chinext_20pct_limit(self, machine):
        from src.agent_loop.seal_state_machine import SealState

        lc = machine.update(
            "300001",
            price=12.0,
            volume=100000,
            prev_close=10.0,
            seal_volume=50000,
            board_type="chinext",
        )
        assert lc.state == SealState.SEALED
        assert lc.limit_up_price == 12.0

    def test_transitions_recorded(self, machine):
        machine.update(
            "600519", price=10.9, volume=50000, prev_close=10.0, timestamp=1000.0
        )
        machine.update(
            "600519",
            price=11.0,
            volume=80000,
            prev_close=10.0,
            seal_volume=50000,
            timestamp=1010.0,
        )
        lc = machine.get_lifecycle("600519")
        assert len(lc.transitions) >= 1

    def test_get_lifecycle_nonexistent(self, machine):
        assert machine.get_lifecycle("NONEXIST") is None

    def test_failed_not_in_active(self, machine):
        """Failed lifecycles should not appear in get_all_active()."""
        from src.agent_loop.seal_state_machine import SealState

        machine.update(
            "600519", price=10.85, volume=50000, prev_close=10.0, timestamp=1000.0
        )
        machine.update(
            "600519", price=10.5, volume=60000, prev_close=10.0, timestamp=1010.0
        )
        lc = machine.get_lifecycle("600519")
        assert lc.state == SealState.FAILED
        assert "600519" not in machine.get_all_active()

    def test_resealed_then_break_again(self, machine):
        """Breaking from RESEALED state should increment break_count."""
        from src.agent_loop.seal_state_machine import SealState

        machine.update(
            "600519",
            price=11.0,
            volume=100000,
            prev_close=10.0,
            seal_volume=50000,
            timestamp=1000.0,
        )
        machine.update(
            "600519",
            price=10.5,
            volume=120000,
            prev_close=10.0,
            seal_volume=0,
            timestamp=1010.0,
        )
        machine.update(
            "600519",
            price=11.0,
            volume=130000,
            prev_close=10.0,
            seal_volume=40000,
            timestamp=1020.0,
        )
        lc = machine.update(
            "600519",
            price=10.5,
            volume=140000,
            prev_close=10.0,
            seal_volume=0,
            timestamp=1030.0,
        )
        assert lc.state == SealState.BROKEN
        assert lc.break_count == 2
