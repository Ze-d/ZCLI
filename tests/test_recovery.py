import pytest

from zcli.recovery import RecoveryState, is_prompt_too_long_error, with_retry


def test_429_retries_then_succeeds_without_sleeping():
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("429 rate limit")
        return "ok"

    assert with_retry(operation, RecoveryState("primary"), sleep=lambda _: None, emit=lambda _: None) == "ok"
    assert calls == 3


def test_repeated_529_switches_to_fallback_model():
    calls = 0
    state = RecoveryState("primary")

    def operation():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("529 overloaded")
        return state.current_model

    assert with_retry(operation, state, fallback_model="fallback", sleep=lambda _: None, emit=lambda _: None) == "fallback"


def test_non_transient_error_is_not_retried():
    with pytest.raises(ValueError):
        with_retry(lambda: (_ for _ in ()).throw(ValueError("bad request")), RecoveryState("primary"))


def test_prompt_too_long_variants_are_detected():
    assert is_prompt_too_long_error(RuntimeError("prompt_is_too_long"))
    assert is_prompt_too_long_error(RuntimeError("context_length_exceeded"))
