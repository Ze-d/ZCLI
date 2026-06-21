from pathlib import Path

from zcli.memory import MemoryStore
from zcli.tools import ToolRegistry


def test_file_tools_stay_in_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tools = ToolRegistry(workspace, MemoryStore(tmp_path / "data"), interactive=False)

    assert tools.write_file("hello.txt", "hello").startswith("Wrote")
    assert tools.read_file("hello.txt") == "hello"
    assert tools.execute("read_file", {"path": "../outside.txt"}).startswith("Error: ValueError")


def test_remember_tool(tmp_path: Path):
    memory = MemoryStore(tmp_path / "data")
    tools = ToolRegistry(tmp_path, memory, interactive=False)
    result = tools.remember("language", "使用中文", "默认中文回答")

    assert result.startswith("Remembered")
    assert memory.list()[0].body == "默认中文回答"


def test_unknown_tool_returns_error(tmp_path: Path):
    tools = ToolRegistry(tmp_path, MemoryStore(tmp_path / "data"), interactive=False)
    assert tools.execute("does_not_exist", {}) == "Error: unknown tool does_not_exist"
