from pathlib import Path
from types import SimpleNamespace

from zcli.agent import Agent
from zcli.config import Settings
from zcli.hooks import (
    POST_TOOL_USE,
    PRE_TOOL_USE,
    STOP,
    USER_PROMPT_SUBMIT,
    HookContext,
    HookManager,
    HookResult,
)


class Block:
    def __init__(self, **values):
        self.values = values

    def model_dump(self, exclude_none=True):
        return self.values


class LifecycleMessages:
    def __init__(self):
        self.main_calls = 0
        self.first_messages = None

    def create(self, **kwargs):
        if "tools" not in kwargs:
            return SimpleNamespace(content=[Block(type="text", text="[]")], stop_reason="end_turn")
        self.main_calls += 1
        if self.main_calls == 1:
            self.first_messages = kwargs["messages"]
            return SimpleNamespace(
                content=[Block(type="tool_use", id="tool-1", name="glob", input={"pattern": "*.txt"})],
                stop_reason="tool_use",
            )
        return SimpleNamespace(content=[Block(type="text", text="done")], stop_reason="end_turn")


def make_agent(tmp_path: Path, messages, hooks: HookManager | None = None) -> Agent:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return Agent(
        Settings(workspace, tmp_path / "data", "fake-model", None),
        client=SimpleNamespace(messages=messages),
        interactive=False,
        hooks=hooks,
    )


def test_hook_manager_preserves_order_and_merges_context():
    hooks = HookManager()
    calls = []
    hooks.register(USER_PROMPT_SUBMIT, lambda _: calls.append("a") or HookResult(additional_context="A"))
    hooks.register(USER_PROMPT_SUBMIT, lambda _: calls.append("b") or "B")

    result = hooks.trigger(USER_PROMPT_SUBMIT, HookContext(event=USER_PROMPT_SUBMIT, emit=lambda _: None))

    assert calls == ["a", "b"]
    assert result.additional_context == "A\n\nB"


def test_pre_tool_hook_exception_fails_closed():
    hooks = HookManager()

    def broken(_):
        raise RuntimeError("hook failed")

    hooks.register(PRE_TOOL_USE, broken)
    result = hooks.trigger(PRE_TOOL_USE, HookContext(event=PRE_TOOL_USE, emit=lambda _: None))

    assert result.blocked
    assert "hook failed" in result.reason


def test_all_four_hook_events_integrate_with_agent_loop(tmp_path: Path):
    hooks = HookManager()
    events = []
    hooks.register(USER_PROMPT_SUBMIT, lambda _: events.append(USER_PROMPT_SUBMIT) or "injected-by-hook")
    hooks.register(PRE_TOOL_USE, lambda _: events.append(PRE_TOOL_USE))
    hooks.register(
        POST_TOOL_USE,
        lambda _: events.append(POST_TOOL_USE) or HookResult(updated_output="post-hook-output"),
    )
    hooks.register(STOP, lambda _: events.append(STOP))
    messages = LifecycleMessages()
    agent = make_agent(tmp_path, messages, hooks)
    session = agent.sessions.create("hooks")

    assert agent.run_turn(session, "run", emit=lambda _: None) == "done"

    assert events == [USER_PROMPT_SUBMIT, PRE_TOOL_USE, POST_TOOL_USE, STOP]
    assert "injected-by-hook" in messages.first_messages[0]["content"]
    assert "post-hook-output" in str(session.messages)


def test_pre_tool_hook_blocks_execution_but_returns_tool_result(tmp_path: Path):
    hooks = HookManager()
    hooks.register(PRE_TOOL_USE, lambda _: HookResult(blocked=True, reason="blocked by test hook"))

    class WriteMessages(LifecycleMessages):
        def create(self, **kwargs):
            if "tools" not in kwargs:
                return SimpleNamespace(content=[Block(type="text", text="[]")], stop_reason="end_turn")
            self.main_calls += 1
            if self.main_calls == 1:
                return SimpleNamespace(
                    content=[Block(type="tool_use", id="write-1", name="write_file", input={"path": "blocked.txt", "content": "no"})],
                    stop_reason="tool_use",
                )
            return SimpleNamespace(content=[Block(type="text", text="blocked")], stop_reason="end_turn")

    agent = make_agent(tmp_path, WriteMessages(), hooks)
    session = agent.sessions.create("blocked")
    agent.run_turn(session, "write", emit=lambda _: None)

    assert not (agent.settings.workspace / "blocked.txt").exists()
    assert "blocked by test hook" in str(session.messages)


def test_stop_hook_continues_only_once(tmp_path: Path):
    hooks = HookManager()
    stop_calls = 0

    def continue_once(_):
        nonlocal stop_calls
        stop_calls += 1
        return "Review the answer once, then stop."

    hooks.register(STOP, continue_once)

    class StopMessages:
        def __init__(self):
            self.main_calls = 0

        def create(self, **kwargs):
            if "tools" not in kwargs:
                return SimpleNamespace(content=[Block(type="text", text="[]")], stop_reason="end_turn")
            self.main_calls += 1
            text = "first" if self.main_calls == 1 else "second"
            return SimpleNamespace(content=[Block(type="text", text=text)], stop_reason="end_turn")

    messages = StopMessages()
    agent = make_agent(tmp_path, messages, hooks)
    output = agent.run_turn(agent.sessions.create("stop"), "answer", emit=lambda _: None)

    assert output == "first\nsecond"
    assert messages.main_calls == 2
    assert stop_calls == 1
