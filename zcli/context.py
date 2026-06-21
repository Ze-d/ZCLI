from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Callable

# 估算token，直接拿json的大小来估计
def estimate_tokens(messages: list[dict]) -> int:
    """Cheap token estimate, matching the teaching project's 4 chars/token rule."""
    size = len(json.dumps(messages, ensure_ascii=False, default=str))
    return max(1, size // 4)


def _block_type(block) -> str | None:
    return block.get("type") if isinstance(block, dict) else getattr(block, "type", None)


def message_has_tool_use(message: dict) -> bool:
    content = message.get("content")
    return (
        message.get("role") == "assistant"
        and isinstance(content, list)
        and any(_block_type(block) == "tool_use" for block in content)
    )


def is_tool_result_message(message: dict) -> bool:
    content = message.get("content")
    return (
        message.get("role") == "user"
        and isinstance(content, list)
        and any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content)
    )


def collect_tool_results(messages: list[dict]) -> list[tuple[int, int, dict]]:
    found = []
    for message_index, message in enumerate(messages):
        content = message.get("content")
        if message.get("role") != "user" or not isinstance(content, list):
            continue
        for block_index, block in enumerate(content):
            if isinstance(block, dict) and block.get("type") == "tool_result":
                found.append((message_index, block_index, block))
    return found


class ContextManager:
    """Layered context compaction based on learn-claude-code s08/s20."""

    def __init__(
        self,
        data_dir: Path,
        context_limit: int,
        max_messages: int = 50,
        keep_recent_tool_results: int = 3,
        persist_threshold: int = 30_000,
        tool_result_budget_bytes: int = 200_000,
    ):
        self.context_limit = context_limit
        self.max_messages = max_messages
        self.keep_recent_tool_results = keep_recent_tool_results
        self.persist_threshold = persist_threshold
        self.tool_result_budget_bytes = tool_result_budget_bytes
        self.transcript_dir = data_dir / "transcripts"
        self.tool_results_dir = data_dir / "tool-results"

    def persist_large_output(self, tool_use_id: str, output: str) -> str:
        if len(output) <= self.persist_threshold:
            return output
        self.tool_results_dir.mkdir(parents=True, exist_ok=True)
        path = self.tool_results_dir / f"{tool_use_id}.txt"
        # 如果已经存在同名文件，说明之前已经持久化过了，直接复用路径而不覆盖写入，以免并发时覆盖了另一个工具调用的结果
        if not path.exists():
            path.write_text(output, encoding="utf-8")
        return (
            "<persisted-output>\n"
            f"Full output: {path}\n"
            f"Preview:\n{output[:2000]}\n"
            "</persisted-output>"
        )
    # 工具结果预算：如果用户消息中包含工具结果块且总大小超过预算，就从最大的开始压缩，直到总大小在预算内。压缩方式是持久化输出并替换为占位文本，实际内容可以通过提供的路径访问。
    def tool_result_budget(self, messages: list[dict]) -> list[dict]:
        if not messages:
            return messages
        content = messages[-1].get("content")
        # 只有最后一条消息是用户消息且内容是列表时才处理，否则不确定结构可能导致误删或错误访问
        if messages[-1].get("role") != "user" or not isinstance(content, list):
            return messages
        # 先收集所有工具结果，计算总大小，如果超过预算就从最大的开始压缩，直到总大小在预算内
        blocks = [
            block for block in content
            if isinstance(block, dict) and block.get("type") == "tool_result"
        ]
        # 如果没有工具结果或者总大小已经在预算内，则不修改消息
        total = sum(len(str(block.get("content", ""))) for block in blocks)
        for block in sorted(blocks, key=lambda item: len(str(item.get("content", ""))), reverse=True):
            if total <= self.tool_result_budget_bytes:
                break
            original = str(block.get("content", ""))
            # 持久化输出并替换为占位文本，实际内容可以通过提供的路径访问
            replacement = self.persist_large_output(block.get("tool_use_id", "unknown"), original)
            block["content"] = replacement
            total -= len(original) - len(replacement)
        return messages
    # 消息数量预算：如果消息总数超过 max_messages，则保留开头的 3 条和结尾的若干条（总共 max_messages 条），中间的消息替换为一条占位消息，提示被省略的消息数量。为了避免在工具调用和结果之间插入占位消息导致上下文不连贯，如果第 3 条消息是工具调用，则把开头的保留范围延长到包含所有连续的工具调用和结果；如果倒数第 (max_messages-3) 条消息是工具结果且前一条是对应的工具调用，则把结尾的保留范围提前到包含这个工具调用。
    # 用户最初目标
    # 早期关键响应
    # [snipped 34 messages]
    # 最近几轮对话
    def snip_compact(self, messages: list[dict]) -> list[dict]:
        if len(messages) <= self.max_messages:
            return messages
        head_end = 3
        tail_start = len(messages) - (self.max_messages - 3)
        # 如果第 3 条消息是工具调用，则把开头的保留范围延长到包含所有连续的工具调用和结果
        if head_end and message_has_tool_use(messages[head_end - 1]):
            while head_end < len(messages) and is_tool_result_message(messages[head_end]):
                head_end += 1
        if (
            0 < tail_start < len(messages)
            and is_tool_result_message(messages[tail_start])
            and message_has_tool_use(messages[tail_start - 1])
        ):
            tail_start -= 1
        if head_end >= tail_start:
            return messages
        count = tail_start - head_end
        return messages[:head_end] + [{"role": "user", "content": f"[snipped {count} messages]"}] + messages[tail_start:]
    # micro_compact() 默认保留最近 3 个完整工具结果，将更早且超过 120 字符的结果替换为：
    def micro_compact(self, messages: list[dict]) -> list[dict]:
        results = collect_tool_results(messages)
        keep = self.keep_recent_tool_results
        if len(results) <= keep:
            return messages
        old_results = results[:-keep] if keep else results
        for _, _, block in old_results:
            if len(str(block.get("content", ""))) > 120:
                block["content"] = "[Earlier tool result compacted. Re-run if needed.]"
        return messages
    # 当消息总数超过 context_limit 时，compact_history() 会被调用进行全面压缩。它会将整个消息列表写入转录文件，并调用提供的 summarize 函数生成摘要。然后，它会返回一个新的消息列表，只包含一条用户消息，内容为 "[Compacted]" 和生成的摘要，以及这个摘要文本。这个方法适用于在对话达到上下文限制时进行一次性压缩，保留最重要的信息并提示用户之前的内容已经被压缩了。
    def write_transcript(self, messages: list[dict], label: str = "transcript") -> Path:
        self.transcript_dir.mkdir(parents=True, exist_ok=True)
        target = self.transcript_dir / f"{label}_{time.time_ns()}.jsonl"
        fd, temporary = tempfile.mkstemp(prefix="transcript-", suffix=".tmp", dir=self.transcript_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                for message in messages:
                    handle.write(json.dumps(message, ensure_ascii=False, default=str) + "\n")
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return target
    # 全面压缩：当消息总数超过 context_limit 时，compact_history() 会被调用进行全面压缩。它会将整个消息列表写入转录文件，并调用提供的 summarize 函数生成摘要。然后，它会返回一个新的消息列表，只包含一条用户消息，内容为 "[Compacted]" 和生成的摘要，以及这个摘要文本。这个方法适用于在对话达到上下文限制时进行一次性压缩，保留最重要的信息并提示用户之前的内容已经被压缩了。
    def compact_history(self, messages: list[dict], summarize: Callable[[list[dict]], str]) -> tuple[list[dict], str]:
        self.write_transcript(messages, "compact")
        summary = summarize(messages) or "(empty summary)"
        return [{"role": "user", "content": f"[Compacted]\n\n{summary}"}], summary
    # reactive_compact: 当对话被截断或超出限制时，使用此方法进行反应式压缩。它会将整个消息列表写入转录文件，并尝试调用提供的 summarize 函数生成摘要。如果 summarize 抛出异常或返回空字符串，则使用默认的占位摘要。然后，它会保留最后 5 条消息（或更多，如果最后一条消息是工具结果且前一条是对应的工具调用），并在开头插入一条用户消息，内容为 "[Reactive compact]" 和生成的摘要。返回值是压缩后的消息列表和摘要。 
    def reactive_compact(self, messages: list[dict], summarize: Callable[[list[dict]], str] | None = None) -> tuple[list[dict], str]:
        self.write_transcript(messages, "reactive")
        try:
            summary = summarize(messages) if summarize else ""
        except Exception:
            summary = ""
        summary = summary or "Earlier conversation was trimmed after a prompt-too-long error."
        tail_start = max(0, len(messages) - 5)
        if (
            0 < tail_start < len(messages)
            and is_tool_result_message(messages[tail_start])
            and message_has_tool_use(messages[tail_start - 1])
        ):
            tail_start -= 1
        compacted = [{"role": "user", "content": f"[Reactive compact]\n\n{summary}"}, *messages[tail_start:]]
        return compacted, summary

    def prepare(self, messages: list[dict], summarize: Callable[[list[dict]], str]) -> tuple[list[dict], str | None]:
        messages = self.tool_result_budget(messages)
        messages = self.snip_compact(messages)
        messages = self.micro_compact(messages)
        if estimate_tokens(messages) > self.context_limit:
            return self.compact_history(messages, summarize)
        return messages, None

