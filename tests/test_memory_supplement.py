"""Supplemental tests for zcli.memory — _slug, relevant, render_relevant, save_extracted edge cases."""

from __future__ import annotations

from pathlib import Path

import pytest

from zcli.memory import MemoryStore


# ── _slug ─────────────────────────────────────────────────────────────────

def test_slug_normal_name():
    assert MemoryStore._slug("Language Preference") == "language-preference"


def test_slug_chinese_characters():
    slug = MemoryStore._slug("用户偏好")
    assert "用户偏好" in slug or slug


def test_slug_special_characters():
    slug = MemoryStore._slug("hello!@#$%^&*()world")
    assert "hello" in slug
    assert "world" in slug
    assert "!" not in slug


def test_slug_empty_name():
    slug = MemoryStore._slug("   ")
    assert slug == "memory"


def test_slug_truncates_to_80_chars():
    long_name = "a" * 100
    slug = MemoryStore._slug(long_name)
    assert len(slug) <= 80


# ── remember ──────────────────────────────────────────────────────────────

def test_remember_invalid_memory_type_falls_back_to_user(tmp_path: Path):
    store = MemoryStore(tmp_path)
    memory = store.remember("test", "desc", "body", memory_type="invalid")

    assert memory.type == "user"


def test_remember_all_valid_types(tmp_path: Path):
    store = MemoryStore(tmp_path)

    for t in MemoryStore.TYPES:
        memory = store.remember(f"test-{t}", "desc", "body", memory_type=t)
        assert memory.type == t


def test_remember_updates_existing(tmp_path: Path):
    store = MemoryStore(tmp_path)
    first = store.remember("same-name", "first desc", "first body")
    second = store.remember("same-name", "second desc", "second body")

    # Both go to the same file since slug is the same
    assert first.filename == second.filename


# ── _read / list ──────────────────────────────────────────────────────────

def test_read_file_without_frontmatter_is_skipped(tmp_path: Path):
    store = MemoryStore(tmp_path)
    path = store.directory / "no-frontmatter.md"
    path.write_text("Just plain text\n", encoding="utf-8")

    assert store._read(path) is None


def test_list_excludes_memory_index(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.remember("test", "desc", "body")

    memories = store.list()
    filenames = [m.filename for m in memories]
    assert "MEMORY.md" not in filenames


def test_list_handles_corrupt_file(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.remember("good", "desc", "body")
    # Create a corrupt YAML file
    bad_path = store.directory / "bad.md"
    bad_path.write_text("---\nunbalanced: [\n---\nbody", encoding="utf-8")

    memories = store.list()
    names = [m.name for m in memories]
    assert "good" in names


# ── index ─────────────────────────────────────────────────────────────────

def test_index_missing_file_returns_empty(tmp_path: Path):
    store = MemoryStore(tmp_path)
    # Remove index file manually
    if store.index_path.exists():
        store.index_path.unlink()

    assert store.index() == ""


def test_index_returns_contents(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.remember("test-memory", "a test memory", "body content")

    index = store.index()
    assert "test-memory" in index


# ── rebuild_index ─────────────────────────────────────────────────────────

def test_rebuild_index_with_no_memories(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.rebuild_index()

    assert store.index_path.exists()


# ── _terms ────────────────────────────────────────────────────────────────

def test_terms_extracts_latin_words():
    terms = MemoryStore._terms("hello world test")
    assert "hello" in terms
    assert "world" in terms
    assert "test" in terms


def test_terms_extracts_chinese():
    terms = MemoryStore._terms("你好世界")
    assert "你" in terms
    assert "好" in terms


def test_terms_skips_short_latin():
    terms = MemoryStore._terms("a b c")
    assert "a" not in terms  # too short


def test_terms_mixed():
    terms = MemoryStore._terms("Python 编程 language")
    assert "python" in terms
    assert "language" in terms


# ── relevant ──────────────────────────────────────────────────────────────

def test_relevant_returns_empty_when_no_match(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.remember("python-style", "Python code style", "Use single quotes")

    result = store.relevant("java programming")
    assert result == []


def test_relevant_scores_by_term_overlap(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.remember("python-style", "Python code style", "Use single quotes in Python")
    store.remember("java-style", "Java code style", "Use camelCase in Java")

    result = store.relevant("Python programming")

    assert len(result) >= 1
    assert result[0].name == "python-style"


def test_relevant_respects_limit(tmp_path: Path):
    store = MemoryStore(tmp_path)
    for i in range(10):
        store.remember(f"test-{i}", f"test memory {i}", "python test code style format pattern")

    result = store.relevant("python test", limit=3)

    assert len(result) <= 3


# ── render_relevant ───────────────────────────────────────────────────────

def test_render_relevant_no_match_returns_empty(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.remember("python", "Python style", "body")

    result = store.render_relevant("java")
    assert result == ""


def test_render_relevant_wraps_in_tags(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.remember("language", "Language preference", "Use Chinese")

    result = store.render_relevant("language preference")

    assert "<relevant_memories>" in result
    assert "</relevant_memories>" in result
    assert "Language preference" in result or "language" in result


# ── save_extracted ────────────────────────────────────────────────────────

def test_save_extracted_empty_text(tmp_path: Path):
    store = MemoryStore(tmp_path)
    count = store.save_extracted("no json here")
    assert count == 0


def test_save_extracted_invalid_json(tmp_path: Path):
    store = MemoryStore(tmp_path)
    count = store.save_extracted("[not valid json")
    assert count == 0


def test_save_extracted_missing_name_field(tmp_path: Path):
    store = MemoryStore(tmp_path)
    count = store.save_extracted('[{"description": "test", "body": "content"}]')
    assert count == 0


def test_save_extracted_missing_body_field(tmp_path: Path):
    store = MemoryStore(tmp_path)
    count = store.save_extracted('[{"name": "test", "description": "desc"}]')
    assert count == 0


def test_save_extracted_non_list_is_skipped(tmp_path: Path):
    store = MemoryStore(tmp_path)
    count = store.save_extracted('{"name": "test", "body": "content"}')
    assert count == 0


def test_save_extracted_multiple_items(tmp_path: Path):
    store = MemoryStore(tmp_path)
    count = store.save_extracted(
        '['
        '{"name": "pref1", "description": "d1", "body": "b1", "type": "user"},'
        '{"name": "pref2", "description": "d2", "body": "b2", "type": "feedback"}'
        ']'
    )
    assert count == 2
    assert len(store.list()) == 2


def test_save_extracted_has_extra_text_outside_json(tmp_path: Path):
    store = MemoryStore(tmp_path)
    count = store.save_extracted(
        'Some extra text before [{"name": "inside", "description": "d", "body": "b"}] and after'
    )
    assert count == 1
