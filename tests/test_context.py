from pathlib import Path

from zcli.context import ContextManager, is_tool_result_message, message_has_tool_use


def tool_pair(identifier: str, output: str = "ok") -> list[dict]:
    return [
        {"role": "assistant", "content": [{"type": "tool_use", "id": identifier, "name": "bash", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": identifier, "content": output}]},
    ]


def assert_no_orphan_results(messages: list[dict]) -> None:
    for index, message in enumerate(messages):
        if is_tool_result_message(message):
            assert index > 0
            assert message_has_tool_use(messages[index - 1])


def test_snip_compact_preserves_tool_pairs(tmp_path: Path):
    manager = ContextManager(tmp_path, 50_000, max_messages=6)
    messages = [{"role": "user", "content": "start"}, *tool_pair("a"), {"role": "assistant", "content": "middle"}, *tool_pair("b"), {"role": "assistant", "content": "end"}]
    assert_no_orphan_results(manager.snip_compact(messages))


def test_large_tool_output_is_persisted_and_previewed(tmp_path: Path):
    manager = ContextManager(tmp_path, 50_000, persist_threshold=10)
    replacement = manager.persist_large_output("tool-1", "x" * 100)
    assert "<persisted-output>" in replacement
    assert (tmp_path / "tool-results" / "tool-1.txt").read_text(encoding="utf-8") == "x" * 100


def test_micro_compact_keeps_only_recent_tool_results(tmp_path: Path):
    manager = ContextManager(tmp_path, 50_000, keep_recent_tool_results=1)
    messages = [*tool_pair("a", "a" * 200), *tool_pair("b", "b" * 200)]
    manager.micro_compact(messages)
    assert "Earlier tool result" in messages[1]["content"][0]["content"]
    assert messages[3]["content"][0]["content"] == "b" * 200

