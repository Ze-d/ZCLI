"""Supplemental tests for zcli.context — helper functions, write_transcript, prepare without session."""

from __future__ import annotations

from pathlib import Path

from zcli.context import (
    ContextManager,
    collect_tool_results,
    estimate_tokens,
    is_tool_result_message,
    message_has_tool_use,
)


# ── estimate_tokens ──────────────────────────────────────────────────────

def test_estimate_tokens_empty_messages():
    assert estimate_tokens([]) == 1  # max(1, 0) = 1


def test_estimate_tokens_single_message():
    tokens = estimate_tokens([{"role": "user", "content": "x" * 400}])
    # size ~= 400 + overhead, // 4 >= 100
    assert tokens >= 100


# ── message_has_tool_use ─────────────────────────────────────────────────

def test_message_has_tool_use_true():
    msg = {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "bash", "input": {}}]}
    assert message_has_tool_use(msg)


def test_message_has_tool_use_false_for_user():
    msg = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}
    assert not message_has_tool_use(msg)


def test_message_has_tool_use_false_text_only():
    msg = {"role": "assistant", "content": "plain text response"}
    assert not message_has_tool_use(msg)


def test_message_has_tool_use_false_empty():
    msg = {"role": "assistant", "content": []}
    assert not message_has_tool_use(msg)


# ── is_tool_result_message ───────────────────────────────────────────────

def test_is_tool_result_true():
    msg = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}
    assert is_tool_result_message(msg)


def test_is_tool_result_false_assistant():
    msg = {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "bash", "input": {}}]}
    assert not is_tool_result_message(msg)


def test_is_tool_result_false_plain_text():
    msg = {"role": "user", "content": "plain text"}
    assert not is_tool_result_message(msg)


# ── collect_tool_results ─────────────────────────────────────────────────

def test_collect_tool_results_empty():
    assert collect_tool_results([]) == []


def test_collect_tool_results_finds_all():
    messages = [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "a", "content": "ok"},
            {"type": "tool_result", "tool_use_id": "b", "content": "also ok"},
        ]},
    ]
    results = collect_tool_results(messages)
    assert len(results) == 2


def test_collect_tool_results_skips_assistant():
    messages = [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "bash", "input": {}}]},
    ]
    results = collect_tool_results(messages)
    assert len(results) == 0


# ── _source_tool ─────────────────────────────────────────────────────────

def test_source_tool_finds_tool_name():
    messages = [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "call-1", "name": "bash", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call-1", "content": "ok"}]},
    ]
    assert ContextManager._source_tool(messages, "call-1") == "bash"


def test_source_tool_unknown():
    messages = [
        {"role": "user", "content": "hello"},
    ]
    assert ContextManager._source_tool(messages, "unknown-id") == "unknown"


# ── snip_compact edge cases ──────────────────────────────────────────────

def test_snip_compact_small_list_unchanged(tmp_path: Path):
    manager = ContextManager(tmp_path, 50_000, max_messages=100)
    messages = [{"role": "user", "content": "hello"}]

    result = manager.snip_compact(messages)
    assert result == messages


def test_snip_compact_exact_max(tmp_path: Path):
    manager = ContextManager(tmp_path, 50_000, max_messages=3)
    messages = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "c"},
    ]

    result = manager.snip_compact(messages)
    assert len(result) == 3  # exactly max_messages, no snipping needed


# ── write_transcript ─────────────────────────────────────────────────────

def test_write_transcript_creates_file(tmp_path: Path):
    manager = ContextManager(tmp_path, 50_000)
    messages = [{"role": "user", "content": "hello"}]

    path = manager.write_transcript(messages, "test-label")

    assert path.exists()
    assert "test-label" in path.name
    content = path.read_text(encoding="utf-8")
    assert "hello" in content


# ── compact_history edge case ────────────────────────────────────────────

def test_compact_history_empty_summary(tmp_path: Path):
    manager = ContextManager(tmp_path, 50_000)
    messages = [{"role": "user", "content": "hello"}]

    compacted, summary = manager.compact_history(messages, lambda _: "")

    assert "empty summary" in summary
    assert "Compacted" in compacted[0]["content"]


# ── reactive_compact summarize exception ─────────────────────────────────

def test_reactive_compact_summarize_raises(tmp_path: Path):
    manager = ContextManager(tmp_path, 50_000)
    messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]

    compacted, summary = manager.reactive_compact(messages, lambda _: (_ for _ in ()).throw(RuntimeError("boom")))

    assert "Reactive compact" in compacted[0]["content"]
    # Should have a fallback message


def test_reactive_compact_no_summarize(tmp_path: Path):
    manager = ContextManager(tmp_path, 50_000)
    messages = [{"role": "user", "content": "hello"}]

    compacted, summary = manager.reactive_compact(messages, None)

    assert "trimmed" in summary.lower() or "prompt" in summary.lower() or summary
    assert len(compacted) >= 1


# ── prepare without session_id ───────────────────────────────────────────

def test_prepare_without_session_id(tmp_path: Path):
    manager = ContextManager(tmp_path, 50_000, tool_result_budget_bytes=1000)
    messages = [{"role": "user", "content": "hello world"}]

    prepared, summary = manager.prepare(messages, lambda _: "summary")

    # Without session_id, tool_result_budget runs without artifacts
    assert prepared is not None
    assert len(prepared) >= 1


def test_prepare_with_session_id(tmp_path: Path):
    manager = ContextManager(tmp_path, 50_000)
    messages = [{"role": "user", "content": "hello"}]

    prepared, summary = manager.prepare(messages, lambda _: "summary", session_id="session-a")

    assert prepared is not None


# ── tool_result_budget no blocks ─────────────────────────────────────────

def test_tool_result_budget_no_tool_results(tmp_path: Path):
    manager = ContextManager(tmp_path, 50_000)
    messages = [{"role": "user", "content": "plain text"}]

    result = manager.tool_result_budget(messages)
    assert result == messages


def test_tool_result_budget_empty_messages(tmp_path: Path):
    manager = ContextManager(tmp_path, 50_000)
    result = manager.tool_result_budget([])
    assert result == []
