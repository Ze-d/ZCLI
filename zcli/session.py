from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _interrupted_tool_result(tool_use_id: str) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": "Error: tool execution was interrupted before a result was recorded.",
        "is_error": True,
    }

# 修复工具使用和结果之间的邻接不变式，确保每个工具使用都有一个对应的结果，并且结果紧跟在工具使用之后。如果发现任何不匹配或缺失，将进行修复并统计修复次数。
def repair_tool_protocol(messages: list[dict]) -> tuple[list[dict], int]:
    """Repair persisted Anthropic tool_use/tool_result adjacency invariants."""
    repaired: list[dict] = []
    repair_count = 0
    index = 0
    while index < len(messages):
        message = messages[index]
        content = message.get("content")
        if message.get("role") == "assistant" and isinstance(content, list):
            clean_content = []
            tool_ids: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_id = block.get("id")
                    if not isinstance(tool_id, str) or not tool_id:
                        repair_count += 1
                        continue
                    tool_ids.append(tool_id)
                clean_content.append(block)
            assistant = dict(message)
            assistant["content"] = clean_content
            repaired.append(assistant)
            if not tool_ids:
                index += 1
                continue

            next_message = messages[index + 1] if index + 1 < len(messages) else None
            next_content = next_message.get("content") if isinstance(next_message, dict) else None
            if (
                isinstance(next_message, dict)
                and next_message.get("role") == "user"
                and isinstance(next_content, list)
            ):
                results_by_id: dict[str, dict] = {}
                other_blocks = []
                for block in next_content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        result_id = block.get("tool_use_id")
                        if result_id in tool_ids and result_id not in results_by_id:
                            results_by_id[result_id] = block
                        else:
                            repair_count += 1
                    else:
                        other_blocks.append(block)
                ordered_results = []
                for tool_id in tool_ids:
                    result = results_by_id.get(tool_id)
                    if result is None:
                        result = _interrupted_tool_result(tool_id)
                        repair_count += 1
                    ordered_results.append(result)
                result_message = dict(next_message)
                result_message["content"] = [*ordered_results, *other_blocks]
                repaired.append(result_message)
                index += 2
                continue

            repaired.append({"role": "user", "content": [_interrupted_tool_result(tool_id) for tool_id in tool_ids]})
            repair_count += len(tool_ids)
            index += 1
            continue

        if message.get("role") == "user" and isinstance(content, list):
            clean_content = [
                block for block in content
                if not (isinstance(block, dict) and block.get("type") == "tool_result")
            ]
            repair_count += len(content) - len(clean_content)
            if clean_content:
                clean_message = dict(message)
                clean_message["content"] = clean_content
                repaired.append(clean_message)
        else:
            repaired.append(message)
        index += 1
    return repaired, repair_count


@dataclass
class Session:
    id: str
    created_at: str
    updated_at: str
    messages: list[dict] = field(default_factory=list)
    summary: str = ""
    todos: list[dict] = field(default_factory=list)
    rounds_since_todo: int = 0


class SessionStore:
    def __init__(self, data_dir: Path):
        self.directory = data_dir / "sessions"
        self.directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_id(session_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", session_id):
            raise ValueError("session id may contain only letters, digits, dot, underscore and dash")
        return session_id

    def create(self, session_id: str | None = None) -> Session:
        session_id = self._validate_id(session_id or f"session-{uuid4().hex[:10]}")
        if self.path_for(session_id).exists():
            raise FileExistsError(f"session already exists: {session_id}")
        now = _now()
        session = Session(session_id, now, now)
        self.save(session)
        return session

    def path_for(self, session_id: str) -> Path:
        return self.directory / f"{self._validate_id(session_id)}.json"

    def load(self, session_id: str) -> Session:
        session = Session(**json.loads(self.path_for(session_id).read_text(encoding="utf-8")))
        session.messages, repairs = repair_tool_protocol(session.messages)
        if repairs:
            self.save(session)
        return session

    def load_or_create(self, session_id: str) -> Session:
        path = self.path_for(session_id)
        return self.load(session_id) if path.exists() else self.create(session_id)

    def save(self, session: Session) -> None:
        session.updated_at = _now()
        payload = json.dumps(asdict(session), ensure_ascii=False, indent=2)
        fd, temporary = tempfile.mkstemp(prefix="session-", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(temporary, self.path_for(session.id))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def list(self) -> list[Session]:
        sessions = []
        for path in self.directory.glob("*.json"):
            try:
                sessions.append(Session(**json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, TypeError, json.JSONDecodeError):
                continue
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)
