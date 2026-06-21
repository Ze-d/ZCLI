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


def test_create_bind_keep_and_remove_dirty_worktree(repository: Path, tmp_path: Path):
    data = repository / ".zcli"
    tasks = TaskStore(data)
    task = tasks.create("isolated change")
    manager = WorktreeManager(repository, data, tasks)

    created = manager.create("feature", task.id)

    path = manager.path_for("feature")
    assert "created" in created
    assert path.exists()
    assert tasks.load(task.id).worktree == "feature"
    assert "task=" + task.id in manager.render()
    assert "kept" in manager.keep("feature")

    (path / "dirty.txt").write_text("dirty", encoding="utf-8")
    assert "changed file" in manager.remove("feature")
    assert path.exists()
    assert "removed" in manager.remove("feature", discard_changes=True)
    assert not path.exists()
    assert tasks.load(task.id).worktree is None


def test_bind_existing_worktree_and_resolve_task_workspace(repository: Path, tmp_path: Path):
    data = tmp_path / "data"
    tasks = TaskStore(data)
    task = tasks.create("bind later")
    manager = WorktreeManager(repository, data, tasks)
    assert "created" in manager.create("later")

    assert "Bound" in manager.bind(task.id, "later")
    assert manager.resolve_for_task(task.id) == manager.path_for("later")
    assert "removed" in manager.remove("later", discard_changes=True)


def test_worktree_name_and_non_git_workspace_are_rejected(tmp_path: Path):
    tasks = TaskStore(tmp_path / "data")
    manager = WorktreeManager(tmp_path / "not-git", tmp_path / "data", tasks)
    manager.workspace.mkdir()

    with pytest.raises(ValueError):
        manager.create("../escape")
    assert manager.create("valid").startswith("Git error:")
