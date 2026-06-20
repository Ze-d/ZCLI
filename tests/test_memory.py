from pathlib import Path

from zcli.memory import MemoryStore


def test_remember_rebuild_and_retrieve(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.remember("language-preference", "用户偏好使用中文", "默认使用中文回答。")

    assert "language-preference.md" in store.index()
    assert store.relevant("你记得我的中文偏好吗")[0].name == "language-preference"


def test_save_extracted_json(tmp_path: Path):
    store = MemoryStore(tmp_path)
    count = store.save_extracted('[{"name":"quotes","type":"feedback","description":"使用单引号","body":"Python 使用单引号。"}]')

    assert count == 1
    assert store.list()[0].type == "feedback"

