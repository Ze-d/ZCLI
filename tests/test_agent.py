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


class FakeCompactMessages:
    """Mock messages.create() for compaction summary."""
    def create(self, **kwargs):
        return SimpleNamespace(content=[Block(type="text", text="对话摘要：用户讨论了项目设计。")])


def test_compact_triggers_after_8_messages(tmp_path: Path):
    """第 4 轮 (8 条消息) 后压缩必须触发，且 summary 非空。"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # context_limit=1 强制任何非空消息立即触发大小检查
    settings = Settings(workspace, tmp_path / "data", "fake-model", None, context_limit=1)
    agent = Agent(settings, client=SimpleNamespace(messages=FakeCompactMessages()), interactive=False)
    session = agent.sessions.create("compact-test")

    # 预先填充 6 条消息（3 轮对话），使第 4 轮达到 8 条
    for i in range(3):
        session.messages.append({"role": "user", "content": f"Q{i}"})
        session.messages.append({"role": "assistant", "content": f"A{i}"})
    assert len(session.messages) == 6

    # 模拟第 4 轮：添加 user 消息后手动调用 compact，验证不会提前触发
    session.messages.append({"role": "user", "content": "Q3"})
    agent._compact_if_needed(session)  # 7 条消息 → < 8，不触发
    assert session.summary == ""  # 尚未触发

    # 添加 assistant 响应后再次检查 → 8 条消息 + size > 1 → 应触发
    session.messages.append({"role": "assistant", "content": "A3"})
    agent._compact_if_needed(session)
    assert session.summary != ""  # 压缩已触发，summary 非空
    assert "<session_summary>" in session.messages[0]["content"]
    # Q0 被摘要替换，原来的第一条 user 消息不再是 "Q0"
    assert session.messages[0]["content"] != "Q0"


def test_compact_split_finds_first_assistant(tmp_path: Path):
    """8 条消息时 split 应从索引 1 (第一个 assistant) 切分。"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = Settings(workspace, tmp_path / "data", "fake-model", None, context_limit=1)
    agent = Agent(settings, client=SimpleNamespace(messages=FakeCompactMessages()), interactive=False)
    session = agent.sessions.create("split-test")

    # 恰好 8 条消息，索引 1 是 assistant
    session.messages = [
        {"role": "user", "content": "Q0"},
        {"role": "assistant", "content": "A0"},
        {"role": "user", "content": "Q1"},
        {"role": "assistant", "content": "A1"},
        {"role": "user", "content": "Q2"},
        {"role": "assistant", "content": "A2"},
        {"role": "user", "content": "Q3"},
        {"role": "assistant", "content": "A3"},
    ]

    agent._compact_if_needed(session)
    assert session.summary != ""
    # recent 应保留索引 1 开始的 7 条（A0..A3），加 1 条 summary = 8
    assert len(session.messages) == 8  # 1 summary + 7 recent


def test_compact_no_trigger_below_threshold(tmp_path: Path):
    """消息不足 8 条时不触发压缩。"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = Settings(workspace, tmp_path / "data", "fake-model", None, context_limit=1)
    agent = Agent(settings, client=SimpleNamespace(messages=FakeCompactMessages()), interactive=False)
    session = agent.sessions.create("no-compact")

    session.messages = [
        {"role": "user", "content": "Q0"},
        {"role": "assistant", "content": "A0"},
    ]
    agent._compact_if_needed(session)
    assert session.summary == ""  # 2 < 8，不触发
