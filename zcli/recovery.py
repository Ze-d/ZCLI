from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable, TypeVar


T = TypeVar("T")


@dataclass
class RecoveryState:
    current_model: str
    has_escalated: bool = False
    recovery_count: int = 0
    consecutive_529: int = 0
    has_attempted_reactive_compact: bool = False


def retry_delay(attempt: int, base_delay_ms: int = 500, retry_after: float | None = None) -> float:
    if retry_after is not None:
        return max(0.0, retry_after)
    base = min(base_delay_ms * (2**attempt), 32_000) / 1000
    return base + random.uniform(0, base * 0.25)


def _retry_after(error: Exception) -> float | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    value = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def with_retry(
    operation: Callable[[], T],
    state: RecoveryState,
    *,
    max_retries: int = 3,
    max_consecutive_529: int = 2,
    fallback_model: str | None = None,
    base_delay_ms: int = 500,
    sleep: Callable[[float], None] = time.sleep,
    emit: Callable[[str], None] = print,
) -> T:
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            result = operation()
            state.consecutive_529 = 0
            return result
        except Exception as error:
            last_error = error
            name = type(error).__name__.lower()
            message = str(error).lower()
            rate_limited = "ratelimit" in name or "429" in message
            overloaded = "overloaded" in name or "529" in message or "overloaded" in message
            if not rate_limited and not overloaded:
                raise
            if overloaded:
                state.consecutive_529 += 1
                if state.consecutive_529 >= max_consecutive_529:
                    if fallback_model:
                        state.current_model = fallback_model
                        emit(f"[529] switching to fallback model: {fallback_model}")
                    state.consecutive_529 = 0
            delay = retry_delay(attempt, base_delay_ms, _retry_after(error))
            emit(f"[{'529' if overloaded else '429'}] retry {attempt + 1}/{max_retries} after {delay:.1f}s")
            sleep(delay)
    raise last_error or RuntimeError(f"max retries ({max_retries}) exceeded")


def is_prompt_too_long_error(error: Exception) -> bool:
    message = str(error).lower()
    return (
        ("prompt" in message and "long" in message)
        or "prompt_is_too_long" in message
        or "context_length_exceeded" in message
        or "max_context_window" in message
    )

