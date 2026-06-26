"""Supplemental tests for zcli.agent — _blocks_to_dicts, system_prompt, _extract_memories."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from zcli.agent import Agent, _blocks_to_dicts
from zcli.config import Settings


class Block:
    def __init__(self, **values):
        self.values = values

    def model_dump(self, exclude_none=True):
        return self.values


# ── _blocks_to_dicts ──────────────────────────────────────────────────────

def test_blocks_to_dicts_with_model_dump():
    block = Block(type="text", text="hello")
    result = _blocks_to_dicts([block])
    assert result == [{"type": "text", "text": "hello"}]


def test_blocks_to_dicts_with_plain_dict():
    result = _blocks_to_dicts([{"type": "text", "text": "hello"}])
    assert result == [{"type": "text", "text": "hello"}]


def test_blocks_to_dicts_with_unknown_object():
    class RawBlock:
        type = "text"
        text = "hello"
        id = None
        name = None
        input = None

    result = _blocks_to_dicts([RawBlock()])
    assert result[0]["type"] == "text"
    assert result[0]["text"] == "hello"
    assert "id" not in result[0]  # None values excluded


# ── system_prompt ─────────────────────────────────────────────────────────

def make_agent(tmp_path: Path) -> Agent:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = Settings(workspace, tmp_path / "data", "test-model", None)
    return Agent(settings, client=SimpleNamespace(), interactive=False)


def test_system_prompt_has_workspace(tmp_path: Path):
    agent = make_agent(tmp_path)
    prompt = agent.system_prompt("hello")
    assert str(agent.settings.workspace) in prompt


def test_system_prompt_without_session(tmp_path: Path):
    agent = make_agent(tmp_path)
    prompt = agent.system_prompt("hello")
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_system_prompt_with_session_todos(tmp_path: Path):
    agent = make_agent(tmp_path)
    session = agent.sessions.create("with-todos")
    session.todos = [{"content": "write tests", "status": "in_progress"}]

    prompt = agent.system_prompt("hello", session)

    assert "[in_progress] write tests" in prompt


def test_system_prompt_without_todos(tmp_path: Path):
    agent = make_agent(tmp_path)
    session = agent.sessions.create("no-todos")

    prompt = agent.system_prompt("hello", session)

    assert "Current session todos" not in prompt


def test_system_prompt_includes_skill_catalog(tmp_path: Path):
    agent = make_agent(tmp_path)
    prompt = agent.system_prompt("hello")

    assert "Skills catalog" in prompt or "no skills" in prompt.lower()


def test_system_prompt_includes_team_status(tmp_path: Path):
    agent = make_agent(tmp_path)
    prompt = agent.system_prompt("hello")

    assert "Team status" in prompt or "teammates" in prompt.lower()


def test_system_prompt_includes_worktree_status(tmp_path: Path):
    agent = make_agent(tmp_path)
    prompt = agent.system_prompt("hello")

    assert "Worktrees" in prompt or "worktrees" in prompt.lower()


def test_system_prompt_includes_mcp_status(tmp_path: Path):
    agent = make_agent(tmp_path)
    prompt = agent.system_prompt("hello")

    assert "MCP" in prompt or "mcp" in prompt.lower()


# ── _extract_memories ────────────────────────────────────────────────────

class ExtractionMessages:
    def __init__(self, response_text="[]"):
        self.main_calls = 0
        self.extract_calls = 0
        self.response_text = response_text

    def create(self, **kwargs):
        if "tools" not in kwargs:
            self.extract_calls += 1
            return SimpleNamespace(content=[Block(type="text", text=self.response_text)])
        self.main_calls += 1
        return SimpleNamespace(content=[Block(type="text", text="done")], stop_reason="end_turn")


def test_extract_memories_with_empty_result(tmp_path: Path):
    agent = make_agent(tmp_path)
    agent.client = SimpleNamespace(messages=ExtractionMessages("[]"))

    # Should not raise
    agent._extract_memories([{"role": "user", "content": "hello"}])


def test_extract_memories_with_valid_json(tmp_path: Path):
    agent = make_agent(tmp_path)
    agent.client = SimpleNamespace(
        messages=ExtractionMessages(
            '[{"name": "pref", "description": "desc", "body": "body", "type": "user"}]'
        )
    )

    agent._extract_memories([{"role": "user", "content": "remember this preference"}])

    memories = agent.memory.list()
    assert any(m.name == "pref" for m in memories)


def test_extract_memories_api_error_is_silent(tmp_path: Path):
    agent = make_agent(tmp_path)

    class FailingMessages:
        def create(self, **kwargs):
            raise RuntimeError("API unavailable")

    agent.client = SimpleNamespace(messages=FailingMessages())

    # Should not raise — memory extraction is best-effort
    agent._extract_memories([{"role": "user", "content": "hello"}])
    # Test passes if no exception


def test_close_cleans_up(tmp_path: Path):
    agent = make_agent(tmp_path)
    agent.close()
    # Should not raise
