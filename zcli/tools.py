from __future__ import annotations

import glob as globlib
import subprocess
from pathlib import Path
from typing import Callable

from .memory import MemoryStore
from .permissions import PermissionPolicy


class ToolRegistry:
    def __init__(self, workspace: Path, memory: MemoryStore, interactive: bool = True):
        self.workspace = workspace.resolve()
        self.memory = memory
        self.policy = PermissionPolicy(self.workspace, interactive)
        self.handlers: dict[str, Callable[..., str]] = {
            "bash": self.bash,
            "read_file": self.read_file,
            "write_file": self.write_file,
            "edit_file": self.edit_file,
            "glob": self.glob,
            "remember": self.remember,
        }

    @property
    def definitions(self) -> list[dict]:
        return [
            self._tool("bash", "Run a shell command in the workspace.", {"command": {"type": "string"}}, ["command"]),
            self._tool("read_file", "Read a UTF-8 text file.", {"path": {"type": "string"}}, ["path"]),
            self._tool("write_file", "Write a UTF-8 text file inside the workspace.", {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
            self._tool("edit_file", "Replace exact text once in a file.", {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, ["path", "old_text", "new_text"]),
            self._tool("glob", "Find workspace files using a glob pattern.", {"pattern": {"type": "string"}}, ["pattern"]),
            self._tool("remember", "Persist a stable user preference or durable project fact. Use this whenever the user explicitly asks you to remember something.", {"name": {"type": "string"}, "description": {"type": "string"}, "body": {"type": "string"}, "memory_type": {"type": "string", "enum": ["user", "feedback", "project", "reference"]}}, ["name", "description", "body"]),
        ]

    @staticmethod
    def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
        return {"name": name, "description": description, "input_schema": {"type": "object", "properties": properties, "required": required}}

    def execute(self, name: str, arguments: dict) -> str:
        handler = self.handlers.get(name)
        if not handler:
            return f"Error: unknown tool {name}"
        try:
            return handler(**arguments)
        except Exception as exc:
            return f"Error: {type(exc).__name__}: {exc}"

    def _path(self, path: str) -> Path:
        error = self.policy.check_path(path)
        if error:
            raise ValueError(error)
        return (self.workspace / path).resolve()

    def bash(self, command: str) -> str:
        error = self.policy.check_command(command)
        if error:
            return f"Permission denied: {error}"
        result = subprocess.run(command, shell=True, cwd=self.workspace, capture_output=True, text=True, timeout=120)
        output = (result.stdout + result.stderr).strip()
        return (output or "(no output)")[:50_000]

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

