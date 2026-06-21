from __future__ import annotations

import re
from pathlib import Path


class PermissionPolicy:
    HARD_DENY = (
        r"rm\s+-rf\s+[/~]",
        r"\bmkfs\b",
        r"\bdd\s+if=",
        r"\bshutdown\b",
        r"\breboot\b",
        r"Remove-Item\s+[^\n]*-Recurse[^\n]*(?:C:\\\\|/)",
    )
    ASK = (r"\brm\s", r"Remove-Item", r"\bsudo\b", r"git\s+push", r"chmod\s+777")

    def __init__(self, workspace: Path, interactive: bool = True):
        self.workspace = workspace.resolve()
        self.interactive = interactive

    def check_path(self, path: str) -> str | None:
        resolved = (self.workspace / path).resolve()
        if not resolved.is_relative_to(self.workspace):
            return f"path escapes workspace: {path}"
        return None

    def check_command(self, command: str) -> str | None:
        if any(re.search(pattern, command, re.IGNORECASE) for pattern in self.HARD_DENY):
            return "command matches the hard deny policy"
        if any(re.search(pattern, command, re.IGNORECASE) for pattern in self.ASK):
            if not self.interactive:
                return "command requires interactive approval"
            answer = input(f"Potentially destructive command:\n  {command}\nAllow? [y/N] ").strip().lower()
            if answer not in {"y", "yes"}:
                return "denied by user"
        return None

    def confirm_action(self, description: str) -> str | None:
        if not self.interactive:
            return "action requires interactive approval"
        answer = input(f"Potentially sensitive action:\n  {description}\nAllow? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            return "denied by user"
        return None
