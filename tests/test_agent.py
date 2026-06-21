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
    assert "[Compacted]" in session.messages[0]["content"]
    # Q0 被摘要替换，原来的第一条 user 消息不再是 "Q0"
    assert session.messages[0]["content"] != "Q0"


def test_full_compact_replaces_history_with_summary(tmp_path: Path):
    """与 s08 一致：完整压缩后只保留一条可继续工作的摘要。"""
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
    assert len(session.messages) == 1
    assert session.messages[0]["content"].startswith("[Compacted]")


class FakeMaxTokensMessages:
    def __init__(self):
        self.max_tokens = []

    def create(self, **kwargs):
        if "tools" not in kwargs:
            return SimpleNamespace(content=[Block(type="text", text="[]")], stop_reason="end_turn")
        self.max_tokens.append(kwargs["max_tokens"])
        if len(self.max_tokens) == 1:
            return SimpleNamespace(content=[Block(type="text", text="截断内容")], stop_reason="max_tokens")
        return SimpleNamespace(content=[Block(type="text", text="完整内容")], stop_reason="end_turn")


def test_max_tokens_escalates_without_saving_first_truncated_response(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = Settings(workspace, tmp_path / "data", "fake-model", None, max_tokens=100, escalated_max_tokens=200)
    messages = FakeMaxTokensMessages()
    agent = Agent(settings, client=SimpleNamespace(messages=messages), interactive=False)
    session = agent.sessions.create("max-tokens")

    output = agent.run_turn(session, "生成内容", emit=lambda _: None)

    assert output == "完整内容"
    assert messages.max_tokens == [100, 200]
    assert "截断内容" not in str(session.messages)


class FakePromptTooLongMessages:
    def __init__(self):
        self.main_calls = 0

    def create(self, **kwargs):
        if "tools" not in kwargs:
            return SimpleNamespace(content=[Block(type="text", text="恢复摘要")], stop_reason="end_turn")
        self.main_calls += 1
        if self.main_calls == 1:
            raise RuntimeError("context_length_exceeded: prompt is too long")
        return SimpleNamespace(content=[Block(type="text", text="恢复成功")], stop_reason="end_turn")


def test_prompt_too_long_reactive_compacts_once_and_retries(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    messages = FakePromptTooLongMessages()
    agent = Agent(Settings(workspace, tmp_path / "data", "fake-model", None), client=SimpleNamespace(messages=messages), interactive=False)
    session = agent.sessions.create("reactive")

    assert agent.run_turn(session, "继续", emit=lambda _: None) == "恢复成功"
    assert messages.main_calls == 2
    assert list((tmp_path / "data" / "transcripts").glob("reactive_*.jsonl"))


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
