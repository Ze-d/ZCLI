from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Memory:
    name: str
    description: str
    type: str
    body: str
    filename: str


class MemoryStore:
    TYPES = {"user", "feedback", "project", "reference"}

    def __init__(self, data_dir: Path):
        self.directory = data_dir / "memory"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.index_path = self.directory / "MEMORY.md"

    @staticmethod
    def _slug(name: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff._-]+", "-", name.strip().lower()).strip("-.")
        return (slug or "memory")[:80]

    def remember(self, name: str, description: str, body: str, memory_type: str = "user") -> Memory:
        memory_type = memory_type if memory_type in self.TYPES else "user"
        filename = f"{self._slug(name)}.md"
        metadata = {"name": name, "description": description, "type": memory_type}
        text = f"---\n{yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()}\n---\n\n{body.strip()}\n"
        (self.directory / filename).write_text(text, encoding="utf-8")
        self.rebuild_index()
        return Memory(name, description, memory_type, body.strip(), filename)

    def _read(self, path: Path) -> Memory | None:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return None
        parts = text.split("---", 2)
        if len(parts) != 3:
            return None
        metadata = yaml.safe_load(parts[1]) or {}
        return Memory(
            str(metadata.get("name", path.stem)),
            str(metadata.get("description", "")),
            str(metadata.get("type", "user")),
            parts[2].strip(),
            path.name,
        )

    def list(self) -> list[Memory]:
        result = []
        for path in sorted(self.directory.glob("*.md")):
            if path.name == "MEMORY.md":
                continue
            try:
                memory = self._read(path)
                if memory:
                    result.append(memory)
            except (OSError, yaml.YAMLError):
                continue
        return result

    def rebuild_index(self) -> None:
        lines = [f"- [{m.name}]({m.filename}) — {m.description}" for m in self.list()]
        self.index_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    # 返回记忆索引的前 25,000 个字符，如果索引文件不存在则返回空字符串
    def index(self) -> str:
        return self.index_path.read_text(encoding="utf-8")[:25_000] if self.index_path.exists() else ""
    # 简单的分词函数，支持英文和中文，返回一个词语集合
    @staticmethod
    def _terms(text: str) -> set[str]:
        latin = re.findall(r"[a-z0-9_-]{2,}", text.lower())
        chinese = re.findall(r"[\u4e00-\u9fff]", text)
        return set(latin + chinese)

    # 返回与查询最相关的记忆列表，按相关度排序，最多返回 limit 个
    def relevant(self, query: str, limit: int = 5) -> list[Memory]:
        query_terms = self._terms(query)
        scored = []
        for memory in self.list():
            terms = self._terms(f"{memory.name} {memory.description} {memory.body}")
            # 简单的相关度评分：查询词与记忆词的交集大小
            score = len(query_terms & terms)
            if score:
                scored.append((score, memory))
        return [item[1] for item in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]]

    # 将与查询相关的记忆渲染成一个字符串，格式化为一个特殊的块，供模型参考
    def render_relevant(self, query: str) -> str:
        memories = self.relevant(query)
        if not memories:
            return ""
        return "<relevant_memories>\n" + "\n\n".join(
            f"## {m.name}\n{m.body}" for m in memories
        ) + "\n</relevant_memories>"
    # 从文本中提取符合特定格式的 JSON 数据，并将其保存为记忆，返回成功保存的记忆数量
    def save_extracted(self, raw_text: str) -> int:
        match = re.search(r"\[.*\]", raw_text, re.DOTALL)
        if not match:
            return 0
        try:
            items = json.loads(match.group())
        except json.JSONDecodeError:
            return 0
        count = 0
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or not item.get("name") or not item.get("body"):
                continue
            self.remember(
                str(item["name"]),
                str(item.get("description", item["name"])),
                str(item["body"]),
                str(item.get("type", "user")),
            )
            count += 1
        return count

