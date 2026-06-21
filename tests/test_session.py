from pathlib import Path

import pytest

from zcli.session import SessionStore, repair_tool_protocol


def test_session_round_trip(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = store.create("demo")
    session.messages.append({"role": "user", "content": "你好"})
    store.save(session)

    loaded = store.load("demo")
    assert loaded.messages[0]["content"] == "你好"
    assert store.list()[0].id == "demo"


def test_session_id_rejects_path_escape(tmp_path: Path):
    store = SessionStore(tmp_path)
    with pytest.raises(ValueError):
        store.create("../escape")


def test_repair_tool_protocol_inserts_missing_results_before_later_user_message():
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "a", "name": "one", "input": {}},
            {"type": "tool_use", "id": "b", "name": "two", "input": {}},
        ]},
        {"role": "user", "content": "a later prompt"},
    ]

    repaired, count = repair_tool_protocol(messages)

    assert count == 2
    assert repaired[1]["role"] == "user"
    assert [block["tool_use_id"] for block in repaired[1]["content"]] == ["a", "b"]
    assert all(block["is_error"] for block in repaired[1]["content"])
    assert repaired[2]["content"] == "a later prompt"


def test_session_load_repairs_partial_and_orphaned_tool_results(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = store.create("damaged")
    session.messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "a", "name": "one", "input": {}},
            {"type": "tool_use", "id": "b", "name": "two", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "a", "content": "ok"},
            {"type": "tool_result", "tool_use_id": "orphan", "content": "bad"},
        ]},
    ]
    store.save(session)

    loaded = store.load("damaged")

    results = loaded.messages[1]["content"]
    assert [result["tool_use_id"] for result in results] == ["a", "b"]
    assert results[0]["content"] == "ok"
    assert results[1]["is_error"] is True
    raw = store.path_for("damaged").read_text(encoding="utf-8")
    assert "orphan" not in raw
