from pathlib import Path
from types import SimpleNamespace

from zcli.agent import Agent
from zcli.config import Settings


class Block:
    def __init__(self, **values):
        self.values = values

    def model_dump(self, exclude_none=True):
        return self.values


class FakeMessages:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(content=[Block(type="tool_use", id="t1", name="remember", input={
                "name": "language", "description": "用户偏好中文", "body": "默认使用中文回答。"
            })])
        if self.calls == 2:
            return SimpleNamespace(content=[Block(type="text", text="已经记住。")])
        return SimpleNamespace(content=[Block(type="text", text="[]")])


def test_agent_persists_session_and_explicit_memory(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = Settings(workspace, tmp_path / "data", "fake-model", None)
    client = SimpleNamespace(messages=FakeMessages())
    agent = Agent(settings, client=client, interactive=False)
    session = agent.sessions.create("demo")

    output = agent.run_turn(session, "请记住使用中文", emit=lambda _: None)

    assert output == "已经记住。"
    assert agent.sessions.load("demo").messages
    assert agent.memory.list()[0].name == "language"
