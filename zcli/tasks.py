from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


TASK_STATUSES = {"pending", "in_progress", "completed"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: str
    owner: str | None
    blockedBy: list[str]
    created_at: str
    updated_at: str


class TaskStore:
    """File-backed task DAG based on learn-claude-code s12."""

    def __init__(self, data_dir: Path):
        self.directory = data_dir / "tasks"
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def _validate_id(task_id: str) -> str:
        if not re.fullmatch(r"task_[A-Za-z0-9_-]{1,80}", task_id):
            raise ValueError(f"invalid task id: {task_id}")
        return task_id

    def path_for(self, task_id: str) -> Path:
        return self.directory / f"{self._validate_id(task_id)}.json"

    def create(self, subject: str, description: str = "", blocked_by: list[str] | None = None) -> Task:
        subject = subject.strip()
        if not subject:
            raise ValueError("task subject cannot be empty")
        dependencies = list(dict.fromkeys(blocked_by or []))
        for dependency in dependencies:
            self._validate_id(dependency)
        now = _now()
        task = Task(
            id=f"task_{uuid4().hex[:12]}",
            subject=subject,
            description=description.strip(),
            status="pending",
            owner=None,
            blockedBy=dependencies,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self.save(task)
        return task

    def save(self, task: Task) -> None:
        if task.status not in TASK_STATUSES:
            raise ValueError(f"invalid task status: {task.status}")
        task.updated_at = _now()
        payload = json.dumps(asdict(task), ensure_ascii=False, indent=2)
        fd, temporary = tempfile.mkstemp(prefix="task-", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(temporary, self.path_for(task.id))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def load(self, task_id: str) -> Task:
        path = self.path_for(task_id)
        if not path.exists():
            raise FileNotFoundError(f"task not found: {task_id}")
        return Task(**json.loads(path.read_text(encoding="utf-8")))

    def list(self) -> list[Task]:
        tasks = []
        for path in self.directory.glob("task_*.json"):
            try:
                task = Task(**json.loads(path.read_text(encoding="utf-8")))
                if task.status in TASK_STATUSES:
                    tasks.append(task)
            except (OSError, TypeError, json.JSONDecodeError):
                continue
        return sorted(tasks, key=lambda task: (task.created_at, task.id))

    def can_start(self, task_id: str) -> bool:
        task = self.load(task_id)
        return all(
            self.path_for(dependency).exists()
            and self.load(dependency).status == "completed"
            for dependency in task.blockedBy
        )

    def claim(self, task_id: str, owner: str = "agent") -> str:
        with self._lock:
            task = self.load(task_id)
            if task.status != "pending":
                return f"Task {task.id} is {task.status}, cannot claim"
            if task.owner:
                return f"Task {task.id} already owned by {task.owner}"
            if not self.can_start(task.id):
                blocked = [
                    dependency for dependency in task.blockedBy
                    if not self.path_for(dependency).exists()
                    or self.load(dependency).status != "completed"
                ]
                return f"Task {task.id} is blocked by: {', '.join(blocked)}"
            task.owner = owner.strip() or "agent"
            task.status = "in_progress"
            self.save(task)
            return f"Claimed {task.id} ({task.subject})"

    def complete(self, task_id: str) -> str:
        with self._lock:
            task = self.load(task_id)
            if task.status != "in_progress":
                return f"Task {task.id} is {task.status}, cannot complete"
            task.status = "completed"
            self.save(task)
            unblocked = [
                candidate.subject for candidate in self.list()
                if candidate.status == "pending"
                and candidate.blockedBy
                and task.id in candidate.blockedBy
                and self.can_start(candidate.id)
            ]
            message = f"Completed {task.id} ({task.subject})"
            if unblocked:
                message += f"\nUnblocked: {', '.join(unblocked)}"
            return message

    def get_json(self, task_id: str) -> str:
        return json.dumps(asdict(self.load(task_id)), ensure_ascii=False, indent=2)

    def render(self) -> str:
        tasks = self.list()
        if not tasks:
            return "No tasks."
        return "\n".join(
            f"{task.id}: {task.subject} [{task.status}]"
            + (f" owner={task.owner}" if task.owner else "")
            + (f" blockedBy={','.join(task.blockedBy)}" if task.blockedBy else "")
            for task in tasks
        )

