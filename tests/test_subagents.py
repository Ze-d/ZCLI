from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy

from zcli.config import Settings
from zcli.memory import MemoryStore
from zcli.subagents import SubagentRunner
from zcli.tasks import TaskStore
from zcli.worktrees import WorktreeManager


class Block:
    def __init__(self, **values):
        self.values = values

    def model_dump(self, exclude_none=True):
        return self.values


class SubagentMessages:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        if len(self.calls) == 1:
            return SimpleNamespace(content=[Block(
                type="tool_use",
                id="write-1",
                name="write_file",
                input={"path": "subagent.txt", "content": "isolated"},
            )])
        return SimpleNamespace(content=[Block(type="text", text="subagent done")])


def test_subagent_has_isolated_history_and_restricted_tools(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data = tmp_path / "data"
    messages = SubagentMessages()
    settings = Settings(workspace, data, "fake", None)
    tasks = TaskStore(data)
    runner = SubagentRunner(
        settings,
        SimpleNamespace(messages=messages),
        MemoryStore(data),
        tasks,
        WorktreeManager(workspace, data, tasks),
    )

    result = runner.run("researcher", "research", "Create an isolated file")

    assert result == "subagent done"
    assert (workspace / "subagent.txt").read_text(encoding="utf-8") == "isolated"
    assert messages.calls[0]["messages"] == [{"role": "user", "content": "Create an isolated file"}]
    names = {tool["name"] for tool in messages.calls[0]["tools"]}
    assert "write_file" in names
    assert "run_subagent" not in names
    assert "spawn_teammate" not in names
    assert "remember" not in names


def test_subagent_claims_assigned_task_and_rejects_other_owner(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data = tmp_path / "data"
    settings = Settings(workspace, data, "fake", None)
    tasks = TaskStore(data)
    first = tasks.create("first")
    second = tasks.create("second")
    tasks.claim(second.id, "someone-else")
    runner = SubagentRunner(
        settings,
        SimpleNamespace(messages=SubagentMessages()),
        MemoryStore(data),
        tasks,
        WorktreeManager(workspace, data, tasks),
    )

    assert runner.run("worker", "dev", "work", task_id=first.id) == "subagent done"
    assert tasks.load(first.id).owner == "worker"
    assert "owned by someone-else" in runner.run("worker", "dev", "work", task_id=second.id)
