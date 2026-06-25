from __future__ import annotations

import ast
import glob as globlib
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from .memory import MemoryStore
from .mcp import MCPManager
from .permissions import PermissionPolicy
from .skills import SkillRegistry
from .tasks import TaskStore

if TYPE_CHECKING:
    from .session import Session
    from .subagents import SubagentRunner
    from .teams import TeamManager
    from .worktrees import WorktreeManager


class ToolRegistry:
    def __init__(
        self,
        workspace: Path,
        memory: MemoryStore,
        interactive: bool = True,
        tasks: TaskStore | None = None,
        skills: SkillRegistry | None = None,
        mcp: MCPManager | None = None,
        subagents: SubagentRunner | None = None,
        team: TeamManager | None = None,
        worktrees: WorktreeManager | None = None,
    ):
        self.workspace = workspace.resolve()
        self.memory = memory
        self.tasks = tasks or TaskStore(memory.directory.parent)
        self.skills = skills or SkillRegistry(self.workspace / "skills")
        self.mcp = mcp or MCPManager(self.workspace)
        self.subagents = subagents
        self.team = team
        self.worktrees = worktrees
        self.policy = PermissionPolicy(self.workspace, interactive)
        self.handlers: dict[str, Callable[..., str]] = {
            "bash": self._run_bash,
            "read_file": self.read_file,
            "write_file": self.write_file,
            "edit_file": self.edit_file,
            "glob": self.glob,
            "remember": self.remember,
            "create_task": self.create_task,
            "list_tasks": self.list_tasks,
            "get_task": self.get_task,
            "claim_task": self.claim_task,
            "complete_task": self.complete_task,
            "load_skill": self.load_skill,
            "connect_mcp": self.connect_mcp,
        }
        if self.subagents:
            self.handlers["run_subagent"] = self.run_subagent
        if self.team:
            self.handlers.update({
                "spawn_teammate": self.spawn_teammate,
                "list_teammates": self.list_teammates,
                "send_message": self.send_message,
                "check_inbox": self.check_inbox,
                "request_shutdown": self.request_shutdown,
                "request_plan": self.request_plan,
                "review_plan": self.review_plan,
            })
        if self.worktrees:
            self.handlers.update({
                "create_worktree": self.create_worktree,
                "list_worktrees": self.list_worktrees,
                "bind_task_worktree": self.bind_task_worktree,
                "remove_worktree": self.remove_worktree,
                "keep_worktree": self.keep_worktree,
            })

    @property
    def definitions(self) -> list[dict]:
        builtins = [
            self._tool("bash", "Run a shell command in the workspace.", {"command": {"type": "string"}}, ["command"]),
            self._tool("read_file", "Read a UTF-8 text file.", {"path": {"type": "string"}}, ["path"]),
            self._tool("write_file", "Write a UTF-8 text file inside the workspace.", {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
            self._tool("edit_file", "Replace exact text once in a file.", {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, ["path", "old_text", "new_text"]),
            self._tool("glob", "Find workspace files using a glob pattern.", {"pattern": {"type": "string"}}, ["pattern"]),
            self._tool("remember", "Persist a stable user preference or durable project fact. Use this whenever the user explicitly asks you to remember something.", {"name": {"type": "string"}, "description": {"type": "string"}, "body": {"type": "string"}, "memory_type": {"type": "string", "enum": ["user", "feedback", "project", "reference"]}}, ["name", "description", "body"]),
            self._tool("todo_write", "Create or update the execution checklist for the current session. Use for multi-step work and keep statuses current.", {"todos": {"type": "array", "items": {"type": "object", "properties": {"content": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}}, "required": ["content", "status"]}}}, ["todos"]),
            self._tool("create_task", "Create a durable task. blockedBy contains task IDs that must complete first.", {"subject": {"type": "string"}, "description": {"type": "string"}, "blockedBy": {"type": "array", "items": {"type": "string"}}}, ["subject"]),
            self._tool("list_tasks", "List durable tasks and their states.", {}, []),
            self._tool("get_task", "Get complete durable task details.", {"task_id": {"type": "string"}}, ["task_id"]),
            self._tool("claim_task", "Claim an unblocked pending task.", {"task_id": {"type": "string"}, "owner": {"type": "string"}}, ["task_id"]),
            self._tool("complete_task", "Complete an in-progress task and report newly unblocked tasks.", {"task_id": {"type": "string"}}, ["task_id"]),
            self._tool("load_skill", "Load the full SKILL.md instructions for a relevant skill from the catalog.", {"name": {"type": "string"}}, ["name"]),
            self._tool("connect_mcp", "Connect to a configured MCP server and discover its external tools.", {"name": {"type": "string"}}, ["name"]),
        ]
        if self.subagents:
            builtins.append(self.subagents.tool_definition())
        if self.team:
            builtins.extend([
                self._tool(
                    "spawn_teammate",
                    "Spawn a named teammate in a background thread. Set autoClaim only for workers that may claim unrelated pending tasks. Teammates cannot spawn teammates.",
                    {
                        "name": {"type": "string"},
                        "role": {"type": "string"},
                        "prompt": {"type": "string"},
                        "autoClaim": {"type": "boolean"},
                    },
                    ["name", "role", "prompt"],
                ),
                self._tool("list_teammates", "List teammate roles, status and unread lead messages.", {}, []),
                self._tool("send_message", "Send a message from lead to a teammate.", {"to": {"type": "string"}, "content": {"type": "string"}}, ["to", "content"]),
                self._tool("check_inbox", "Read and consume messages sent to the lead.", {}, []),
                self._tool("request_shutdown", "Ask a teammate to stop at a safe boundary.", {"teammate": {"type": "string"}}, ["teammate"]),
                self._tool("request_plan", "Request a plan from a teammate for a task.", {"teammate": {"type": "string"}, "task": {"type": "string"}}, ["teammate", "task"]),
                self._tool("review_plan", "Approve or reject a teammate plan request.", {"request_id": {"type": "string"}, "approve": {"type": "boolean"}, "feedback": {"type": "string"}}, ["request_id", "approve"]),
            ])
        if self.worktrees:
            builtins.extend([
                self._tool("create_worktree", "Create an isolated git worktree and optional task binding.", {"name": {"type": "string"}, "task_id": {"type": "string"}}, ["name"]),
                self._tool("list_worktrees", "List ZCLI-managed worktrees.", {}, []),
                self._tool("bind_task_worktree", "Bind an existing task to an existing worktree.", {"task_id": {"type": "string"}, "name": {"type": "string"}}, ["task_id", "name"]),
                self._tool("remove_worktree", "Remove a managed worktree. Refuses changed work unless discard_changes is true.", {"name": {"type": "string"}, "discard_changes": {"type": "boolean"}}, ["name"]),
                self._tool("keep_worktree", "Keep a worktree and record it for manual review.", {"name": {"type": "string"}}, ["name"]),
            ])
        return builtins + self.mcp.definitions()

    @staticmethod
    def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
        return {"name": name, "description": description, "input_schema": {"type": "object", "properties": properties, "required": required}}

    def permission_error(self, name: str, arguments: dict) -> str | None:
        if name == "bash":
            return self.policy.check_command(str(arguments.get("command", "")))
        if name in {"read_file", "write_file", "edit_file"}:
            return self.policy.check_path(str(arguments.get("path", "")))
        if name == "connect_mcp":
            return self.policy.confirm_action(f"connect to MCP server {arguments.get('name', '')!r}")
        if name == "remove_worktree":
            action = f"remove worktree {arguments.get('name', '')!r}"
            if arguments.get("discard_changes"):
                action += " and discard its changes"
            return self.policy.confirm_action(action)
        mcp_tool = self.mcp.tools.get(name)
        if mcp_tool and mcp_tool.destructive:
            return self.policy.confirm_action(f"run destructive MCP tool {name!r}")
        return None

    def execute(
        self,
        name: str,
        arguments: dict,
        *,
        permission_checked: bool = False,
        session: Session | None = None,
    ) -> str:
        if name == "todo_write":
            try:
                return self.todo_write(arguments.get("todos", []), session)
            except Exception as exc:
                return f"Error: {type(exc).__name__}: {exc}"
        handler = self.handlers.get(name)
        if not handler and name not in self.mcp.tools:
            return f"Error: unknown tool {name}"
        try:
            if not permission_checked:
                error = self.permission_error(name, arguments)
                if error:
                    return f"Permission denied: {error}"
            if handler:
                return handler(**arguments)
            return self.mcp.call(name, arguments)
        except Exception as exc:
            return f"Error: {type(exc).__name__}: {exc}"

    def _path(self, path: str) -> Path:
        error = self.policy.check_path(path)
        if error:
            raise ValueError(error)
        return (self.workspace / path).resolve()

    def _run_bash(self, command: str) -> str:
        result = subprocess.run(command, shell=True, cwd=self.workspace, capture_output=True, text=True, timeout=120)
        output = (result.stdout + result.stderr).strip()
        return (output or "(no output)")[:50_000]

    def bash(self, command: str) -> str:
        """Safe direct-call facade; Agent execution uses the PreToolUse hook."""
        return self.execute("bash", {"command": command})

    def read_file(self, path: str) -> str:
        return self._path(path).read_text(encoding="utf-8")[:50_000]

    def write_file(self, path: str, content: str) -> str:
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} characters to {path}"

    def edit_file(self, path: str, old_text: str, new_text: str) -> str:
        target = self._path(path)
        text = target.read_text(encoding="utf-8")
        if old_text not in text:
            return f"Error: text not found in {path}"
        target.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
        return f"Edited {path}"

    def glob(self, pattern: str) -> str:
        paths = []
        for value in globlib.glob(pattern, root_dir=self.workspace, recursive=True):
            if (self.workspace / value).resolve().is_relative_to(self.workspace):
                paths.append(value)
        return "\n".join(paths[:1000]) or "(no matches)"

    def remember(self, name: str, description: str, body: str, memory_type: str = "user") -> str:
        memory = self.memory.remember(name, description, body, memory_type)
        return f"Remembered {memory.name} in {memory.filename}"

    # 
    @staticmethod
    def _normalize_todos(todos) -> list[dict]:
        if isinstance(todos, str):
            try:
                todos = json.loads(todos)
            except json.JSONDecodeError:
                todos = ast.literal_eval(todos)
        if not isinstance(todos, list):
            raise ValueError("todos must be a list")
        normalized = []
        for index, todo in enumerate(todos):
            if not isinstance(todo, dict):
                raise ValueError(f"todos[{index}] must be an object")
            content = str(todo.get("content", "")).strip()
            status = todo.get("status")
            if not content:
                raise ValueError(f"todos[{index}] content cannot be empty")
            if status not in {"pending", "in_progress", "completed"}:
                raise ValueError(f"todos[{index}] has invalid status: {status}")
            normalized.append({"content": content, "status": status})
        return normalized
    # 将待办事项写入会话
    def todo_write(self, todos, session: Session | None) -> str:
        if session is None:
            raise ValueError("todo_write requires an active session")
        session.todos = self._normalize_todos(todos)
        session.rounds_since_todo = 0
        icons = {"pending": " ", "in_progress": ">", "completed": "x"}
        lines = ["Current todos:"] + [
            f"[{icons[todo['status']]}] {todo['content']}" for todo in session.todos
        ]
        return "\n".join(lines)

    def create_task(self, subject: str, description: str = "", blockedBy: list[str] | None = None) -> str:
        task = self.tasks.create(subject, description, blockedBy)
        return f"Created {task.id}: {task.subject}"

    def list_tasks(self) -> str:
        return self.tasks.render()

    def get_task(self, task_id: str) -> str:
        return self.tasks.get_json(task_id)

    def claim_task(self, task_id: str, owner: str = "agent") -> str:
        return self.tasks.claim(task_id, owner)

    def complete_task(self, task_id: str) -> str:
        return self.tasks.complete(task_id)

    def load_skill(self, name: str) -> str:
        return self.skills.load(name)

    def connect_mcp(self, name: str) -> str:
        return self.mcp.connect(name)

    def run_subagent(self, name: str, role: str, prompt: str, task_id: str = "", worktree: str = "") -> str:
        if not self.subagents:
            return "Error: subagents are unavailable"
        return self.subagents.run(name, role, prompt, task_id, worktree)

    def spawn_teammate(self, name: str, role: str, prompt: str, autoClaim: bool = False) -> str:
        return self.team.spawn(name, role, prompt, autoClaim) if self.team else "Error: team is unavailable"

    def list_teammates(self) -> str:
        return self.team.render() if self.team else "Error: team is unavailable"

    def send_message(self, to: str, content: str) -> str:
        return self.team.send_message(to, content) if self.team else "Error: team is unavailable"

    def check_inbox(self) -> str:
        return self.team.check_inbox() if self.team else "Error: team is unavailable"

    def request_shutdown(self, teammate: str) -> str:
        return self.team.request_shutdown(teammate) if self.team else "Error: team is unavailable"

    def request_plan(self, teammate: str, task: str) -> str:
        return self.team.request_plan(teammate, task) if self.team else "Error: team is unavailable"

    def review_plan(self, request_id: str, approve: bool, feedback: str = "") -> str:
        return self.team.review_plan(request_id, approve, feedback) if self.team else "Error: team is unavailable"

    def create_worktree(self, name: str, task_id: str = "") -> str:
        return self.worktrees.create(name, task_id) if self.worktrees else "Error: worktrees are unavailable"

    def list_worktrees(self) -> str:
        return self.worktrees.render() if self.worktrees else "Error: worktrees are unavailable"

    def bind_task_worktree(self, task_id: str, name: str) -> str:
        return self.worktrees.bind(task_id, name) if self.worktrees else "Error: worktrees are unavailable"

    def remove_worktree(self, name: str, discard_changes: bool = False) -> str:
        return self.worktrees.remove(name, discard_changes) if self.worktrees else "Error: worktrees are unavailable"

    def keep_worktree(self, name: str) -> str:
        return self.worktrees.keep(name) if self.worktrees else "Error: worktrees are unavailable"
