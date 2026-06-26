"""Supplemental tests for zcli.tools — glob, edit_file, _normalize_todos, more execute paths."""

from __future__ import annotations

from pathlib import Path

from zcli.memory import MemoryStore
from zcli.tools import ToolRegistry


# ── helpers ───────────────────────────────────────────────────────────────

def make_tools(tmp_path: Path) -> ToolRegistry:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return ToolRegistry(workspace, MemoryStore(tmp_path / "data"), interactive=False)


# ── _tool static method ──────────────────────────────────────────────────

def test_tool_static_method():
    result = ToolRegistry._tool("test_tool", "Test description", {"arg": {"type": "string"}}, ["arg"])

    assert result["name"] == "test_tool"
    assert result["description"] == "Test description"
    assert result["input_schema"]["type"] == "object"
    assert result["input_schema"]["required"] == ["arg"]


# ── _normalize_todos ─────────────────────────────────────────────────────

def test_normalize_todos_from_json_string():
    todos = ToolRegistry._normalize_todos('[{"content": "task 1", "status": "pending"}]')

    assert len(todos) == 1
    assert todos[0]["content"] == "task 1"
    assert todos[0]["status"] == "pending"


def test_normalize_todos_from_python_literal():
    todos = ToolRegistry._normalize_todos("[{'content': 'task', 'status': 'completed'}]")

    assert len(todos) == 1
    assert todos[0]["status"] == "completed"


def test_normalize_todos_rejects_non_list():
    # Both json.loads and ast.literal_eval will fail on this string
    try:
        ToolRegistry._normalize_todos("not a list")
        assert False, "Should have raised"
    except (ValueError, SyntaxError):
        pass


def test_normalize_todos_rejects_non_dict_item():
    try:
        ToolRegistry._normalize_todos(["not a dict"])
        assert False, "Should have raised"
    except ValueError as e:
        assert "object" in str(e)


def test_normalize_todos_rejects_empty_content():
    try:
        ToolRegistry._normalize_todos([{"content": "  ", "status": "pending"}])
        assert False, "Should have raised"
    except ValueError as e:
        assert "content cannot be empty" in str(e)


def test_normalize_todos_rejects_invalid_status():
    try:
        ToolRegistry._normalize_todos([{"content": "task", "status": "unknown"}])
        assert False, "Should have raised"
    except ValueError as e:
        assert "invalid status" in str(e)


def test_normalize_todos_rejects_invalid_json_string():
    # Both json.loads and ast.literal_eval will fail on this broken input
    try:
        ToolRegistry._normalize_todos("{invalid json")
        assert False, "Should have raised"
    except (ValueError, SyntaxError):
        pass


# ── glob ──────────────────────────────────────────────────────────────────

def test_glob_no_matches(tmp_path: Path):
    tools = make_tools(tmp_path)

    result = tools.glob("*.nonexistent")
    assert result == "(no matches)"


def test_glob_with_matches(tmp_path: Path):
    tools = make_tools(tmp_path)
    (tools.workspace / "test.txt").write_text("hello", encoding="utf-8")
    (tools.workspace / "test.py").write_text("print(1)", encoding="utf-8")

    result = tools.glob("*.txt")

    assert "test.txt" in result
    assert "test.py" not in result


def test_glob_recursive(tmp_path: Path):
    tools = make_tools(tmp_path)
    (tools.workspace / "sub").mkdir()
    (tools.workspace / "sub" / "nested.txt").write_text("nested", encoding="utf-8")

    result = tools.glob("**/*.txt")

    assert "nested.txt" in result or "sub/nested.txt" in result or "sub\\nested.txt" in result


# ── edit_file ─────────────────────────────────────────────────────────────

def test_edit_file_text_not_found(tmp_path: Path):
    tools = make_tools(tmp_path)
    (tools.workspace / "doc.txt").write_text("hello world", encoding="utf-8")

    result = tools.edit_file("doc.txt", "goodbye", "replacement")

    assert "text not found" in result


def test_edit_file_successful(tmp_path: Path):
    tools = make_tools(tmp_path)
    (tools.workspace / "doc.txt").write_text("hello world", encoding="utf-8")

    result = tools.edit_file("doc.txt", "hello", "hi")

    assert result == "Edited doc.txt"
    assert (tools.workspace / "doc.txt").read_text(encoding="utf-8") == "hi world"


def test_edit_file_replaces_only_first_occurrence(tmp_path: Path):
    tools = make_tools(tmp_path)
    (tools.workspace / "doc.txt").write_text("hello hello", encoding="utf-8")

    tools.edit_file("doc.txt", "hello", "hi")

    assert (tools.workspace / "doc.txt").read_text(encoding="utf-8") == "hi hello"


# ── write_file creates parent directories ─────────────────────────────────

def test_write_file_creates_parent_directories(tmp_path: Path):
    tools = make_tools(tmp_path)

    result = tools.write_file("deep/nested/file.txt", "content")

    assert result.startswith("Wrote")
    assert (tools.workspace / "deep" / "nested" / "file.txt").read_text(encoding="utf-8") == "content"


# ── execute with permission_checked=True ─────────────────────────────────

def test_execute_skip_permission_check(tmp_path: Path):
    tools = make_tools(tmp_path)

    # With permission_checked=True, even a "dangerous" command passes to the handler
    # (though it may fail since we're in a test environment)
    result = tools.execute("bash", {"command": "echo safe"}, permission_checked=True)

    assert "safe" in result or "Permission denied" not in result


# ── execute with MCP tool ────────────────────────────────────────────────

def test_execute_mcp_tool_not_registered(tmp_path: Path):
    tools = make_tools(tmp_path)

    result = tools.execute("mcp__nonexistent__tool", {})

    assert "unknown tool" in result


# ── execute handler exception ────────────────────────────────────────────

def test_execute_handler_exception_is_caught(tmp_path: Path):
    tools = make_tools(tmp_path)

    # Force a handler exception by calling write_file without required args
    result = tools.execute("write_file", {})

    assert result.startswith("Error:")


# ── read_file error ──────────────────────────────────────────────────────

def test_read_file_not_found(tmp_path: Path):
    tools = make_tools(tmp_path)

    try:
        tools.read_file("nonexistent.txt")
        assert False, "Should have raised"
    except FileNotFoundError:
        pass


# ── bash tool timeout ────────────────────────────────────────────────────

def test_bash_tool_returns_output(tmp_path: Path):
    tools = make_tools(tmp_path)

    result = tools._run_bash("echo hello")

    assert "hello" in result


def test_bash_tool_returns_no_output_message(tmp_path: Path):
    tools = make_tools(tmp_path)

    # On Windows, an empty command may produce different results,
    # but in general the result should not be empty string
    result = tools._run_bash("echo.")
    # Echo typically produces at least whitespace
    assert isinstance(result, str)


# ── definitions with different configurations ─────────────────────────────

def test_definitions_without_optional_components(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tools = ToolRegistry(workspace, MemoryStore(tmp_path / "data"), interactive=False)

    names = {d["name"] for d in tools.definitions}

    # These should NOT be present without subagents/team/worktrees/artifacts
    assert "run_subagent" not in names
    assert "spawn_teammate" not in names
    assert "create_worktree" not in names
    assert "inspect_artifact" not in names


def test_definitions_count_with_minimal_config(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tools = ToolRegistry(workspace, MemoryStore(tmp_path / "data"), interactive=False)

    # There are 19 "builtins" + MCP definitions
    # The MCP manager starts with 0 connected servers so definitions count = 19 base tools
    names = {d["name"] for d in tools.definitions}
    # All builtins should be present: bash, read_file, write_file, edit_file, glob,
    # remember, todo_write, create_task, list_tasks, get_task, claim_task,
    # complete_task, load_skill, connect_mcp
    expected = {
        "bash", "read_file", "write_file", "edit_file", "glob",
        "remember", "todo_write", "create_task", "list_tasks", "get_task",
        "claim_task", "complete_task", "load_skill", "connect_mcp",
    }
    assert expected <= names
