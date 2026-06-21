import time
from pathlib import Path

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


def test_file_message_bus_consumes_messages_once(tmp_path: Path):
    bus = MessageBus(tmp_path)
    bus.send("lead", "alice", "hello")

    assert bus.count("alice") == 1
    assert bus.read("alice")[0].content == "hello"
    assert bus.read("alice") == []


def test_teammate_background_messages_plan_and_shutdown(tmp_path: Path):
    runner = FakeRunner()
    team = TeamManager(
        tmp_path,
        runner,
        TaskStore(tmp_path),
        poll_interval=0.01,
        idle_timeout=5,
    )
    try:
        assert "spawned" in team.spawn("alice", "backend", "initial task")
        assert wait_until(lambda: team.bus.count("lead") >= 1)
        assert "[completion]" in team.check_inbox()

        assert "Sent" in team.send_message("alice", "follow up")
        assert wait_until(lambda: team.bus.count("lead") >= 1)
        assert "follow up" in team.check_inbox()

        plan_result = team.request_plan("alice", "plan the API")
        request_id = plan_result.rsplit("(", 1)[1].rstrip(")")
        assert wait_until(lambda: team.bus.count("lead") >= 1)
        submission = team.check_inbox()
        assert "[plan_submission]" in submission
        assert request_id in submission
        assert "approved" in team.review_plan(request_id, True, "go ahead")

        assert "Shutdown requested" in team.request_shutdown("alice")
        assert wait_until(lambda: team.members["alice"].status == "stopped")
    finally:
        team.close()


def test_idle_teammate_auto_claims_unblocked_task(tmp_path: Path):
    tasks = TaskStore(tmp_path)
    task = tasks.create("autonomous")
    runner = FakeRunner()
    team = TeamManager(tmp_path, runner, tasks, poll_interval=0.01, idle_timeout=1)
    try:
        team.spawn("bob", "worker", "stand by")
        assert wait_until(lambda: tasks.load(task.id).owner == "bob")
        assert any(call[3] == task.id for call in runner.calls)
    finally:
        team.close()
