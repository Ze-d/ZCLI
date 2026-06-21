from pathlib import Path

from zcli.memory import MemoryStore
from zcli.tools import ToolRegistry
from zcli.agent import Agent
from zcli.config import Settings


def test_file_tools_stay_in_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tools = ToolRegistry(workspace, MemoryStore(tmp_path / "data"), interactive=False)

    assert tools.write_file("hello.txt", "hello").startswith("Wrote")
    assert tools.read_file("hello.txt") == "hello"
    assert tools.execute("read_file", {"path": "../outside.txt"}).startswith("Permission denied: path escapes workspace")


def test_remember_tool(tmp_path: Path):
    memory = MemoryStore(tmp_path / "data")
    tools = ToolRegistry(tmp_path, memory, interactive=False)
    result = tools.remember("language", "使用中文", "默认中文回答")

    assert result.startswith("Remembered")
    assert memory.list()[0].body == "默认中文回答"


def test_unknown_tool_returns_error(tmp_path: Path):
    tools = ToolRegistry(tmp_path, MemoryStore(tmp_path / "data"), interactive=False)
    assert tools.execute("does_not_exist", {}) == "Error: unknown tool does_not_exist"


def test_direct_tool_execution_still_enforces_permission(tmp_path: Path):
    tools = ToolRegistry(tmp_path, MemoryStore(tmp_path / "data"), interactive=False)
    assert tools.execute("bash", {"command": "git push"}) == "Permission denied: command requires interactive approval"


def test_planning_tools_are_exposed_to_model(tmp_path: Path):
    tools = ToolRegistry(tmp_path, MemoryStore(tmp_path / "data"), interactive=False)
    names = {definition["name"] for definition in tools.definitions}

    assert {
        "todo_write",
        "create_task",
        "list_tasks",
        "get_task",
        "claim_task",
        "complete_task",
    } <= names


def test_full_agent_exposes_subagent_team_and_worktree_tools(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agent = Agent(Settings(workspace, tmp_path / "data", "fake", None), client=object(), interactive=False)
    try:
        names = {definition["name"] for definition in agent.tools.definitions}
        assert len(names) == 27
        assert {
            "run_subagent",
            "spawn_teammate",
            "send_message",
            "request_plan",
            "create_worktree",
            "bind_task_worktree",
            "remove_worktree",
        } <= names
        assert agent.tools.execute("remove_worktree", {"name": "demo"}).startswith("Permission denied")
    finally:
        agent.close()
