"""Supplemental tests for zcli.session — duplicate ID, load_or_create, corrupt list, repair edge cases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zcli.session import Session, SessionStore, repair_tool_protocol


# ── SessionStore create ──────────────────────────────────────────────────

def test_create_custom_id(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = store.create("my-custom-id")

    assert session.id == "my-custom-id"
    assert store.path_for("my-custom-id").exists()


def test_create_duplicate_id_raises(tmp_path: Path):
    store = SessionStore(tmp_path)
    store.create("unique")

    with pytest.raises(FileExistsError):
        store.create("unique")


def test_create_auto_generated_id(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = store.create()

    assert session.id.startswith("session-")
    assert len(session.id) > 8


# ── SessionStore load_or_create ──────────────────────────────────────────

def test_load_or_create_loads_existing(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = store.create("existing")
    session.messages.append({"role": "user", "content": "saved"})
    store.save(session)

    loaded = store.load_or_create("existing")

    assert loaded.messages[0]["content"] == "saved"


def test_load_or_create_creates_new(tmp_path: Path):
    store = SessionStore(tmp_path)

    session = store.load_or_create("new-one")

    assert session.id == "new-one"
    assert session.messages == []


# ── SessionStore list ────────────────────────────────────────────────────

def test_list_multiple_sessions_sorted(tmp_path: Path):
    store = SessionStore(tmp_path)
    a = store.create("session-a")
    b = store.create("session-b")
    c = store.create("session-c")

    # Update in reverse order
    import time
    time.sleep(0.01)
    store.save(c)
    time.sleep(0.01)
    store.save(a)

    sessions = store.list()
    # Most recent first
    assert sessions[0].id == "session-a"


def test_list_skips_corrupt_json(tmp_path: Path):
    store = SessionStore(tmp_path)
    store.create("good")
    # Write corrupt file
    bad_path = store.directory / "bad.json"
    bad_path.write_text("not valid json", encoding="utf-8")

    sessions = store.list()
    ids = [s.id for s in sessions]
    assert "good" in ids
    assert "bad" not in ids


def test_list_handles_type_error(tmp_path: Path):
    store = SessionStore(tmp_path)
    store.create("good")
    # JSON that parses but doesn't match Session fields
    bad_path = store.directory / "wrong.json"
    bad_path.write_text('{"not": "a session"}', encoding="utf-8")

    sessions = store.list()
    ids = [s.id for s in sessions]
    assert "good" in ids


# ── Session defaults ────────────────────────────────────────────────────

def test_session_defaults():
    session = Session("test-id", "2025-01-01T00:00:00", "2025-01-01T00:00:00")

    assert session.messages == []
    assert session.summary == ""
    assert session.todos == []
    assert session.rounds_since_todo == 0


# ── repair_tool_protocol edge cases ──────────────────────────────────────

def test_repair_empty_tool_use_id_skipped():
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "", "name": "bad", "input": {}},
        ]},
    ]

    repaired, count = repair_tool_protocol(messages)

    assert count >= 1  # Empty id is skipped/counted
    # The bad block should be removed from assistant content
    assistant = repaired[0]
    assert all(
        block.get("id") != "" for block in assistant["content"]
        if isinstance(block, dict) and block.get("type") == "tool_use"
    )


def test_repair_mixed_content_blocks():
    messages = [
        {"role": "assistant", "content": [
            {"type": "text", "text": "reasoning"},
            {"type": "tool_use", "id": "t1", "name": "bash", "input": {}},
            {"type": "text", "text": "more reasoning"},
        ]},
    ]

    repaired, count = repair_tool_protocol(messages)

    # Text blocks preserved, tool_use gets synthetic result
    assert len(repaired) == 2  # assistant + synthetic user result
    assert repaired[1]["role"] == "user"
    assert len(repaired[1]["content"]) == 1  # synthetic tool_result


def test_repair_orphaned_tool_results_removed():
    messages = [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "orphan", "content": "no matching tool_use"},
            {"type": "text", "text": "some text"},
        ]},
    ]

    repaired, count = repair_tool_protocol(messages)
    # Orphaned tool_results removed from user message without preceding assistant
    # Text blocks preserved
    assert count >= 1
    if repaired:  # If there's still content after cleanup
        first_content = repaired[0].get("content", [])
        # No tool_results should remain
        tool_results = [b for b in first_content if isinstance(b, dict) and b.get("type") == "tool_result"]
        assert len(tool_results) == 0


def test_repair_no_messages():
    repaired, count = repair_tool_protocol([])

    assert repaired == []
    assert count == 0


def test_repair_duplicate_tool_result_id():
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "bash", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "first"},
            {"type": "tool_result", "tool_use_id": "t1", "content": "duplicate"},
        ]},
    ]

    repaired, count = repair_tool_protocol(messages)
    # Duplicate tool_result_id triggers repair_count increment
    assert count >= 1
