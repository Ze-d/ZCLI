from __future__ import annotations

import json
from typing import Callable

from anthropic import Anthropic

from .config import Settings
from .context import ContextManager
from .hooks import (
    POST_TOOL_USE,
    PRE_TOOL_USE,
    STOP,
    USER_PROMPT_SUBMIT,
    HookContext,
    HookManager,
    large_output_hook,
    permission_hook,
)
from .memory import MemoryStore
from .mcp import MCPManager
from .recovery import RecoveryState, is_prompt_too_long_error, with_retry
from .session import Session, SessionStore
from .skills import SkillRegistry
from .tasks import TaskStore
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
    def __init__(
        self,
        settings: Settings,
        client=None,
        interactive: bool = True,
        hooks: HookManager | None = None,
    ):
        self.settings = settings
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.client = client or Anthropic(base_url=settings.base_url)
        self.memory = MemoryStore(settings.data_dir)
        self.sessions = SessionStore(settings.data_dir)
        self.tasks = TaskStore(settings.data_dir)
        self.skills = SkillRegistry(settings.workspace / "skills")
        self.mcp = MCPManager(settings.workspace)
        self.tools = ToolRegistry(
            settings.workspace,
            self.memory,
            interactive,
            self.tasks,
            self.skills,
            self.mcp,
        )
        self.context = ContextManager(settings.data_dir, settings.context_limit)
        self.hooks = hooks or HookManager()
        # Permission is registered first so an extension cannot bypass it by
        # returning an "allow" result, matching Claude Code's safety invariant.
        self.hooks.register(PRE_TOOL_USE, permission_hook, prepend=True)
        self.hooks.register(POST_TOOL_USE, large_output_hook)

    def system_prompt(self, query: str, session: Session | None = None) -> str:
        index = self.memory.index()
        relevant = self.memory.render_relevant(query)
        memory_section = "\n\nLong-term memory catalog:\n" + index if index else ""
        todo_section = ""
        if session and session.todos:
            todo_section = "\n\nCurrent session todos:\n" + "\n".join(
                f"- [{todo['status']}] {todo['content']}" for todo in session.todos
            )
        task_summary = self.tasks.render()
        task_section = "" if task_summary == "No tasks." else f"\n\nDurable task graph:\n{task_summary[:4000]}"
        skill_catalog = self.skills.catalog()
        skill_section = (
            "\n\nSkills catalog:\n"
            f"{skill_catalog}\n"
            "When a skill is relevant, call load_skill(name) before following its instructions."
        )
        mcp_section = "\n\n" + self.mcp.status()
        return (
            "You are ZCLI, a personal coding agent. Respond in the user's preferred language. "
            "Use tools to inspect and modify the workspace when needed. Never claim a tool action succeeded "
            "without its result. When the user explicitly asks you to remember a stable preference or fact, "
            "call the remember tool. For multi-step work, use todo_write and keep statuses current. Use the "
            "durable task graph for work that must survive sessions or has dependencies. Keep answers concise.\n\n"
            f"Workspace: {self.settings.workspace}"
            f"{memory_section}{todo_section}{task_section}{skill_section}{mcp_section}\n\n{relevant}"
        ).strip()

    def close(self) -> None:
        self.mcp.close()

    def run_turn(self, session: Session, query: str, emit: Callable[[str], None] = print) -> str:
        submit = self.hooks.trigger(
            USER_PROMPT_SUBMIT,
            HookContext(
                event=USER_PROMPT_SUBMIT,
                agent=self,
                session=session,
                query=query,
                emit=emit,
            ),
        )
        if submit.blocked:
            message = submit.reason or "User prompt blocked by hook"
            emit(f"[HOOK] UserPromptSubmit blocked: {message}")
            return message

        memory_context = self.memory.render_relevant(query)
        user_parts = [part for part in (memory_context, submit.additional_context, query) if part]
        user_content = "\n\n".join(user_parts)
        user_message = {"role": "user", "content": user_content}
        turn_messages = [user_message]
        session.messages.append(user_message)
        self.sessions.save(session)

        state = RecoveryState(self.settings.model)
        max_tokens = self.settings.max_tokens
        emitted_text: list[str] = []
        stop_hook_active = False
        while True:
            if session.rounds_since_todo >= 3:
                reminder = {"role": "user", "content": "<reminder>Update your todos.</reminder>"}
                session.messages.append(reminder)
                turn_messages.append(reminder)
                session.rounds_since_todo = 0
                self.sessions.save(session)
            try:
                prepared, summary = self.context.prepare(
                    session.messages,
                    lambda messages: self._summarize(messages, state, emit),
                )
                if prepared is not session.messages or summary is not None:
                    session.messages = prepared
                    if summary:
                        session.summary = summary
                    self.sessions.save(session)

                response = with_retry(
                    lambda: self.client.messages.create(
                        model=state.current_model,
                        system=self.system_prompt(query, session),
                        messages=session.messages,
                        tools=self.tools.definitions,
                        max_tokens=max_tokens,
                    ),
                    state,
                    max_retries=self.settings.max_retries,
                    fallback_model=self.settings.fallback_model,
                    emit=emit,
                )
            except Exception as error:
                if is_prompt_too_long_error(error) and not state.has_attempted_reactive_compact:
                    session.messages, session.summary = self.context.reactive_compact(
                        session.messages,
                        lambda messages: self._summarize(messages, state, emit),
                    )
                    state.has_attempted_reactive_compact = True
                    self.sessions.save(session)
                    emit("[context] prompt too long; compacted and retrying")
                    continue
                raise

            blocks = _blocks_to_dicts(response.content)
            text = "\n".join(block.get("text", "") for block in blocks if block.get("type") == "text").strip()

            if getattr(response, "stop_reason", None) == "max_tokens":
                if not state.has_escalated:
                    state.has_escalated = True
                    max_tokens = self.settings.escalated_max_tokens
                    emit(f"[max_tokens] escalating {self.settings.max_tokens} -> {max_tokens}")
                    continue
                assistant_message = {"role": "assistant", "content": blocks}
                session.messages.append(assistant_message)
                turn_messages.append(assistant_message)
                self.sessions.save(session)
                if text:
                    emitted_text.append(text)
                    emit(text)
                if state.recovery_count < self.settings.max_recovery_retries:
                    continuation = {
                        "role": "user",
                        "content": "Continue from the previous response. Do not repeat completed work.",
                    }
                    session.messages.append(continuation)
                    turn_messages.append(continuation)
                    state.recovery_count += 1
                    self.sessions.save(session)
                    emit(f"[max_tokens] continuation {state.recovery_count}/{self.settings.max_recovery_retries}")
                    continue
                return "\n".join(emitted_text)

            max_tokens = self.settings.max_tokens
            state.has_escalated = False
            assistant_message = {"role": "assistant", "content": blocks}
            session.messages.append(assistant_message)
            turn_messages.append(assistant_message)
            self.sessions.save(session)
            if text:
                emitted_text.append(text)
                emit(text)

            calls = [block for block in blocks if block.get("type") == "tool_use"]
            if not calls:
                if not stop_hook_active:
                    stop = self.hooks.trigger(
                        STOP,
                        HookContext(
                            event=STOP,
                            agent=self,
                            session=session,
                            query=query,
                            response_text=text,
                            emit=emit,
                        ),
                    )
                    if stop.continuation:
                        continuation = {"role": "user", "content": stop.continuation}
                        session.messages.append(continuation)
                        turn_messages.append(continuation)
                        stop_hook_active = True
                        self.sessions.save(session)
                        continue
                self._extract_memories(turn_messages)
                return "\n".join(emitted_text)

            results = []
            for call in calls:
                tool_input = call.get("input", {})
                pre = self.hooks.trigger(
                    PRE_TOOL_USE,
                    HookContext(
                        event=PRE_TOOL_USE,
                        agent=self,
                        session=session,
                        query=query,
                        tool_name=call["name"],
                        tool_input=tool_input,
                        emit=emit,
                    ),
                )
                if pre.blocked:
                    output = pre.reason or "Blocked by PreToolUse hook"
                else:
                    output = self.tools.execute(
                        call["name"],
                        tool_input,
                        permission_checked=True,
                        session=session,
                    )
                    post = self.hooks.trigger(
                        POST_TOOL_USE,
                        HookContext(
                            event=POST_TOOL_USE,
                            agent=self,
                            session=session,
                            query=query,
                            tool_name=call["name"],
                            tool_input=tool_input,
                            output=output,
                            emit=emit,
                        ),
                    )
                    if post.updated_output is not None:
                        output = post.updated_output
                    if call["name"] != "todo_write":
                        session.rounds_since_todo += 1
                emit(f"[{call['name']}] {output[:300]}")
                compact_output = self.context.persist_large_output(call["id"], output)
                results.append({"type": "tool_result", "tool_use_id": call["id"], "content": compact_output})
            result_message = {"role": "user", "content": results}
            session.messages.append(result_message)
            turn_messages.append(result_message)
            self.sessions.save(session)

    def _compact_if_needed(self, session: Session) -> None:
        """Compatibility entry point used by tests and callers from ZCLI 0.1."""
        if len(session.messages) < 8:
            return
        prepared, summary = self.context.prepare(
            session.messages,
            lambda messages: self._summarize(messages, RecoveryState(self.settings.model), lambda _: None),
        )
        if prepared is not session.messages or summary:
            session.messages = prepared
            if summary:
                session.summary = summary
            self.sessions.save(session)

    def _summarize(self, messages: list[dict], state: RecoveryState, emit: Callable[[str], None]) -> str:
        conversation = json.dumps(messages, ensure_ascii=False, default=str)[:120_000]
        prompt = (
            "Summarize this coding-agent conversation so work can continue. Preserve the current goal, "
            "user preferences and constraints, key findings, changed files, errors, and remaining work.\n\n"
            + conversation
        )
        response = with_retry(
            lambda: self.client.messages.create(
                model=state.current_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2_000,
            ),
            state,
            max_retries=self.settings.max_retries,
            fallback_model=self.settings.fallback_model,
            emit=emit,
        )
        return "\n".join(
            block.get("text", "")
            for block in _blocks_to_dicts(response.content)
            if block.get("type") == "text"
        ).strip()

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
