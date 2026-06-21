from types import SimpleNamespace

from zcli.agent import Agent
from zcli.config import Settings
from zcli.memory import MemoryStore
from zcli.session import SessionStore
from zcli.tools import ToolRegistry


class Block:
    def __init__(self, **values):
        self.values = values

    def model_dump(self, exclude_none=True):
        return self.values


def test_todo_write_validates_and_persists_with_session(tmp_path):
    sessions = SessionStore(tmp_path / "data")
    session = sessions.create("todo")
    tools = ToolRegistry(tmp_path, MemoryStore(tmp_path / "data"), interactive=False)

    result = tools.execute(
        "todo_write",
        {"todos": [
            {"content": "inspect", "status": "completed"},
            {"content": "implement", "status": "in_progress"},
        ]},
        session=session,
    )
    sessions.save(session)

    assert "[x] inspect" in result
    assert sessions.load("todo").todos[1]["status"] == "in_progress"


def test_todo_write_rejects_invalid_status_and_requires_session(tmp_path):
    tools = ToolRegistry(tmp_path, MemoryStore(tmp_path / "data"), interactive=False)
    invalid = tools.execute("todo_write", {"todos": [{"content": "x", "status": "unknown"}]}, session=SimpleNamespace(todos=[], rounds_since_todo=0))
    missing = tools.execute("todo_write", {"todos": []})

    assert "invalid status" in invalid
    assert "requires an active session" in missing


class ReminderMessages:
    def __init__(self):
        self.main_calls = 0
        self.final_messages = None

    def create(self, **kwargs):
        if "tools" not in kwargs:
            return SimpleNamespace(content=[Block(type="text", text="[]")], stop_reason="end_turn")
        self.main_calls += 1
        if self.main_calls <= 3:
            return SimpleNamespace(
                content=[Block(type="tool_use", id=f"glob-{self.main_calls}", name="glob", input={"pattern": "*.none"})],
                stop_reason="tool_use",
            )
        self.final_messages = kwargs["messages"]
        return SimpleNamespace(content=[Block(type="text", text="done")], stop_reason="end_turn")


def test_three_non_todo_tools_inject_reminder_and_reset_counter(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client = SimpleNamespace(messages=ReminderMessages())
    agent = Agent(Settings(workspace, tmp_path / "data", "fake", None), client=client, interactive=False)
    session = agent.sessions.create("reminder")

    assert agent.run_turn(session, "multi-step", emit=lambda _: None) == "done"

    assert any("<reminder>Update your todos.</reminder>" in str(message) for message in client.messages.final_messages)
    assert session.rounds_since_todo == 0


def test_todos_are_injected_into_system_prompt(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agent = Agent(Settings(workspace, tmp_path / "data", "fake", None), client=SimpleNamespace(), interactive=False)
    session = agent.sessions.create("system")
    session.todos = [{"content": "write tests", "status": "in_progress"}]

    assert "[in_progress] write tests" in agent.system_prompt("continue", session)
