"""Supplemental tests for zcli.teams — validate_agent_name, send_message edges, review_plan, exceptions."""

from __future__ import annotations

import time
from pathlib import Path

from zcli.subagents import validate_agent_name
from zcli.tasks import TaskStore
from zcli.teams import MessageBus, TeamManager


def wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class FakeRunner:
    def __init__(self):
        self.calls = []

    def run(self, name, role, prompt, task_id="", **kwargs):
        self.calls.append((name, role, prompt, task_id))
        return f"{name} result: {prompt}"


# ── validate_agent_name ──────────────────────────────────────────────────

def test_validate_agent_name_valid():
    assert validate_agent_name("alice") == "alice"
    assert validate_agent_name("bob-42") == "bob-42"
    assert validate_agent_name("test_agent") == "test_agent"
    assert validate_agent_name("A" * 32) == "A" * 32


def test_validate_agent_name_too_long():
    try:
        validate_agent_name("A" * 33)
        assert False, "Should have raised"
    except ValueError:
        pass


def test_validate_agent_name_empty():
    try:
        validate_agent_name("")
        assert False, "Should have raised"
    except ValueError:
        pass


def test_validate_agent_name_special_chars():
    try:
        validate_agent_name("bad name!")
        assert False, "Should have raised"
    except ValueError:
        pass


def test_validate_agent_name_leading_dash():
    try:
        validate_agent_name("-bad")
        assert False, "Should have raised"
    except ValueError:
        pass


# ── MessageBus edge cases ────────────────────────────────────────────────

def test_message_bus_read_types_with_filter(tmp_path: Path):
    bus = MessageBus(tmp_path)
    bus.send("lead", "alice", "hello", "message")
    bus.send("lead", "alice", "plan this", "plan_request")

    messages = bus.read_types("alice", {"message"})
    assert len(messages) == 1
    assert messages[0].type == "message"

    # The plan_request should still be there
    remaining = bus.read("alice")
    assert len(remaining) == 1
    assert remaining[0].type == "plan_request"


def test_message_bus_read_corrupt_jsonl(tmp_path: Path):
    bus = MessageBus(tmp_path)
    path = bus._path("alice")
    path.write_text("not valid json\n", encoding="utf-8")

    assert bus.read("alice") == []


def test_message_bus_count_nonexistent(tmp_path: Path):
    bus = MessageBus(tmp_path)
    assert bus.count("nobody") == 0


def test_message_bus_read_nonexistent_agent(tmp_path: Path):
    bus = MessageBus(tmp_path)
    assert bus.read("nobody") == []


def test_message_bus_send_and_count(tmp_path: Path):
    bus = MessageBus(tmp_path)
    assert bus.count("alice") == 0

    bus.send("lead", "alice", "msg1")
    bus.send("lead", "alice", "msg2")

    assert bus.count("alice") == 2


# ── TeamManager send_message ─────────────────────────────────────────────

def test_send_message_to_nonexistent_teammate(tmp_path: Path):
    team = TeamManager(tmp_path, FakeRunner(), TaskStore(tmp_path))
    result = team.send_message("nobody", "hello")
    assert "not found" in result


def test_send_message_to_lead(tmp_path: Path):
    team = TeamManager(tmp_path, FakeRunner(), TaskStore(tmp_path))
    result = team.send_message("lead", "note to self")
    assert "Sent" in result


# ── TeamManager request_shutdown edges ───────────────────────────────────

def test_request_shutdown_nonexistent_teammate(tmp_path: Path):
    team = TeamManager(tmp_path, FakeRunner(), TaskStore(tmp_path))
    result = team.request_shutdown("nobody")
    assert "not found" in result


# ── TeamManager request_plan edges ───────────────────────────────────────

def test_request_plan_nonexistent_teammate(tmp_path: Path):
    team = TeamManager(tmp_path, FakeRunner(), TaskStore(tmp_path))
    result = team.request_plan("nobody", "do something")
    assert "not found" in result


# ── TeamManager review_plan edges ────────────────────────────────────────

def test_review_plan_unknown_request_id(tmp_path: Path):
    team = TeamManager(tmp_path, FakeRunner(), TaskStore(tmp_path))
    result = team.review_plan("unknown_id", True)
    assert "not found" in result


def test_review_plan_rejection(tmp_path: Path):
    runner = FakeRunner()
    team = TeamManager(tmp_path, runner, TaskStore(tmp_path), poll_interval=0.01, idle_timeout=5)
    try:
        team.spawn("alice", "planner", "initial")
        assert wait_until(lambda: team.bus.count("lead") >= 1)
        team.check_inbox()

        plan_result = team.request_plan("alice", "plan feature")
        request_id = plan_result.rsplit("(", 1)[1].rstrip(")")
        assert wait_until(lambda: team.bus.count("lead") >= 1)
        team.check_inbox()

        result = team.review_plan(request_id, False, "needs work")
        assert "rejected" in result
    finally:
        team.close()


# ── TeamManager spawn edges ──────────────────────────────────────────────

def test_spawn_empty_prompt(tmp_path: Path):
    team = TeamManager(tmp_path, FakeRunner(), TaskStore(tmp_path))
    result = team.spawn("worker", "dev", "  ")
    assert "cannot be empty" in result


def test_spawn_duplicate_running(tmp_path: Path):
    team = TeamManager(tmp_path, FakeRunner(), TaskStore(tmp_path), poll_interval=0.01, idle_timeout=5)
    try:
        team.spawn("dup", "worker", "work")
        result = team.spawn("dup", "worker", "more work")
        assert "already exists" in result
    finally:
        team.close()


# ── TeamManager render ───────────────────────────────────────────────────

def test_render_empty_team(tmp_path: Path):
    team = TeamManager(tmp_path, FakeRunner(), TaskStore(tmp_path))
    assert "No teammates" in team.render()


def test_render_with_teammates(tmp_path: Path):
    team = TeamManager(tmp_path, FakeRunner(), TaskStore(tmp_path), poll_interval=0.01, idle_timeout=5)
    try:
        team.spawn("alice", "backend", "task one")
        assert wait_until(lambda: team.members["alice"].status in ("working", "idle"))
        rendered = team.render()
        assert "alice" in rendered
        assert "backend" in rendered
    finally:
        team.close()


def test_render_sorted_by_name(tmp_path: Path):
    runner = FakeRunner()
    team = TeamManager(tmp_path, runner, TaskStore(tmp_path), poll_interval=0.01, idle_timeout=5)
    try:
        team.spawn("charlie", "worker", "c")
        team.spawn("alice", "worker", "a")
        team.spawn("bob", "worker", "b")
        assert wait_until(lambda: len(team.members) == 3)

        rendered = team.render()
        alice_pos = rendered.index("alice")
        bob_pos = rendered.index("bob")
        charlie_pos = rendered.index("charlie")
        assert alice_pos < bob_pos < charlie_pos
    finally:
        team.close()


# ── TeamManager close ───────────────────────────────────────────────────

def test_close_stops_all_threads(tmp_path: Path):
    team = TeamManager(tmp_path, FakeRunner(), TaskStore(tmp_path), poll_interval=0.01, idle_timeout=5)
    team.spawn("quick", "worker", "quick task")
    assert wait_until(lambda: team.members["quick"].status in ("working", "idle"))
    team.close()
    # close() should not hang
    assert True
