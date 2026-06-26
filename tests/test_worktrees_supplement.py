"""Supplemental tests for zcli.worktrees — invalid names, path escapes, corrupt registry, _changes errors."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from zcli.tasks import TaskStore
from zcli.worktrees import WorktreeManager


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "zcli@example.test")
    git(repo, "config", "user.name", "ZCLI Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "initial")
    return repo


# ── validate_name ────────────────────────────────────────────────────────

def test_validate_name_valid():
    assert WorktreeManager.validate_name("feature") == "feature"
    assert WorktreeManager.validate_name("feature-1") == "feature-1"
    assert WorktreeManager.validate_name("A" * 64) == "A" * 64


def test_validate_name_too_long():
    with pytest.raises(ValueError):
        WorktreeManager.validate_name("A" * 65)


def test_validate_name_reserved_names():
    with pytest.raises(ValueError):
        WorktreeManager.validate_name(".")
    with pytest.raises(ValueError):
        WorktreeManager.validate_name("..")


def test_validate_name_special_chars():
    with pytest.raises(ValueError):
        WorktreeManager.validate_name("bad name")
    with pytest.raises(ValueError):
        WorktreeManager.validate_name("")


# ── path_for ─────────────────────────────────────────────────────────────

def test_path_for_inside_directory(tmp_path: Path):
    tasks = TaskStore(tmp_path / "data")
    manager = WorktreeManager(tmp_path / "not-git", tmp_path / "data", tasks)
    manager.workspace.mkdir()

    path = manager.path_for("feature")
    assert path.is_relative_to(manager.directory)


# ── resolve not found ────────────────────────────────────────────────────

def test_resolve_not_found(tmp_path: Path):
    tasks = TaskStore(tmp_path / "data")
    manager = WorktreeManager(tmp_path / "not-git", tmp_path / "data", tasks)
    manager.workspace.mkdir()

    with pytest.raises(FileNotFoundError):
        manager.resolve("nonexistent")


# ── _load_registry corrupt ───────────────────────────────────────────────

def test_load_registry_corrupt_json(tmp_path: Path):
    tasks = TaskStore(tmp_path / "data")
    manager = WorktreeManager(tmp_path / "not-git", tmp_path / "data", tasks)
    manager.workspace.mkdir()
    manager.registry_path.write_text("not valid json", encoding="utf-8")

    result = manager._load_registry()
    assert result == {}


def test_load_registry_missing_file(tmp_path: Path):
    tasks = TaskStore(tmp_path / "data")
    manager = WorktreeManager(tmp_path / "not-git", tmp_path / "data", tasks)
    manager.workspace.mkdir()

    assert manager._load_registry() == {}


# ── create duplicate ─────────────────────────────────────────────────────

def test_create_duplicate_name(repository: Path, tmp_path: Path):
    data = repository / ".zcli"
    tasks = TaskStore(data)
    manager = WorktreeManager(repository, data, tasks)

    manager.create("dup")
    result = manager.create("dup")

    assert "already exists" in result
    assert "removed" in manager.remove("dup", discard_changes=True)


# ── bind worktree not found ──────────────────────────────────────────────

def test_bind_worktree_not_found(repository: Path, tmp_path: Path):
    data = repository / ".zcli"
    tasks = TaskStore(data)
    manager = WorktreeManager(repository, data, tasks)

    task = tasks.create("orphan")
    result = manager.bind(task.id, "nonexistent")

    assert "not found" in result


# ── remove not found ─────────────────────────────────────────────────────

def test_remove_not_found(repository: Path, tmp_path: Path):
    data = repository / ".zcli"
    tasks = TaskStore(data)
    manager = WorktreeManager(repository, data, tasks)

    result = manager.remove("nonexistent")

    assert "not found" in result


# ── keep not found ───────────────────────────────────────────────────────

def test_keep_not_found(repository: Path, tmp_path: Path):
    data = repository / ".zcli"
    tasks = TaskStore(data)
    manager = WorktreeManager(repository, data, tasks)

    result = manager.keep("nonexistent")

    assert "not found" in result


# ── _changes with git error ──────────────────────────────────────────────

def test_changes_with_invalid_path(repository: Path, tmp_path: Path):
    data = repository / ".zcli"
    tasks = TaskStore(data)
    manager = WorktreeManager(repository, data, tasks)

    from zcli.worktrees import WorktreeRecord
    record = WorktreeRecord("fake", str(tmp_path / "nonexistent"), "branch", "sha1", None, "now")

    changes = manager._changes(record)
    # Should handle non-existent path gracefully
    assert changes is None or isinstance(changes, tuple)


# ── render empty ─────────────────────────────────────────────────────────

def test_render_empty(repository: Path, tmp_path: Path):
    data = repository / ".zcli"
    tasks = TaskStore(data)
    manager = WorktreeManager(repository, data, tasks)

    assert "No managed worktrees" in manager.render()


# ── _event writes to events file ─────────────────────────────────────────

def test_event_writes_jsonl(repository: Path, tmp_path: Path):
    data = repository / ".zcli"
    tasks = TaskStore(data)
    manager = WorktreeManager(repository, data, tasks)

    manager._event("test", "feature", "task_123")

    lines = manager.events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 1
    event = json.loads(lines[0])
    assert event["event"] == "test"
    assert event["name"] == "feature"


# ── resolve_for_task with no worktree ────────────────────────────────────

def test_resolve_for_task_without_worktree(repository: Path, tmp_path: Path):
    data = repository / ".zcli"
    tasks = TaskStore(data)
    task = tasks.create("no worktree")
    manager = WorktreeManager(repository, data, tasks)

    result = manager.resolve_for_task(task.id)

    assert result == manager.workspace
