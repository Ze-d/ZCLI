from pathlib import Path

from zcli.context import ContextManager, estimate_tokens, is_tool_result_message, message_has_tool_use


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


def test_tool_result_budget_persists_largest_results_until_under_budget(tmp_path: Path):
    manager = ContextManager(tmp_path, 50_000, persist_threshold=100, tool_result_budget_bytes=3_000)
    messages = [{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "small", "content": "s" * 20},
        {"type": "tool_result", "tool_use_id": "large", "content": "L" * 5_000},
    ]}]

    manager.tool_result_budget(messages)

    assert messages[0]["content"][0]["content"] == "s" * 20
    assert "<persisted-output>" in messages[0]["content"][1]["content"]
    assert (tmp_path / "tool-results" / "large.txt").exists()


def test_prepare_runs_cheap_layers_before_llm_summary(tmp_path: Path):
    events = []

    class RecordingContextManager(ContextManager):
        def tool_result_budget(self, messages):
            events.append("budget")
            return super().tool_result_budget(messages)

        def snip_compact(self, messages):
            events.append("snip")
            return super().snip_compact(messages)

        def micro_compact(self, messages):
            events.append("micro")
            return super().micro_compact(messages)

        def compact_history(self, messages, summarize):
            events.append("summary")
            return super().compact_history(messages, summarize)

    manager = RecordingContextManager(tmp_path, context_limit=1)
    compacted, summary = manager.prepare(
        [{"role": "user", "content": "long enough to exceed one estimated token"}],
        lambda _: "working summary",
    )

    assert events == ["budget", "snip", "micro", "summary"]
    assert summary == "working summary"
    assert compacted == [{"role": "user", "content": "[Compacted]\n\nworking summary"}]
    assert list((tmp_path / "transcripts").glob("compact_*.jsonl"))


def test_reactive_compact_preserves_boundary_tool_pair_and_transcript(tmp_path: Path):
    manager = ContextManager(tmp_path, 50_000)
    messages = [
        *tool_pair("boundary", "result"),
        {"role": "assistant", "content": "a"},
        {"role": "user", "content": "b"},
        {"role": "assistant", "content": "c"},
        {"role": "user", "content": "d"},
    ]

    compacted, summary = manager.reactive_compact(messages, lambda _: "recovery summary")

    assert summary == "recovery summary"
    assert_no_orphan_results(compacted)
    assert list((tmp_path / "transcripts").glob("reactive_*.jsonl"))


def test_estimate_tokens_uses_four_character_approximation():
    messages = [{"role": "user", "content": "x" * 100}]
    assert estimate_tokens(messages) >= 25
