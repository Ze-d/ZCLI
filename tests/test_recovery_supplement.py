"""Supplemental tests for zcli.recovery — retry_delay, mixed retries, exhaustion."""

from __future__ import annotations

import pytest

from zcli.recovery import RecoveryState, is_prompt_too_long_error, retry_delay, with_retry


# ── retry_delay ───────────────────────────────────────────────────────────

def test_retry_delay_first_attempt():
    delay = retry_delay(0)
    # base=500*2^0=500ms -> 0.5s + 0-25% jitter
    assert 0.5 <= delay <= 0.625


def test_retry_delay_second_attempt():
    delay = retry_delay(1)
    # base=500*2^1=1000ms -> 1.0s + 0-25% jitter
    assert 1.0 <= delay <= 1.25


def test_retry_delay_caps_at_32_seconds():
    delay = retry_delay(10)  # 500*2^10=512000ms capped at 32000ms
    # base=32000ms -> 32.0s + 0-25% jitter
    assert 32.0 <= delay <= 40.0


def test_retry_delay_with_retry_after_header():
    delay = retry_delay(0, retry_after=10.0)
    assert delay == 10.0


def test_retry_delay_with_zero_retry_after():
    delay = retry_delay(0, retry_after=0.0)
    assert delay == 0.0


def test_retry_delay_with_negative_retry_after():
    delay = retry_delay(0, retry_after=-5.0)
    assert delay == 0.0


# ── with_retry exhaustion ─────────────────────────────────────────────────

def test_with_retry_exhausts_all_attempts():
    calls = []

    def always_fail():
        calls.append(1)
        raise RuntimeError("429 rate limit")

    with pytest.raises(RuntimeError, match="429 rate limit"):
        with_retry(always_fail, RecoveryState("primary"), max_retries=3, sleep=lambda _: None, emit=lambda _: None)

    assert len(calls) == 3


def test_with_retry_mixed_429_and_529():
    state = RecoveryState("primary")
    call_count = [0]

    def mixed():
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("429 rate limit")
        if call_count[0] == 2:
            raise RuntimeError("529 overloaded")
        return "ok"

    result = with_retry(mixed, state, max_retries=5, sleep=lambda _: None, emit=lambda _: None)

    assert result == "ok"
    assert call_count[0] == 3


def test_with_retry_two_consecutive_529_switches_model_and_resets_count():
    state = RecoveryState("primary")
    calls = []

    def overloaded():
        calls.append(1)
        raise RuntimeError("529 overloaded")

    with pytest.raises(RuntimeError):
        with_retry(overloaded, state, max_retries=3, fallback_model="fallback", sleep=lambda _: None, emit=lambda _: None)

    # Model switches to fallback after 2 consecutive 529s (at attempt 1).
    # After the third 529 (attempt 2), consecutive_529 becomes 1 before the raise.
    assert state.current_model == "fallback"


def test_with_retry_fallback_model_is_none_does_not_switch():
    state = RecoveryState("primary")
    calls = []

    def overloaded():
        calls.append(1)
        raise RuntimeError("529 overloaded")

    with pytest.raises(RuntimeError):
        with_retry(overloaded, state, max_retries=3, fallback_model=None, max_consecutive_529=2, sleep=lambda _: None, emit=lambda _: None)

    # Model stays as primary since no fallback
    assert state.current_model == "primary"


def test_with_retry_non_transient_no_retry():
    with pytest.raises(ValueError, match="bad request"):
        with_retry(lambda: (_ for _ in ()).throw(ValueError("bad request")), RecoveryState("primary"))


# ── is_prompt_too_long_error ──────────────────────────────────────────────

def test_is_prompt_too_long_detects_all_variants():
    assert is_prompt_too_long_error(RuntimeError("prompt is too long"))
    assert is_prompt_too_long_error(RuntimeError("prompt_is_too_long"))
    assert is_prompt_too_long_error(RuntimeError("context_length_exceeded"))
    assert is_prompt_too_long_error(RuntimeError("max_context_window exceeded"))


def test_is_prompt_too_long_negative():
    assert not is_prompt_too_long_error(RuntimeError("unknown error"))
    assert not is_prompt_too_long_error(ValueError("something else"))


# ── RecoveryState defaults ────────────────────────────────────────────────

def test_recovery_state_defaults():
    state = RecoveryState("claude-sonnet")

    assert state.current_model == "claude-sonnet"
    assert state.has_escalated is False
    assert state.recovery_count == 0
    assert state.consecutive_529 == 0
    assert state.has_attempted_reactive_compact is False
