from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


USER_PROMPT_SUBMIT = "UserPromptSubmit"
PRE_TOOL_USE = "PreToolUse"
POST_TOOL_USE = "PostToolUse"
STOP = "Stop"
HOOK_EVENTS = (USER_PROMPT_SUBMIT, PRE_TOOL_USE, POST_TOOL_USE, STOP)


@dataclass
class HookContext:
    event: str
    agent: Any = None
    session: Any = None
    query: str = ""
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    output: str | None = None
    response_text: str = ""
    emit: Callable[[str], None] = print


@dataclass
class HookResult:
    blocked: bool = False
    reason: str = ""
    additional_context: str = ""
    updated_output: str | None = None
    continuation: str = ""
    errors: list[str] = field(default_factory=list)


HookCallback = Callable[[HookContext], HookResult | str | None]


class HookManager:
    """Ordered lifecycle hooks inspired by learn-claude-code s04.

    String results keep the teaching-version convention: on PreToolUse they
    block the tool, on Stop they request one continuation, and on
    UserPromptSubmit they add context.
    """

    def __init__(self):
        self._hooks: dict[str, list[HookCallback]] = {event: [] for event in HOOK_EVENTS}

    def register(self, event: str, callback: HookCallback, *, prepend: bool = False) -> None:
        if event not in self._hooks:
            raise ValueError(f"unknown hook event: {event}")
        if prepend:
            self._hooks[event].insert(0, callback)
        else:
            self._hooks[event].append(callback)

    def unregister(self, event: str, callback: HookCallback) -> bool:
        if event not in self._hooks:
            raise ValueError(f"unknown hook event: {event}")
        try:
            self._hooks[event].remove(callback)
            return True
        except ValueError:
            return False

    def callbacks(self, event: str) -> tuple[HookCallback, ...]:
        if event not in self._hooks:
            raise ValueError(f"unknown hook event: {event}")
        return tuple(self._hooks[event])

    def trigger(self, event: str, context: HookContext) -> HookResult:
        if event not in self._hooks:
            raise ValueError(f"unknown hook event: {event}")
        if context.event != event:
            raise ValueError(f"hook context event {context.event!r} does not match {event!r}")

        merged = HookResult()
        for callback in tuple(self._hooks[event]):
            try:
                value = callback(context)
                if value is None:
                    continue
                result = self._normalize(event, value)
            except Exception as error:
                name = getattr(callback, "__name__", callback.__class__.__name__)
                message = f"{name}: {type(error).__name__}: {error}"
                merged.errors.append(message)
                context.emit(f"[HOOK] {event} error: {message}")
                # A failing pre-tool hook must not accidentally bypass safety.
                if event == PRE_TOOL_USE:
                    merged.blocked = True
                    merged.reason = f"PreToolUse hook failed: {message}"
                    break
                continue
            if result.additional_context:
                merged.additional_context = "\n\n".join(
                    part for part in (merged.additional_context, result.additional_context) if part
                )
            if result.updated_output is not None:
                merged.updated_output = result.updated_output
                context.output = result.updated_output
            if result.continuation:
                merged.continuation = result.continuation
            merged.errors.extend(result.errors)
            if result.blocked:
                merged.blocked = True
                merged.reason = result.reason or "blocked by hook"
                break
        return merged

    @staticmethod
    def _normalize(event: str, value: HookResult | str) -> HookResult:
        if isinstance(value, HookResult):
            return value
        if not isinstance(value, str):
            raise TypeError("hook callbacks must return HookResult, str, or None")
        if event == PRE_TOOL_USE:
            return HookResult(blocked=True, reason=value)
        if event == STOP:
            return HookResult(continuation=value)
        if event == USER_PROMPT_SUBMIT:
            return HookResult(additional_context=value)
        return HookResult(updated_output=value)


def permission_hook(context: HookContext) -> HookResult | None:
    """Default PreToolUse hook; permission remains authoritative over hooks."""
    error = context.agent.tools.permission_error(context.tool_name, context.tool_input)
    if error:
        return HookResult(blocked=True, reason=f"Permission denied: {error}")
    return None


def large_output_hook(context: HookContext) -> None:
    if context.output is not None and len(context.output) > 100_000:
        context.emit(f"[HOOK] large output from {context.tool_name}: {len(context.output)} characters")
