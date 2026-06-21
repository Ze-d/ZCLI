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
        return Session(**json.loads(self.path_for(session_id).read_text(encoding="utf-8")))

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
