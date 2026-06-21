from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .subagents import SubagentRunner, validate_agent_name
from .tasks import TaskStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class TeamMessage:
    id: str
    sender: str
    recipient: str
    type: str
    content: str
    request_id: str | None
    timestamp: str


class MessageBus:
    """File-backed consumable mailboxes based on learn-claude-code s15."""

    def __init__(self, data_dir: Path):
        self.directory = data_dir / "team-mailboxes"
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, agent: str) -> Path:
        if agent != "lead":
            validate_agent_name(agent)
        return self.directory / f"{agent}.jsonl"

    def send(
        self,
        sender: str,
        recipient: str,
        content: str,
        message_type: str = "message",
        request_id: str | None = None,
    ) -> TeamMessage:
        if sender != "lead":
            validate_agent_name(sender)
        message = TeamMessage(
            id=f"msg_{uuid4().hex[:12]}",
            sender=sender,
            recipient=recipient,
            type=message_type,
            content=content,
            request_id=request_id,
            timestamp=_now(),
        )
        path = self._path(recipient)
        with self._lock, path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(message), ensure_ascii=False) + "\n")
        return message

    def read(self, agent: str) -> list[TeamMessage]:
        return self.read_types(agent)

    def read_types(self, agent: str, allowed: set[str] | None = None) -> list[TeamMessage]:
        path = self._path(agent)
        with self._lock:
            if not path.exists():
                return []
            try:
                messages = [
                    TeamMessage(**json.loads(line))
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
            except (OSError, TypeError, json.JSONDecodeError):
                return []
            selected = messages if allowed is None else [message for message in messages if message.type in allowed]
            remaining = [] if allowed is None else [message for message in messages if message.type not in allowed]
            fd, temporary = tempfile.mkstemp(prefix="mailbox-", suffix=".tmp", dir=self.directory)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                for message in remaining:
                    handle.write(json.dumps(asdict(message), ensure_ascii=False) + "\n")
            os.replace(temporary, path)
            return selected

    def count(self, agent: str) -> int:
        path = self._path(agent)
        if not path.exists():
            return 0
        try:
            return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])
        except OSError:
            return 0


@dataclass
class TeammateState:
    name: str
    role: str
    status: str
    started_at: str
    auto_claim: bool = False
    last_result: str = ""


class TeamManager:
    """Named background teammates, typed messages, plans, and auto-claim."""

    def __init__(
        self,
        data_dir: Path,
        runner: SubagentRunner,
        tasks: TaskStore,
        *,
        poll_interval: float = 0.5,
        idle_timeout: float = 60.0,
    ):
        self.bus = MessageBus(data_dir)
        self.runner = runner
        self.tasks = tasks
        self.poll_interval = poll_interval
        self.idle_timeout = idle_timeout
        self.members: dict[str, TeammateState] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._stops: dict[str, threading.Event] = {}
        self._plan_targets: dict[str, str] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
        return {
            "name": name,
            "description": description,
            "input_schema": {"type": "object", "properties": properties, "required": required},
        }

    def spawn(self, name: str, role: str, prompt: str, auto_claim: bool = False) -> str:
        name = validate_agent_name(name)
        if not prompt.strip():
            return "Error: teammate prompt cannot be empty"
        with self._lock:
            current = self.members.get(name)
            if current and current.status not in {"stopped", "completed", "failed"}:
                return f"Teammate '{name}' already exists with status {current.status}"
            self.bus.read(name)
            state = TeammateState(
                name,
                role.strip() or "generalist",
                "starting",
                _now(),
                auto_claim=auto_claim,
            )
            stop_event = threading.Event()
            self.members[name] = state
            self._stops[name] = stop_event
            thread = threading.Thread(
                target=self._teammate_loop,
                args=(state, prompt.strip(), stop_event),
                daemon=True,
                name=f"zcli-teammate-{name}",
            )
            self._threads[name] = thread
            thread.start()
        return f"Teammate '{name}' spawned as {state.role}"

    def _extra_tools(self, name: str) -> dict:
        return {
            "send_message": (
                self._tool(
                    "send_message",
                    "Send a message to lead or another teammate.",
                    {"to": {"type": "string"}, "content": {"type": "string"}},
                    ["to", "content"],
                ),
                lambda to, content: self.send_message(to, content, sender=name),
            ),
            "check_inbox": (
                self._tool("check_inbox", "Read and consume your teammate inbox.", {}, []),
                lambda: self._check_teammate_inbox(name),
            ),
        }

    def _check_teammate_inbox(self, name: str) -> str:
        messages = self.bus.read_types(name, {"message", "plan_review"})
        if not messages:
            return "Inbox empty."
        return "\n".join(
            f"[{message.type}] from={message.sender}: {message.content}" for message in messages
        )

    def _run_work(self, state: TeammateState, prompt: str, stop_event: threading.Event, task_id: str = "") -> str:
        state.status = "working"
        result = self.runner.run(
            state.name,
            state.role,
            prompt,
            task_id=task_id,
            stop_event=stop_event,
            extra_tools=self._extra_tools(state.name),
        )
        state.last_result = result
        return result

    def _teammate_loop(self, state: TeammateState, initial_prompt: str, stop_event: threading.Event) -> None:
        try:
            result = self._run_work(state, initial_prompt, stop_event)
            self.bus.send(state.name, "lead", result, "completion")
            idle_since = time.monotonic()
            state.status = "idle"
            while not stop_event.is_set() and time.monotonic() - idle_since < self.idle_timeout:
                inbox = self.bus.read(state.name)
                if inbox:
                    idle_since = time.monotonic()
                    for message in inbox:
                        if message.type == "shutdown_request":
                            stop_event.set()
                            self.bus.send(
                                state.name,
                                "lead",
                                "Shutdown acknowledged",
                                "shutdown_response",
                                message.request_id,
                            )
                            break
                        prompt = message.content
                        response_type = "message_response"
                        if message.type == "plan_request":
                            prompt = "Return a concrete implementation plan only.\n\n" + prompt
                            response_type = "plan_submission"
                        elif message.type == "plan_review":
                            prompt = "Revise your work or plan using this review.\n\n" + prompt
                        result = self._run_work(state, prompt, stop_event)
                        self.bus.send(state.name, "lead", result, response_type, message.request_id)
                    state.status = "idle"
                    continue
                task = self.tasks.claim_next(state.name) if state.auto_claim else None
                if task:
                    idle_since = time.monotonic()
                    result = self._run_work(
                        state,
                        f"Work on durable task {task.id}: {task.subject}\n{task.description}",
                        stop_event,
                        task.id,
                    )
                    self.bus.send(state.name, "lead", result, "task_completion", task.id)
                    state.status = "idle"
                    continue
                time.sleep(self.poll_interval)
            state.status = "stopped" if stop_event.is_set() else "completed"
        except Exception as exc:
            state.status = "failed"
            state.last_result = f"{type(exc).__name__}: {exc}"
            self.bus.send(state.name, "lead", state.last_result, "failure")

    def send_message(self, to: str, content: str, sender: str = "lead") -> str:
        if to != "lead":
            validate_agent_name(to)
            state = self.members.get(to)
            if not state:
                return f"Teammate '{to}' not found"
            if state.status in {"stopped", "completed", "failed"}:
                return f"Teammate '{to}' is {state.status}"
        message = self.bus.send(sender, to, content, "message")
        return f"Sent {message.id} from {sender} to {to}"

    def check_inbox(self, agent: str = "lead") -> str:
        messages = self.bus.read(agent)
        if not messages:
            return "Inbox empty."
        return "\n".join(
            f"[{message.type}] from={message.sender}"
            + (f" request={message.request_id}" if message.request_id else "")
            + f": {message.content}"
            for message in messages
        )

    def request_shutdown(self, teammate: str) -> str:
        validate_agent_name(teammate)
        state = self.members.get(teammate)
        if not state:
            return f"Teammate '{teammate}' not found"
        if state.status in {"stopped", "completed", "failed"}:
            return f"Teammate '{teammate}' is already {state.status}"
        request_id = f"shutdown_{uuid4().hex[:10]}"
        self.bus.send("lead", teammate, "Please stop after the current safe boundary.", "shutdown_request", request_id)
        return f"Shutdown requested for '{teammate}' ({request_id})"

    def request_plan(self, teammate: str, task: str) -> str:
        validate_agent_name(teammate)
        state = self.members.get(teammate)
        if not state:
            return f"Teammate '{teammate}' not found"
        if state.status in {"stopped", "completed", "failed"}:
            return f"Teammate '{teammate}' is {state.status}"
        request_id = f"plan_{uuid4().hex[:10]}"
        self._plan_targets[request_id] = teammate
        self.bus.send("lead", teammate, task, "plan_request", request_id)
        return f"Plan requested from '{teammate}' ({request_id})"

    def review_plan(self, request_id: str, approve: bool, feedback: str = "") -> str:
        teammate = self._plan_targets.get(request_id)
        if not teammate:
            return f"Plan request not found: {request_id}"
        decision = "approved" if approve else "rejected"
        content = f"Plan {decision}. {feedback}".strip()
        self.bus.send("lead", teammate, content, "plan_review", request_id)
        if approve:
            self._plan_targets.pop(request_id, None)
        return f"Plan {request_id} {decision}"

    def render(self) -> str:
        with self._lock:
            if not self.members:
                return "No teammates."
            lines = [
                f"{state.name}: role={state.role} status={state.status}"
                + (" autoClaim=on" if state.auto_claim else "")
                for state in sorted(self.members.values(), key=lambda item: item.name)
            ]
        unread = self.bus.count("lead")
        if unread:
            lines.append(f"lead inbox: {unread} unread")
        return "\n".join(lines)

    def close(self) -> None:
        with self._lock:
            stops = list(self._stops.values())
            threads = list(self._threads.values())
        for stop in stops:
            stop.set()
        for thread in threads:
            thread.join(timeout=2)
