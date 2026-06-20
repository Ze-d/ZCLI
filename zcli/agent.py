from __future__ import annotations

import json
from typing import Callable

from anthropic import Anthropic

from .config import Settings
from .memory import MemoryStore
from .session import Session, SessionStore
from .tools import ToolRegistry


def _blocks_to_dicts(blocks) -> list[dict]:
    result = []
    for block in blocks:
        if hasattr(block, "model_dump"):
            result.append(block.model_dump(exclude_none=True))
        elif isinstance(block, dict):
            result.append(block)
        else:
            data = {"type": getattr(block, "type", "text")}
            for key in ("text", "id", "name", "input"):
                value = getattr(block, key, None)
                if value is not None:
                    data[key] = value
            result.append(data)
    return result


class Agent:
    def __init__(self, settings: Settings, client=None, interactive: bool = True):
        self.settings = settings
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.client = client or Anthropic(base_url=settings.base_url)
        self.memory = MemoryStore(settings.data_dir)
        self.sessions = SessionStore(settings.data_dir)
        self.tools = ToolRegistry(settings.workspace, self.memory, interactive)

    def system_prompt(self, query: str) -> str:
        index = self.memory.index()
        relevant = self.memory.render_relevant(query)
        memory_section = "\n\nLong-term memory catalog:\n" + index if index else ""
        return (
            "You are ZCLI, a personal coding agent. Respond in the user's preferred language. "
            "Use tools to inspect and modify the workspace when needed. Never claim a tool action succeeded "
            "without its result. When the user explicitly asks you to remember a stable preference or fact, "
            "call the remember tool. Keep answers concise.\n\n"
            f"Workspace: {self.settings.workspace}"
            f"{memory_section}\n\n{relevant}"
        ).strip()

    def run_turn(self, session: Session, query: str, emit: Callable[[str], None] = print) -> str:
        turn_start = len(session.messages)
        memory_context = self.memory.render_relevant(query)
        user_content = f"{memory_context}\n\n{query}" if memory_context else query
        session.messages.append({"role": "user", "content": user_content})
        self.sessions.save(session)

        while True:
            self._compact_if_needed(session)
            response = self.client.messages.create(
                model=self.settings.model,
                system=self.system_prompt(query),
                messages=session.messages,
                tools=self.tools.definitions,
                max_tokens=self.settings.max_tokens,
            )
            blocks = _blocks_to_dicts(response.content)
            session.messages.append({"role": "assistant", "content": blocks})
            self.sessions.save(session)
            self._compact_if_needed(session)  # 检查当前轮是否触发压缩

            text = "\n".join(block.get("text", "") for block in blocks if block.get("type") == "text").strip()
            if text:
                emit(text)

            calls = [block for block in blocks if block.get("type") == "tool_use"]
            if not calls:
                self._extract_memories(session.messages[turn_start:])
                return text

            results = []
            for call in calls:
                output = self.tools.execute(call["name"], call.get("input", {}))
                emit(f"[{call['name']}] {output[:300]}")
                results.append({"type": "tool_result", "tool_use_id": call["id"], "content": output})
            session.messages.append({"role": "user", "content": results})
            self.sessions.save(session)

    def _estimate_size(self, messages: list[dict]) -> int:
        return len(json.dumps(messages, ensure_ascii=False)) // 4

    def _compact_if_needed(self, session: Session) -> None:
        if self._estimate_size(session.messages) <= self.settings.context_limit or len(session.messages) < 8:
            return
        # Start the retained tail at an assistant response. Its preceding user
        # request is represented by the summary, and any following tool_result
        # remains paired with the retained tool_use block.
        preferred = max(2, len(session.messages) - 6)
        split = next(
            (index for index in range(preferred, 0, -1)
             if session.messages[index].get("role") == "assistant"),
            0,
        )
        if not split:
            return
        old, recent = session.messages[:split], session.messages[split:]
        response = self.client.messages.create(
            model=self.settings.model,
            messages=[{"role": "user", "content": "Summarize this conversation for continuation. Preserve user preferences, decisions, files changed, pending work, and errors.\n\n" + json.dumps(old, ensure_ascii=False)[:120_000]}],
            max_tokens=1500,
        )
        summary = "\n".join(block.get("text", "") for block in _blocks_to_dicts(response.content) if block.get("type") == "text")
        session.summary = summary
        session.messages = [{"role": "user", "content": f"<session_summary>\n{summary}\n</session_summary>"}] + recent
        self.sessions.save(session)

    def _extract_memories(self, turn_messages: list[dict]) -> None:
        dialogue = json.dumps(turn_messages, ensure_ascii=False)[:12_000]
        prompt = (
            "Extract only durable user preferences, repeated feedback, or stable project facts from the dialogue. "
            "Do not save transient requests, greetings, or task progress. Return only a JSON array. Each item must "
            "contain name, type (user|feedback|project|reference), description, and body. Return [] if none.\n\n"
            f"Existing memory catalog:\n{self.memory.index()}\n\nDialogue:\n{dialogue}"
        )
        try:
            response = self.client.messages.create(
                model=self.settings.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
            )
            text = "\n".join(block.get("text", "") for block in _blocks_to_dicts(response.content) if block.get("type") == "text")
            self.memory.save_extracted(text)
        except Exception:
            # Memory extraction must never make a successful user turn fail.
            return
