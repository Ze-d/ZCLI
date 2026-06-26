from __future__ import annotations

import json
import re
import subprocess
import threading
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from .tasks import TaskStore


_VALID_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class WorktreeRecord:
    name: str
    path: str
    branch: str
    base_sha: str
    task_id: str | None
    created_at: str


class WorktreeManager:
    """Safe git-worktree lifecycle based on learn-claude-code s18."""

    def __init__(self, workspace: Path, data_dir: Path, tasks: TaskStore):
        self.workspace = workspace.resolve()
        self.directory = (data_dir / "worktrees").resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.registry_path = data_dir / "worktrees.json"
        self.events_path = data_dir / "worktree-events.jsonl"
        self.tasks = tasks
        self._lock = threading.RLock()

    @staticmethod
    def validate_name(name: str) -> str:
        if not _VALID_NAME.fullmatch(name or "") or name in {".", ".."}:
            raise ValueError("worktree name must use letters, digits, dot, underscore or dash (1-64 chars)")
        return name

    def path_for(self, name: str) -> Path:
        name = self.validate_name(name)
        path = (self.directory / name).resolve()
        if not path.is_relative_to(self.directory):
            raise ValueError("worktree path escapes managed directory")
        return path

    def resolve(self, name: str) -> Path:
        name = self.validate_name(name)
        record = self._load_registry().get(name)
        path = self.path_for(name)
        if not record or Path(record.path).resolve() != path or not path.exists():
            raise FileNotFoundError(f"managed worktree not found: {name}")
        return path

    def _git(self, *args: str, cwd: Path | None = None) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=cwd or self.workspace,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = (result.stdout + result.stderr).strip() or "(no output)"
            return result.returncode == 0, output[:10_000]
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def _load_registry(self) -> dict[str, WorktreeRecord]:
        if not self.registry_path.exists():
            return {}
        try:
            values = json.loads(self.registry_path.read_text(encoding="utf-8"))
            return {name: WorktreeRecord(**record) for name, record in values.items()}
        except (OSError, TypeError, json.JSONDecodeError):
            return {}

    def _save_registry(self, records: dict[str, WorktreeRecord]) -> None:
        payload = {name: asdict(record) for name, record in records.items()}
        temporary = self.registry_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.registry_path)

    def _event(self, event: str, name: str, task_id: str | None = None) -> None:
        value = {"event": event, "name": name, "task_id": task_id, "timestamp": _now()}
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False) + "\n")
    # 创建一个新的工作树，如果指定了task_id，则将工作树与该任务绑定，并在Git中创建一个新的分支
    def create(self, name: str, task_id: str = "") -> str:
        name = self.validate_name(name)
        with self._lock:
            records = self._load_registry()
            path = self.path_for(name)
            if name in records or path.exists():
                return f"Worktree '{name}' already exists at {path}"
            if task_id:
                self.tasks.load(task_id)
            ok, base_sha = self._git("rev-parse", "HEAD")
            if not ok:
                return f"Git error: {base_sha}"
            branch = f"zcli/{name}"
            ok, output = self._git("worktree", "add", str(path), "-b", branch, base_sha)
            if not ok:
                return f"Git error: {output}"
            record = WorktreeRecord(name, str(path), branch, base_sha, task_id or None, _now())
            records[name] = record
            self._save_registry(records)
            if task_id:
                self.tasks.bind_worktree(task_id, name)
            self._event("create", name, task_id or None)
            return f"Worktree '{name}' created at {path} (branch: {branch})"

    def bind(self, task_id: str, name: str) -> str:
        name = self.validate_name(name)
        with self._lock:
            records = self._load_registry()
            if name not in records or not self.path_for(name).exists():
                return f"Worktree '{name}' not found"
            task = self.tasks.bind_worktree(task_id, name)
            records[name] = replace(records[name], task_id=task_id)
            self._save_registry(records)
            self._event("bind", name, task_id)
            return f"Bound {task.id} ({task.subject}) to worktree '{name}'"

    def resolve_for_task(self, task_id: str) -> Path:
        task = self.tasks.load(task_id)
        return self.resolve(task.worktree) if task.worktree else self.workspace

    def _changes(self, record: WorktreeRecord) -> tuple[int, int] | None:
        path = Path(record.path)
        ok, status = self._git("status", "--porcelain", cwd=path)
        if not ok:
            return None
        files = len([line for line in status.splitlines() if line and line != "(no output)"])
        ok, count = self._git("rev-list", "--count", f"{record.base_sha}..HEAD", cwd=path)
        if not ok:
            return None
        try:
            commits = int(count.strip())
        except ValueError:
            return None
        return files, commits

    def remove(self, name: str, discard_changes: bool = False) -> str:
        name = self.validate_name(name)
        with self._lock:
            records = self._load_registry()
            record = records.get(name)
            if not record:
                return f"Worktree '{name}' not found"
            path = self.path_for(name)
            if not discard_changes:
                changes = self._changes(record)
                if changes is None:
                    return f"Cannot verify worktree '{name}' status; refuse removal"
                files, commits = changes
                if files or commits:
                    return (
                        f"Worktree '{name}' has {files} changed file(s) and {commits} commit(s). "
                        "Use discard_changes=true to remove, or keep_worktree for review."
                    )
            ok, output = self._git("worktree", "remove", str(path), "--force")
            if not ok:
                return f"Git error: {output}"
            ok, output = self._git("branch", "-D", record.branch)
            records.pop(name, None)
            self._save_registry(records)
            self.tasks.unbind_worktree(name)
            self._event("remove", name, record.task_id)
            if not ok:
                return f"Worktree '{name}' removed; branch cleanup failed: {output}"
            return f"Worktree '{name}' removed"

    def keep(self, name: str) -> str:
        name = self.validate_name(name)
        record = self._load_registry().get(name)
        if not record:
            return f"Worktree '{name}' not found"
        self._event("keep", name, record.task_id)
        return f"Worktree '{name}' kept at {record.path} (branch: {record.branch})"

    def render(self) -> str:
        records = self._load_registry()
        if not records:
            return "No managed worktrees."
        return "\n".join(
            f"{record.name}: {record.path} branch={record.branch}"
            + (f" task={record.task_id}" if record.task_id else "")
            for record in sorted(records.values(), key=lambda item: item.name)
        )
