from pathlib import Path

import pytest

from zcli.session import SessionStore


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

