import json

import pytest

from zcli.tasks import TaskStore


def test_task_dependency_claim_complete_and_unlock(tmp_path):
    store = TaskStore(tmp_path)
    schema = store.create("schema")
    api = store.create("api", blocked_by=[schema.id])

    assert not store.can_start(api.id)
    assert "blocked by" in store.claim(api.id)
    assert store.claim(schema.id, "zcli").startswith("Claimed")
    completed = store.complete(schema.id)

    assert "Unblocked: api" in completed
    assert store.can_start(api.id)
    assert store.claim(api.id).startswith("Claimed")


def test_task_graph_persists_across_store_instances(tmp_path):
    first = TaskStore(tmp_path)
    task = first.create("persistent", "survives sessions")
    first.claim(task.id)

    loaded = TaskStore(tmp_path).load(task.id)

    assert loaded.subject == "persistent"
    assert loaded.status == "in_progress"
    assert json.loads(TaskStore(tmp_path).get_json(task.id))["owner"] == "agent"


def test_missing_dependency_remains_blocked(tmp_path):
    store = TaskStore(tmp_path)
    task = store.create("blocked", blocked_by=["task_missing"])

    assert not store.can_start(task.id)
    assert "task_missing" in store.claim(task.id)


def test_task_state_machine_rejects_invalid_transitions(tmp_path):
    store = TaskStore(tmp_path)
    task = store.create("stateful")

    assert "pending, cannot complete" in store.complete(task.id)
    store.claim(task.id)
    assert "in_progress, cannot claim" in store.claim(task.id)
    store.complete(task.id)
    assert "completed, cannot complete" in store.complete(task.id)


def test_invalid_task_input_is_rejected(tmp_path):
    store = TaskStore(tmp_path)
    with pytest.raises(ValueError):
        store.create(" ")
    with pytest.raises(ValueError):
        store.create("bad dependency", blocked_by=["../escape"])


def test_task_worktree_binding_persists_and_renders(tmp_path):
    store = TaskStore(tmp_path)
    task = store.create("isolated")

    store.bind_worktree(task.id, "feature")

    assert TaskStore(tmp_path).load(task.id).worktree == "feature"
    assert "worktree=feature" in store.render()
    assert store.unbind_worktree("feature") == [task.id]
    assert store.load(task.id).worktree is None
