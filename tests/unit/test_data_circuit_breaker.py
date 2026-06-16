"""Tests for data.circuit_breaker module (API call circuit breaker)."""

import pytest

from src.data.circuit_breaker import CircuitBreaker, CircuitBreakerOpen


class TestCircuitBreakerClosed:
    def test_passes_through_on_success(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        result = cb.call(lambda: 42)
        assert result == 42
        assert cb.state == "closed"

    def test_stays_closed_under_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=3)

        def failing():
            raise ValueError("boom")

        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(failing)

        assert cb.state == "closed"
        assert cb._failure_count == 2


class TestCircuitBreakerOpen:
    def test_opens_after_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=60)

        def failing():
            raise ValueError("boom")

        for _ in range(3):
            with pytest.raises(ValueError):
                cb.call(failing)

        assert cb.state == "open"

    def test_rejects_calls_when_open(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=9999)

        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("boom")))

        with pytest.raises(CircuitBreakerOpen) as exc_info:
            cb.call(lambda: 42)

        assert "OPEN" in str(exc_info.value)
        assert exc_info.value.name == "test"


class TestCircuitBreakerHalfOpen:
    def test_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.0)

        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("boom")))

        assert cb.state == "half_open"

    def test_recovers_on_successful_probe(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.0)

        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("boom")))

        result = cb.call(lambda: 99)
        assert result == 99
        assert cb.state == "closed"


class TestCircuitBreakerReset:
    def test_manual_reset(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=9999)

        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("boom")))

        assert cb.state == "open"
        cb.reset()
        assert cb.state == "closed"
        assert cb._failure_count == 0


class TestSuccessResetsCount:
    def test_success_resets_failure_count(self):
        cb = CircuitBreaker("test", failure_threshold=3)

        def failing():
            raise ValueError("boom")

        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(failing)

        cb.call(lambda: "ok")
        assert cb._failure_count == 0

        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(failing)
        assert cb.state == "closed"
