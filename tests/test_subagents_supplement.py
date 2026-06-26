"""Supplemental tests for zcli.subagents — validate_agent_name, worktree/task resolution, stop/limit."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from zcli.config import Settings
from zcli.memory import MemoryStore
from zcli.subagents import SUBAGENT_TOOLS, SubagentRunner, validate_agent_name
from zcli.tasks import TaskStore
from zcli.worktrees import WorktreeManager


# ── validate_agent_name ──────────────────────────────────────────────────

def test_validate_agent_name_valid_cases():
    assert validate_agent_name("agent") == "agent"
    assert validate_agent_name("agent-1") == "agent-1"
    assert validate_agent_name("AGENT_2") == "AGENT_2"
    assert validate_agent_name("a") == "a"
    assert validate_agent_name("A" + "b" * 30) == "A" + "b" * 30


def test_validate_agent_name_invalid():
    for name in ["", " ", "-bad", "_bad", "bad name", "a" * 33]:
        try:
            validate_agent_name(name)
            assert False, f"Should have raised for {name!r}"
        except ValueError:
            pass


# ── SUBAGENT_TOOLS ───────────────────────────────────────────────────────

def test_subagent_tools_does_not_include_team_or_mcp():
    assert "spawn_teammate" not in SUBAGENT_TOOLS
    assert "send_message" not in SUBAGENT_TOOLS
    assert "remember" not in SUBAGENT_TOOLS
    assert "run_subagent" not in SUBAGENT_TOOLS
    assert "connect_mcp" not in SUBAGENT_TOOLS
    assert "todo_write" not in SUBAGENT_TOOLS


def test_subagent_tools_includes_basic_tools():
    assert "bash" in SUBAGENT_TOOLS
    assert "read_file" in SUBAGENT_TOOLS
    assert "write_file" in SUBAGENT_TOOLS
    assert "edit_file" in SUBAGENT_TOOLS
    assert "glob" in SUBAGENT_TOOLS


# ── SubagentRunner edge cases ────────────────────────────────────────────

class Block:
    def __init__(self, **values):
        self.values = values

    def model_dump(self, exclude_none=True):
        return self.values


def make_runner(tmp_path: Path, messages=None):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    settings = Settings(workspace, data, "fake", None)
    tasks = TaskStore(data)
    return SubagentRunner(
        settings,
        SimpleNamespace(messages=messages),
        MemoryStore(data),
        tasks,
        WorktreeManager(workspace, data, tasks),
    )


def test_run_empty_prompt(tmp_path: Path):
    runner = make_runner(tmp_path)
    result = runner.run("agent", "dev", "  ")
    assert "cannot be empty" in result


def test_run_stop_event_set_at_start(tmp_path: Path):
    import threading
    runner = make_runner(tmp_path)
    stop = threading.Event()
    stop.set()

    result = runner.run("agent", "dev", "do work", stop_event=stop)

    assert "stopped" in result.lower()


def test_run_exception_during_execution(tmp_path: Path):
    class ErrorMessages:
        def create(self, **kwargs):
            raise RuntimeError("connection failed")

    runner = make_runner(tmp_path, ErrorMessages())
    result = runner.run("agent", "dev", "work")

    assert "Error:" in result


def test_run_text_only_response(tmp_path: Path):
    class TextOnlyMessages:
        def create(self, **kwargs):
            return SimpleNamespace(
                content=[Block(type="text", text="just text, no tool calls")],
            )

    runner = make_runner(tmp_path, TextOnlyMessages())
    result = runner.run("agent", "dev", "work")

    assert result == "just text, no tool calls"


def test_run_no_text_no_tool_calls(tmp_path: Path):
    class EmptyMessages:
        def create(self, **kwargs):
            return SimpleNamespace(content=[])

    runner = make_runner(tmp_path, EmptyMessages())
    result = runner.run("agent", "dev", "work")

    assert "without a text response" in result


def test_run_disallowed_tool(tmp_path: Path):
    class BadToolMessages:
        def __init__(self):
            self.calls = 0
            self.messages_log = []

        def create(self, **kwargs):
            self.calls += 1
            self.messages_log.append(kwargs.get("messages", []))
            if self.calls == 1:
                return SimpleNamespace(
                    content=[Block(type="tool_use", id="bad-1", name="spawn_teammate", input={"name": "helper"})],
                )
            return SimpleNamespace(content=[Block(type="text", text="done")])

    mock = BadToolMessages()
    runner = make_runner(tmp_path, mock)
    result = runner.run("agent", "dev", "work")

    # The subagent recovers and returns the final text response
    assert result == "done"
    # The disallowed tool error is in the conversation history
    # Second call's messages include the tool result from round 1
    second_call_messages = mock.messages_log[1]
    found_error = False
    for msg in second_call_messages:
        content = msg.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and "not allowed" in str(block.get("content", "")):
                    found_error = True
    assert found_error, "Should have found 'not allowed' error in conversation"


def test_run_max_rounds_exceeded(tmp_path: Path):
    class InfiniteToolMessages:
        def create(self, **kwargs):
            return SimpleNamespace(
                content=[Block(type="tool_use", id="inf", name="glob", input={"pattern": "*.txt"})],
            )

    runner = make_runner(tmp_path, InfiniteToolMessages())
    runner.max_rounds = 2
    result = runner.run("agent", "dev", "work")

    assert "exceeded" in result.lower()


def test_run_with_extra_tools(tmp_path: Path):
    handler_results = []

    class ExtraToolMessages:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    content=[Block(type="tool_use", id="extra-1", name="custom_tool", input={"arg": "value"})],
                )
            return SimpleNamespace(content=[Block(type="text", text="done")])

    def custom_handler(arg="default"):
        handler_results.append(arg)
        return f"handled: {arg}"

    runner = make_runner(tmp_path, ExtraToolMessages())
    extra = {
        "custom_tool": (
            {"name": "custom_tool", "description": "Custom", "input_schema": {"type": "object", "properties": {"arg": {"type": "string"}}}},
            custom_handler,
        )
    }
    result = runner.run("agent", "dev", "work", extra_tools=extra)

    # The subagent returns text response, handler is called with correct args
    assert result == "done"
    assert handler_results == ["value"]


def test_run_extra_tool_handler_raises(tmp_path: Path):
    class ErrorToolMessages:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    content=[Block(type="tool_use", id="err-1", name="broken_tool", input={})],
                )
            return SimpleNamespace(content=[Block(type="text", text="recovered")])

    def broken_handler(**kwargs):
        raise ValueError("handler failed")

    runner = make_runner(tmp_path, ErrorToolMessages())
    extra = {
        "broken_tool": (
            {"name": "broken_tool", "description": "B", "input_schema": {"type": "object", "properties": {}}},
            broken_handler,
        )
    }
    result = runner.run("agent", "dev", "work", extra_tools=extra)

    assert "recovered" in result


def test_tool_definition_structure():
    td = SubagentRunner.tool_definition(SubagentRunner)

    assert td["name"] == "run_subagent"
    assert "input_schema" in td
    assert td["input_schema"]["required"] == ["name", "role", "prompt"]
