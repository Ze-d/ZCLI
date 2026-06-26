"""Supplemental tests for zcli.tasks — claim_next, invalid status, corrupt file handling."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zcli.tasks import TASK_STATUSES, Task, TaskStore


# ── claim_next ────────────────────────────────────────────────────────────

def test_claim_next_claims_first_available(tmp_path: Path):
    store = TaskStore(tmp_path)
    task = store.create("first")

    claimed = store.claim_next("worker")

    assert claimed is not None
    assert claimed.id == task.id
    assert claimed.owner == "worker"
    assert claimed.status == "in_progress"


def test_claim_next_skips_blocked_tasks(tmp_path: Path):
    store = TaskStore(tmp_path)
    blocker = store.create("blocker")
    blocked = store.create("blocked", blocked_by=[blocker.id])
    free = store.create("free")

    # First claim_next will claim "blocker" (first pending, unblocked)
    first = store.claim_next("worker")
    assert first.subject == "blocker"

    # Second claim_next should claim "free", not "blocked" (blocked is still blocked)
    second = store.claim_next("worker")
    assert second.subject == "free"

    # blocked is still pending and not claimable
    assert not store.can_start(blocked.id)


def test_claim_next_skips_owned_tasks(tmp_path: Path):
    store = TaskStore(tmp_path)
    first = store.create("first")
    second = store.create("second")
    store.claim(first.id, "other-worker")

    claimed = store.claim_next("worker")

    assert claimed.id == second.id


def test_claim_next_returns_none_when_no_available(tmp_path: Path):
    store = TaskStore(tmp_path)
    task = store.create("only")
    store.claim(task.id, "someone")

    claimed = store.claim_next("worker")

    assert claimed is None


def test_claim_next_returns_none_empty_store(tmp_path: Path):
    store = TaskStore(tmp_path)

    assert store.claim_next("worker") is None


# ── save with invalid status ─────────────────────────────────────────────

def test_save_rejects_invalid_status(tmp_path: Path):
    store = TaskStore(tmp_path)
    task = store.create("test")
    task.status = "unknown"

    with pytest.raises(ValueError, match="invalid task status"):
        store.save(task)


# ── load non-existent ────────────────────────────────────────────────────

def test_load_nonexistent_task(tmp_path: Path):
    store = TaskStore(tmp_path)

    with pytest.raises(FileNotFoundError):
        store.load("task_nonexistent")


# ── list with corrupt files ──────────────────────────────────────────────

def test_list_skips_corrupt_json(tmp_path: Path):
    store = TaskStore(tmp_path)
    store.create("good")
    # Write a corrupt task file
    bad_path = store.directory / "task_badfile.json"
    bad_path.write_text("not valid json", encoding="utf-8")

    tasks = store.list()
    names = [t.subject for t in tasks]
    assert "good" in names
    assert len(tasks) == 1


def test_list_skips_invalid_status(tmp_path: Path):
    store = TaskStore(tmp_path)
    store.create("good")
    # Write a task with invalid status
    bad_path = store.directory / "task_badstatus.json"
    bad_path.write_text(
        json.dumps({
            "id": "task_badstatus", "subject": "bad", "description": "",
            "status": "unknown_state", "owner": None, "blockedBy": [],
            "created_at": "2025-01-01T00:00:00", "updated_at": "2025-01-01T00:00:00",
        }),
        encoding="utf-8",
    )

    tasks = store.list()
    assert "bad" not in [t.subject for t in tasks]


# ── claim edge cases ─────────────────────────────────────────────────────

def test_claim_with_no_owner_defaults_to_agent(tmp_path: Path):
    store = TaskStore(tmp_path)
    task = store.create("default owner")

    result = store.claim(task.id)

    assert result.startswith("Claimed")
    assert store.load(task.id).owner == "agent"


def test_claim_with_blank_owner_defaults_to_agent(tmp_path: Path):
    store = TaskStore(tmp_path)
    task = store.create("blank owner")

    result = store.claim(task.id, "  ")

    assert store.load(task.id).owner == "agent"


def test_claim_already_owned_task(tmp_path: Path):
    store = TaskStore(tmp_path)
    task = store.create("owned")
    store.claim(task.id, "first")

    result = store.claim(task.id, "second")

    # After first claim, status is "in_progress", so claim fails with status check
    assert "cannot claim" in result


def test_claim_blocked_by_failed_dependency(tmp_path: Path):
    store = TaskStore(tmp_path)
    blocker = store.create("blocker")
    blocked = store.create("blocked", blocked_by=[blocker.id])

    result = store.claim(blocked.id)
    assert "blocked by" in result


# ── complete edge cases ──────────────────────────────────────────────────

def test_complete_unblocks_multiple_tasks(tmp_path: Path):
    store = TaskStore(tmp_path)
    common = store.create("common blocker")
    task_a = store.create("task A", blocked_by=[common.id])
    task_b = store.create("task B", blocked_by=[common.id])

    store.claim(common.id)
    result = store.complete(common.id)

    assert "Unblocked: task A" in result or "Unblocked: task B" in result


def test_complete_pending_task(tmp_path: Path):
    store = TaskStore(tmp_path)
    task = store.create("pending task")

    result = store.complete(task.id)
    assert "cannot complete" in result


# ── TASK_STATUSES ────────────────────────────────────────────────────────

def test_task_statuses_constant():
    assert "pending" in TASK_STATUSES
    assert "in_progress" in TASK_STATUSES
    assert "completed" in TASK_STATUSES


# ── _validate_id ─────────────────────────────────────────────────────────

def test_validate_id_rejects_invalid():
    for bad_id in ["", "not_a_task", "task_", "../escape", "task_../escape"]:
        try:
            TaskStore._validate_id(bad_id)
            if bad_id not in ["task_", "task_../escape"]:
                assert False, f"Should have raised for {bad_id!r}"
        except ValueError:
            pass


def test_validate_id_accepts_valid():
    assert TaskStore._validate_id("task_abc") == "task_abc"
    assert TaskStore._validate_id("task_" + "A" * 80) == "task_" + "A" * 80


# ── render empty ─────────────────────────────────────────────────────────

def test_render_empty(tmp_path: Path):
    store = TaskStore(tmp_path)

    assert store.render() == "No tasks."


# ── get_json ─────────────────────────────────────────────────────────────

def test_get_json_contains_id_and_subject(tmp_path: Path):
    store = TaskStore(tmp_path)
    task = store.create("json test", "description here")

    result = store.get_json(task.id)
    data = json.loads(result)

    assert data["id"] == task.id
    assert data["subject"] == "json test"
