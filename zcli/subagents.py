from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any, Callable

from .config import Settings
from .memory import MemoryStore
from .tasks import TaskStore
from .tools import ToolRegistry
from .worktrees import WorktreeManager


SUBAGENT_TOOLS = {
    "bash",
    "read_file",
    "write_file",
    "edit_file",
    "glob",
    "list_tasks",
    "get_task",
    "claim_task",
    "complete_task",
}


def validate_agent_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", name or ""):
        raise ValueError("agent name must use letters, digits, underscore or dash (1-32 chars)")
    return name


def _blocks_to_dicts(blocks) -> list[dict]:
    values = []
    for block in blocks:
        if hasattr(block, "model_dump"):
            values.append(block.model_dump(exclude_none=True))
        elif isinstance(block, dict):
            values.append(block)
        else:
            value = {"type": getattr(block, "type", "text")}
            for key in ("text", "id", "name", "input"):
                item = getattr(block, key, None)
                if item is not None:
                    value[key] = item
            values.append(value)
    return values


class SubagentRunner:
    """One-shot isolated agent with a deliberately restricted tool subset."""

    def __init__(
        self,
        settings: Settings,
        client,
        memory: MemoryStore,
        tasks: TaskStore,
        worktrees: WorktreeManager,
        max_rounds: int = 12,
    ):
        self.settings = settings
        self.client = client
        self.memory = memory
        self.tasks = tasks
        self.worktrees = worktrees
        self.max_rounds = max_rounds

    def run(
        self,
        name: str,
        role: str,
        prompt: str,
        task_id: str = "",
        worktree: str = "",
        *,
        stop_event: threading.Event | None = None,
        extra_tools: dict[str, tuple[dict, Callable[..., str]]] | None = None,
    ) -> str:
        name = validate_agent_name(name)
        role = role.strip() or "generalist"
        prompt = prompt.strip()
        if not prompt:
            return "Error: subagent prompt cannot be empty"
        try:
            workspace = self.settings.workspace
            if worktree:
                workspace = self.worktrees.resolve(worktree)
            if task_id:
                task = self.tasks.load(task_id)
                if task.worktree:
                    workspace = self.worktrees.resolve(task.worktree)
                if task.status == "pending":
                    claim = self.tasks.claim(task.id, name)
                    if not claim.startswith("Claimed"):
                        return claim
                elif task.status == "in_progress" and task.owner not in {None, name}:
                    return f"Task {task.id} is owned by {task.owner}"

            tools = ToolRegistry(workspace, self.memory, False, self.tasks)
            definitions = [item for item in tools.definitions if item["name"] in SUBAGENT_TOOLS]
            handlers: dict[str, Callable[..., str]] = {}
            for tool_name, (definition, handler) in (extra_tools or {}).items():
                definitions.append(definition)
                handlers[tool_name] = handler
            system = (
                f"You are subagent '{name}', role: {role}. Work autonomously on the delegated scope. "
                "Use tools for evidence and implementation. You cannot create other subagents or teammates. "
                "Stay inside the assigned workspace. If assigned a durable task, complete it only after the "
                f"work is verified. Workspace: {workspace}"
            )
            task_context = f"\nAssigned task: {self.tasks.get_json(task_id)}" if task_id else ""
            messages = [{"role": "user", "content": prompt + task_context}]
            final_text = ""
            for _ in range(self.max_rounds):
                if stop_event and stop_event.is_set():
                    return "Subagent stopped before completion"
                response = self.client.messages.create(
                    model=self.settings.model,
                    system=system,
                    messages=messages,
                    tools=definitions,
                    max_tokens=self.settings.max_tokens,
                )
                blocks = _blocks_to_dicts(response.content)
                messages.append({"role": "assistant", "content": blocks})
                text = "\n".join(
                    block.get("text", "") for block in blocks if block.get("type") == "text"
                ).strip()
                if text:
                    final_text = text
                calls = [block for block in blocks if block.get("type") == "tool_use"]
                if not calls:
                    return final_text or "Subagent completed without a text response"
                results = []
                for call in calls:
                    if stop_event and stop_event.is_set():
                        output = "Error: subagent was asked to stop"
                    elif call["name"] in handlers:
                        try:
                            output = handlers[call["name"]](**call.get("input", {}))
                        except Exception as exc:
                            output = f"Error: {type(exc).__name__}: {exc}"
                    elif call["name"] in SUBAGENT_TOOLS:
                        if call["name"] == "claim_task":
                            output = self.tasks.claim(call.get("input", {}).get("task_id", ""), name)
                        elif call["name"] == "complete_task":
                            task_id_value = call.get("input", {}).get("task_id", "")
                            task = self.tasks.load(task_id_value)
                            output = (
                                self.tasks.complete(task_id_value)
                                if task.owner == name
                                else f"Error: task {task_id_value} is owned by {task.owner}"
                            )
                        else:
                            output = tools.execute(call["name"], call.get("input", {}))
                    else:
                        output = f"Error: tool not allowed for subagent: {call['name']}"
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": call["id"],
                        "content": str(output)[:50_000],
                    })
                messages.append({"role": "user", "content": results})
            return f"Error: subagent exceeded {self.max_rounds} tool rounds. Last response: {final_text}"
        except Exception as exc:
            return f"Error: subagent {name} failed: {type(exc).__name__}: {exc}"

    def tool_definition(self) -> dict[str, Any]:
        return {
            "name": "run_subagent",
            "description": "Run a one-shot isolated subagent synchronously and return its final result.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "prompt": {"type": "string"},
                    "task_id": {"type": "string"},
                    "worktree": {"type": "string"},
                },
                "required": ["name", "role", "prompt"],
            },
        }
