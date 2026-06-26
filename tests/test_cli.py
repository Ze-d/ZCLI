"""Tests for zcli.cli — argument parsing and main() function."""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from zcli.cli import build_parser, main


# ── build_parser ──────────────────────────────────────────────────────────

def test_parser_defaults():
    parser = build_parser()
    args = parser.parse_args([])

    assert args.workspace is None
    assert args.session == "default"
    assert args.new is False
    assert args.list_sessions is False


def test_parser_workspace_flag():
    parser = build_parser()
    args = parser.parse_args(["--workspace", "/tmp/project"])

    assert args.workspace == Path("/tmp/project")


def test_parser_session_flag():
    parser = build_parser()
    args = parser.parse_args(["--session", "my-session"])

    assert args.session == "my-session"


def test_parser_new_flag():
    parser = build_parser()
    args = parser.parse_args(["--new"])

    assert args.new is True


def test_parser_list_sessions_flag():
    parser = build_parser()
    args = parser.parse_args(["--list-sessions"])

    assert args.list_sessions is True


def test_parser_combined_flags():
    parser = build_parser()
    args = parser.parse_args(["--workspace", "/tmp/proj", "--session", "dev", "--new"])

    assert args.workspace == Path("/tmp/proj")
    assert args.session == "dev"
    assert args.new is True


# ── main() helpers ────────────────────────────────────────────────────────

class Block:
    def __init__(self, **values):
        self.values = values

    def model_dump(self, exclude_none=True):
        return self.values


class FakeAgent:
    """Minimal fake Agent for CLI testing."""

    def __init__(self, settings):
        self.settings = settings
        self.closed = False
        from zcli.memory import MemoryStore
        from zcli.session import Session, SessionStore
        from zcli.skills import SkillRegistry
        from zcli.tasks import TaskStore
        from zcli.teams import TeamManager

        self.memory = MemoryStore(settings.data_dir)
        self.sessions = SessionStore(settings.data_dir)
        self.tasks = TaskStore(settings.data_dir)
        self.skills = SkillRegistry(settings.workspace / "skills")
        self.mcp = SimpleNamespace(
            status=lambda: "MCP: no servers connected",
            errors=[],
        )
        self.team = SimpleNamespace(
            render=lambda: "No teammates.",
            check_inbox=lambda: "Inbox empty.",
        )
        self.worktrees = SimpleNamespace(
            render=lambda: "No managed worktrees.",
        )

    def run_turn(self, session, query, emit=None):
        pass

    def close(self):
        self.closed = True


def test_main_list_sessions(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("ZCLI_DATA_DIR", str(data_dir))

    from zcli.config import Settings
    with patch("zcli.cli.Agent", return_value=FakeAgent(Settings(workspace, data_dir, "fake", None))):
        captured = StringIO()
        with patch("sys.stdout", captured):
            result = main(["--workspace", str(workspace), "--list-sessions"])

    assert result == 0


def test_main_empty_input_continues(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("ZCLI_DATA_DIR", str(data_dir))

    from zcli.config import Settings
    with patch("zcli.cli.Agent", return_value=FakeAgent(Settings(workspace, data_dir, "fake", None))):
        # Simulate empty input then /exit
        inputs = iter(["", "  ", "/exit"])
        with patch("builtins.input", lambda _: next(inputs)):
            captured = StringIO()
            with patch("sys.stdout", captured):
                result = main(["--workspace", str(workspace)])

    assert result == 0


def test_main_slash_memory(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("ZCLI_DATA_DIR", str(data_dir))

    from zcli.config import Settings
    agent = FakeAgent(Settings(workspace, data_dir, "fake", None))
    with patch("zcli.cli.Agent", return_value=agent):
        inputs = iter(["/memory", "/exit"])
        with patch("builtins.input", lambda _: next(inputs)):
            captured = StringIO()
            with patch("sys.stdout", captured):
                main(["--workspace", str(workspace)])

    assert agent.closed


def test_main_slash_sessions(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("ZCLI_DATA_DIR", str(data_dir))

    from zcli.config import Settings
    agent = FakeAgent(Settings(workspace, data_dir, "fake", None))
    with patch("zcli.cli.Agent", return_value=agent):
        inputs = iter(["/sessions", "/exit"])
        with patch("builtins.input", lambda _: next(inputs)):
            captured = StringIO()
            with patch("sys.stdout", captured):
                main(["--workspace", str(workspace)])

    assert agent.closed


def test_main_slash_todos_empty(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("ZCLI_DATA_DIR", str(data_dir))

    from zcli.config import Settings
    agent = FakeAgent(Settings(workspace, data_dir, "fake", None))
    with patch("zcli.cli.Agent", return_value=agent):
        inputs = iter(["/todos", "/exit"])
        with patch("builtins.input", lambda _: next(inputs)):
            captured = StringIO()
            with patch("sys.stdout", captured):
                main(["--workspace", str(workspace)])
            output = captured.getvalue()

    assert "(no todos)" in output
    assert agent.closed


def test_main_slash_tasks(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("ZCLI_DATA_DIR", str(data_dir))

    from zcli.config import Settings
    agent = FakeAgent(Settings(workspace, data_dir, "fake", None))
    with patch("zcli.cli.Agent", return_value=agent):
        inputs = iter(["/tasks", "/exit"])
        with patch("builtins.input", lambda _: next(inputs)):
            captured = StringIO()
            with patch("sys.stdout", captured):
                main(["--workspace", str(workspace)])

    assert agent.closed


def test_main_slash_skills(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("ZCLI_DATA_DIR", str(data_dir))

    from zcli.config import Settings
    agent = FakeAgent(Settings(workspace, data_dir, "fake", None))
    with patch("zcli.cli.Agent", return_value=agent):
        inputs = iter(["/skills", "/exit"])
        with patch("builtins.input", lambda _: next(inputs)):
            captured = StringIO()
            with patch("sys.stdout", captured):
                main(["--workspace", str(workspace)])

    assert agent.closed


def test_main_slash_mcp(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("ZCLI_DATA_DIR", str(data_dir))

    from zcli.config import Settings
    agent = FakeAgent(Settings(workspace, data_dir, "fake", None))
    with patch("zcli.cli.Agent", return_value=agent):
        inputs = iter(["/mcp", "/exit"])
        with patch("builtins.input", lambda _: next(inputs)):
            captured = StringIO()
            with patch("sys.stdout", captured):
                main(["--workspace", str(workspace)])

    assert agent.closed


def test_main_slash_team(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("ZCLI_DATA_DIR", str(data_dir))

    from zcli.config import Settings
    agent = FakeAgent(Settings(workspace, data_dir, "fake", None))
    with patch("zcli.cli.Agent", return_value=agent):
        inputs = iter(["/team", "/exit"])
        with patch("builtins.input", lambda _: next(inputs)):
            captured = StringIO()
            with patch("sys.stdout", captured):
                main(["--workspace", str(workspace)])

    assert agent.closed


def test_main_slash_worktrees(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("ZCLI_DATA_DIR", str(data_dir))

    from zcli.config import Settings
    agent = FakeAgent(Settings(workspace, data_dir, "fake", None))
    with patch("zcli.cli.Agent", return_value=agent):
        inputs = iter(["/worktrees", "/exit"])
        with patch("builtins.input", lambda _: next(inputs)):
            captured = StringIO()
            with patch("sys.stdout", captured):
                main(["--workspace", str(workspace)])

    assert agent.closed


def test_main_slash_quit(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("ZCLI_DATA_DIR", str(data_dir))

    from zcli.config import Settings
    agent = FakeAgent(Settings(workspace, data_dir, "fake", None))
    with patch("zcli.cli.Agent", return_value=agent):
        inputs = iter(["/quit"])
        with patch("builtins.input", lambda _: next(inputs)):
            captured = StringIO()
            with patch("sys.stdout", captured):
                result = main(["--workspace", str(workspace)])

    assert result == 0
    assert agent.closed


def test_main_keyboard_interrupt_exits(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("ZCLI_DATA_DIR", str(data_dir))

    from zcli.config import Settings
    agent = FakeAgent(Settings(workspace, data_dir, "fake", None))
    with patch("zcli.cli.Agent", return_value=agent):
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            captured = StringIO()
            with patch("sys.stdout", captured):
                result = main(["--workspace", str(workspace)])

    assert result == 0
    assert agent.closed


def test_main_eof_error_exits(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("ZCLI_DATA_DIR", str(data_dir))

    from zcli.config import Settings
    agent = FakeAgent(Settings(workspace, data_dir, "fake", None))
    with patch("zcli.cli.Agent", return_value=agent):
        with patch("builtins.input", side_effect=EOFError):
            captured = StringIO()
            with patch("sys.stdout", captured):
                result = main(["--workspace", str(workspace)])

    assert result == 0
    assert agent.closed


def test_main_run_turn_exception_is_caught(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("ZCLI_DATA_DIR", str(data_dir))

    from zcli.config import Settings

    class ErrorAgent(FakeAgent):
        def run_turn(self, session, query, emit=None):
            raise RuntimeError("test error")

    agent = ErrorAgent(Settings(workspace, data_dir, "fake", None))
    with patch("zcli.cli.Agent", return_value=agent):
        inputs = iter(["hello", "/exit"])
        with patch("builtins.input", lambda _: next(inputs)):
            captured = StringIO()
            with patch("sys.stdout", captured):
                result = main(["--workspace", str(workspace)])
            output = captured.getvalue()

    assert result == 0
    assert "RuntimeError: test error" in output
    assert agent.closed


def test_main_new_session_flag(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("ZCLI_DATA_DIR", str(data_dir))

    from zcli.config import Settings
    agent = FakeAgent(Settings(workspace, data_dir, "fake", None))
    with patch("zcli.cli.Agent", return_value=agent):
        inputs = iter(["/exit"])
        with patch("builtins.input", lambda _: next(inputs)):
            captured = StringIO()
            with patch("sys.stdout", captured):
                result = main(["--workspace", str(workspace), "--new", "--session", "fresh"])

    assert result == 0
    assert agent.closed


def test_main_slash_todos_with_items(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("ZCLI_DATA_DIR", str(data_dir))

    from zcli.config import Settings
    from zcli.session import Session, SessionStore

    agent = FakeAgent(Settings(workspace, data_dir, "fake", None))
    # Pre-populate session with todos
    session = agent.sessions.create("default")
    session.todos = [{"content": "write tests", "status": "in_progress"}]
    agent.sessions.save(session)

    with patch("zcli.cli.Agent", return_value=agent):
        inputs = iter(["/todos", "/exit"])
        with patch("builtins.input", lambda _: next(inputs)):
            captured = StringIO()
            with patch("sys.stdout", captured):
                main(["--workspace", str(workspace)])
            output = captured.getvalue()

    assert "[in_progress]" in output
    assert agent.closed


def test_main_slash_team_with_inbox(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("ZCLI_DATA_DIR", str(data_dir))

    from zcli.config import Settings

    agent = FakeAgent(Settings(workspace, data_dir, "fake", None))
    agent.team = SimpleNamespace(
        render=lambda: "No teammates.",
        check_inbox=lambda: "[message] from=alice: hello",
    )

    with patch("zcli.cli.Agent", return_value=agent):
        inputs = iter(["/team", "/exit"])
        with patch("builtins.input", lambda _: next(inputs)):
            captured = StringIO()
            with patch("sys.stdout", captured):
                main(["--workspace", str(workspace)])
            output = captured.getvalue()

    assert "[message] from=alice: hello" in output
    assert agent.closed
