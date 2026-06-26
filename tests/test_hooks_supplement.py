"""Supplemental tests for zcli.hooks — invalid event, unregister, _normalize for all events."""

from __future__ import annotations

import pytest

from zcli.hooks import (
    POST_TOOL_USE,
    PRE_TOOL_USE,
    STOP,
    USER_PROMPT_SUBMIT,
    HookContext,
    HookManager,
    HookResult,
    large_output_hook,
    permission_hook,
)


# ── register / unregister / callbacks with invalid events ─────────────────

def test_register_invalid_event():
    hooks = HookManager()

    with pytest.raises(ValueError, match="unknown hook event"):
        hooks.register("InvalidEvent", lambda _: None)


def test_unregister_invalid_event():
    hooks = HookManager()

    with pytest.raises(ValueError, match="unknown hook event"):
        hooks.unregister("InvalidEvent", lambda _: None)


def test_unregister_nonexistent_callback():
    hooks = HookManager()

    result = hooks.unregister(PRE_TOOL_USE, lambda _: None)
    assert result is False


def test_unregister_existing_callback():
    hooks = HookManager()

    def cb(_):
        return None

    hooks.register(PRE_TOOL_USE, cb)
    result = hooks.unregister(PRE_TOOL_USE, cb)

    assert result is True
    assert cb not in hooks.callbacks(PRE_TOOL_USE)


def test_callbacks_invalid_event():
    hooks = HookManager()

    with pytest.raises(ValueError):
        hooks.callbacks("InvalidEvent")


def test_callbacks_returns_tuple():
    hooks = HookManager()

    result = hooks.callbacks(PRE_TOOL_USE)
    assert isinstance(result, tuple)


# ── trigger with invalid event ────────────────────────────────────────────

def test_trigger_invalid_event():
    hooks = HookManager()

    with pytest.raises(ValueError, match="unknown hook event"):
        hooks.trigger("InvalidEvent", HookContext(event="InvalidEvent"))


def test_trigger_event_mismatch():
    hooks = HookManager()

    with pytest.raises(ValueError, match="does not match"):
        hooks.trigger(PRE_TOOL_USE, HookContext(event=STOP))


# ── _normalize for POST_TOOL_USE ─────────────────────────────────────────

def test_normalize_post_tool_use_string():
    result = HookManager._normalize(POST_TOOL_USE, "modified output")

    assert result.updated_output == "modified output"
    assert not result.blocked


# ── _normalize for unknown event ─────────────────────────────────────────

def test_normalize_unknown_event():
    result = HookManager._normalize("UnknownEvent", "value")

    assert isinstance(result, HookResult)


# ── _normalize rejects non-str non-HookResult ────────────────────────────

def test_normalize_rejects_invalid_type():
    with pytest.raises(TypeError, match="must return HookResult, str, or None"):
        HookManager._normalize(PRE_TOOL_USE, 42)


# ── permission_hook ──────────────────────────────────────────────────────

def test_permission_hook_allows_safe_tool():
    from zcli.tools import ToolRegistry
    from zcli.memory import MemoryStore
    from pathlib import Path

    tools = ToolRegistry(Path("/tmp"), MemoryStore(Path("/tmp/data")), interactive=False)

    class FakeAgent:
        pass

    agent = FakeAgent()
    agent.tools = tools

    context = HookContext(event=PRE_TOOL_USE, agent=agent, tool_name="read_file", tool_input={"path": "test.txt"})
    result = permission_hook(context)

    # Safe tool within workspace should be allowed
    assert result is None


# ── large_output_hook ────────────────────────────────────────────────────

def test_large_output_hook_emits_for_large_output():
    emitted = []

    context = HookContext(
        event=POST_TOOL_USE,
        tool_name="read_file",
        output="x" * 100_001,
        emit=lambda msg: emitted.append(msg),
    )

    large_output_hook(context)

    assert len(emitted) == 1
    assert "large output" in emitted[0]


def test_large_output_hook_silent_for_small_output():
    emitted = []

    context = HookContext(
        event=POST_TOOL_USE,
        tool_name="read_file",
        output="small",
        emit=lambda msg: emitted.append(msg),
    )

    large_output_hook(context)

    assert len(emitted) == 0


def test_large_output_hook_silent_for_none_output():
    emitted = []

    context = HookContext(
        event=POST_TOOL_USE,
        tool_name="read_file",
        output=None,
        emit=lambda msg: emitted.append(msg),
    )

    large_output_hook(context)

    assert len(emitted) == 0


# ── HookResult defaults ──────────────────────────────────────────────────

def test_hook_result_defaults():
    result = HookResult()

    assert result.blocked is False
    assert result.reason == ""
    assert result.additional_context == ""
    assert result.updated_output is None
    assert result.continuation == ""
    assert result.errors == []


# ── HookContext defaults ─────────────────────────────────────────────────

def test_hook_context_defaults():
    context = HookContext(event=PRE_TOOL_USE)

    assert context.event == PRE_TOOL_USE
    assert context.agent is None
    assert context.session is None
    assert context.query == ""
    assert context.tool_name == ""
    assert context.tool_input == {}
    assert context.output is None
    assert context.response_text == ""


# ── register prepend ─────────────────────────────────────────────────────

def test_register_prepend_adds_first():
    hooks = HookManager()
    calls = []

    hooks.register(USER_PROMPT_SUBMIT, lambda _: calls.append("second"))
    hooks.register(USER_PROMPT_SUBMIT, lambda _: calls.append("first"), prepend=True)

    hooks.trigger(USER_PROMPT_SUBMIT, HookContext(event=USER_PROMPT_SUBMIT))

    assert calls == ["first", "second"]
