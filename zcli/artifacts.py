from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


_SESSION_ID = re.compile(r"[A-Za-z0-9._-]{1,80}")
_ARTIFACT_ID = re.compile(r"artifact_[a-f0-9]{20}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ArtifactMetadata:
    artifact_id: str
    session_id: str
    tool_use_id: str
    source_tool: str
    chars: int
    lines: int
    created_at: str
    content_hash: str
    encoding: str = "utf-8"


class ArtifactStore:
    """Session-scoped storage and bounded retrieval for large text tool results."""

    def __init__(
        self,
        data_dir: Path,
        persist_threshold: int = 30_000,
        preview_head_chars: int = 1_200,
        preview_tail_chars: int = 800,
        max_return_chars: int = 20_000,
    ):
        self.directory = data_dir / "artifacts"
        self.persist_threshold = persist_threshold
        self.preview_head_chars = preview_head_chars
        self.preview_tail_chars = preview_tail_chars
        self.max_return_chars = max_return_chars

    @staticmethod
    def _validate_session_id(session_id: str) -> str:
        if not _SESSION_ID.fullmatch(session_id):
            raise ValueError("invalid session id")
        return session_id

    @staticmethod
    def _validate_artifact_id(artifact_id: str) -> str:
        if not _ARTIFACT_ID.fullmatch(artifact_id):
            raise ValueError("invalid artifact id")
        return artifact_id

    def _artifact_dir(self, session_id: str, artifact_id: str) -> Path:
        session_id = self._validate_session_id(session_id)
        artifact_id = self._validate_artifact_id(artifact_id)
        return self.directory / session_id / artifact_id

    def _metadata_path(self, session_id: str, artifact_id: str) -> Path:
        return self._artifact_dir(session_id, artifact_id) / "metadata.json"

    def _content_path(self, session_id: str, artifact_id: str) -> Path:
        return self._artifact_dir(session_id, artifact_id) / "content.txt"

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f"{path.name}-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def persist(
        self,
        session_id: str,
        tool_use_id: str,
        source_tool: str,
        output: str,
    ) -> tuple[ArtifactMetadata, str]:
        session_id = self._validate_session_id(session_id)
        artifact_id = f"artifact_{uuid4().hex[:20]}"
        target = self._artifact_dir(session_id, artifact_id)
        metadata = ArtifactMetadata(
            artifact_id=artifact_id,
            session_id=session_id,
            tool_use_id=str(tool_use_id),
            source_tool=str(source_tool),
            chars=len(output),
            lines=output.count("\n") + (1 if output else 0),
            created_at=_now(),
            content_hash=hashlib.sha256(output.encode("utf-8")).hexdigest(),
        )
        self._atomic_write(target / "content.txt", output)
        self._atomic_write(
            target / "metadata.json",
            json.dumps(asdict(metadata), ensure_ascii=False, indent=2),
        )
        return metadata, self.reference(metadata, output)

    def persist_if_large(
        self,
        session_id: str,
        tool_use_id: str,
        source_tool: str,
        output: str,
    ) -> str:
        if len(output) <= self.persist_threshold or output.startswith("<artifact-result>"):
            return output
        _, reference = self.persist(session_id, tool_use_id, source_tool, output)
        return reference

    #返回一个带有预览的引用字符串，包含artifact_id、source_tool、大小和预览内容。 
    def reference(self, metadata: ArtifactMetadata, output: str) -> str:
        head = output[:self.preview_head_chars]
        tail = output[-self.preview_tail_chars:] if len(output) > self.preview_head_chars else ""
        tail_section = f"\nTail preview:\n{tail}\n" if tail else ""
        return (
            "<artifact-result>\n"
            f"Artifact ID: {metadata.artifact_id}\n"
            f"Source tool: {metadata.source_tool}\n"
            f"Size: {metadata.chars} chars, {metadata.lines} lines\n"
            f"Head preview:\n{head}\n"
            f"{tail_section}"
            "Use inspect_artifact, search_artifact, or read_artifact_chunk to retrieve more.\n"
            "</artifact-result>"
        )

    def _load_metadata(self, session_id: str, artifact_id: str) -> ArtifactMetadata:
        path = self._metadata_path(session_id, artifact_id)
        if not path.exists():
            raise FileNotFoundError("artifact not found in current session")
        metadata = ArtifactMetadata(**json.loads(path.read_text(encoding="utf-8")))
        if metadata.session_id != session_id or metadata.artifact_id != artifact_id:
            raise ValueError("artifact metadata does not match current session")
        return metadata

    def inspect(self, session_id: str, artifact_id: str) -> str:
        metadata = self._load_metadata(session_id, artifact_id)
        path = self._content_path(session_id, artifact_id)
        with path.open("r", encoding="utf-8") as handle:
            head = handle.read(self.preview_head_chars)
        tail = ""
        if metadata.chars > self.preview_head_chars:
            with path.open("r", encoding="utf-8") as handle:
                remaining = metadata.chars - self.preview_tail_chars
                while remaining > 0:
                    consumed = handle.read(min(remaining, 64 * 1024))
                    if not consumed:
                        break
                    remaining -= len(consumed)
                tail = handle.read(self.preview_tail_chars)
        return json.dumps(
            {
                "artifact_id": metadata.artifact_id,
                "source_tool": metadata.source_tool,
                "tool_use_id": metadata.tool_use_id,
                "chars": metadata.chars,
                "lines": metadata.lines,
                "created_at": metadata.created_at,
                "content_hash": metadata.content_hash,
                "head_preview": head,
                "tail_preview": tail,
            },
            ensure_ascii=False,
            indent=2,
        )

    def read_chunk(
        self,
        session_id: str,
        artifact_id: str,
        offset: int = 0,
        limit: int = 8_000,
    ) -> str:
        metadata = self._load_metadata(session_id, artifact_id)
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if limit <= 0:
            raise ValueError("limit must be positive")
        limit = min(limit, self.max_return_chars)

        path = self._content_path(session_id, artifact_id)
        start_line = 1
        skipped = 0
        with path.open("r", encoding="utf-8") as handle:
            while skipped < offset:
                part = handle.read(min(offset - skipped, 64 * 1024))
                if not part:
                    break
                skipped += len(part)
                start_line += part.count("\n")
            content = handle.read(limit)

        end = skipped + len(content)
        end_line = start_line + content.count("\n")
        has_more = end < metadata.chars
        header = {
            "artifact_id": artifact_id,
            "offset": skipped,
            "end_offset": end,
            "start_line": start_line,
            "end_line": end_line,
            "has_more": has_more,
            "next_offset": end if has_more else None,
        }
        return f"{json.dumps(header, ensure_ascii=False)}\n\n{content}"

    def search(
        self,
        session_id: str,
        artifact_id: str,
        query: str,
        regex: bool = False,
        context_lines: int = 5,
        max_matches: int = 20,
    ) -> str:
        self._load_metadata(session_id, artifact_id)
        if not query:
            raise ValueError("query must not be empty")
        context_lines = max(0, min(context_lines, 50))
        max_matches = max(1, min(max_matches, 100))
        pattern = re.compile(query) if regex else None
        before: deque[tuple[int, int, str]] = deque(maxlen=context_lines)
        pending: list[dict] = []
        matches: list[dict] = []
        char_offset = 0

        with self._content_path(session_id, artifact_id).open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                for item in pending:
                    if item["remaining"] > 0:
                        item["lines"].append((line_number, char_offset, line))
                        item["remaining"] -= 1
                pending = [item for item in pending if item["remaining"] > 0]

                found = bool(pattern.search(line)) if pattern else query in line
                if found and len(matches) < max_matches:
                    item = {
                        "match_line": line_number,
                        "match_offset": char_offset,
                        "lines": [*before, (line_number, char_offset, line)],
                        "remaining": context_lines,
                    }
                    matches.append(item)
                    if context_lines:
                        pending.append(item)

                before.append((line_number, char_offset, line))
                char_offset += len(line)
                if len(matches) >= max_matches and not pending:
                    break

        rendered = []
        used = 0
        for item in matches:
            snippet = "".join(
                f"{line_number}:{offset}: {line}"
                for line_number, offset, line in item["lines"]
            )
            entry = (
                f"Match at line {item['match_line']}, char {item['match_offset']}:\n"
                f"{snippet}"
            )
            remaining = self.max_return_chars - used
            if remaining <= 0:
                break
            rendered.append(entry[:remaining])
            used += len(rendered[-1])

        if not rendered:
            return f"No matches for {query!r} in artifact {artifact_id}."
        return "\n---\n".join(rendered)
