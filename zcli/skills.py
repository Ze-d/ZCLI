from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    directory: Path
    manifest: Path
    content: str


class SkillRegistry:
    """Two-level skill loader based on learn-claude-code s07."""

    def __init__(self, skills_dir: Path, catalog_budget: int = 8_000):
        self.directory = skills_dir.resolve()
        self.catalog_budget = catalog_budget
        self._skills: dict[str, Skill] = {}
        self.errors: list[str] = []
        self.scan()

    @staticmethod
    def _parse_frontmatter(text: str) -> tuple[dict, str]:
        if not text.startswith("---"):
            return {}, text
        parts = text.split("---", 2)
        if len(parts) < 3:
            raise ValueError("frontmatter is not closed with ---")
        metadata = yaml.safe_load(parts[1]) or {}
        if not isinstance(metadata, dict):
            raise ValueError("frontmatter must be a YAML mapping")
        return metadata, parts[2].strip()

    @staticmethod
    def _fallback_description(body: str, directory_name: str) -> str:
        for line in body.splitlines():
            cleaned = line.strip().lstrip("#").strip()
            if cleaned:
                return cleaned[:300]
        return f"Instructions from {directory_name}"

    @staticmethod
    def _validate_name(name: str) -> str:
        name = name.strip()
        if not name or len(name) > 100 or re.search(r"[\x00-\x1f]", name):
            raise ValueError("skill name must be 1-100 printable characters")
        return name

    def scan(self) -> tuple[Skill, ...]:
        self._skills.clear()
        self.errors.clear()
        if not self.directory.exists():
            return ()

        for child in sorted(self.directory.iterdir(), key=lambda path: path.name.lower()):
            if not child.is_dir():
                continue
            try:
                resolved = child.resolve()
                if not resolved.is_relative_to(self.directory):
                    raise ValueError("skill directory escapes skills root")
                manifest = resolved / "SKILL.md"
                if not manifest.is_file():
                    continue
                # utf-8-sig accepts normal UTF-8 and strips a PowerShell BOM.
                raw = manifest.read_text(encoding="utf-8-sig")
                metadata, body = self._parse_frontmatter(raw)
                name = self._validate_name(str(metadata.get("name") or child.name))
                description = str(
                    metadata.get("description")
                    or self._fallback_description(body, child.name)
                ).strip()[:500]
                if name in self._skills:
                    raise ValueError(f"duplicate skill name: {name}")
                self._skills[name] = Skill(name, description, resolved, manifest, raw)
            except (OSError, UnicodeError, yaml.YAMLError, ValueError) as error:
                self.errors.append(f"{child.name}: {type(error).__name__}: {error}")
        return self.list()

    def list(self, refresh: bool = False) -> tuple[Skill, ...]:
        if refresh:
            self.scan()
        return tuple(sorted(self._skills.values(), key=lambda skill: skill.name.lower()))

    def catalog(self, refresh: bool = True) -> str:
        skills = self.list(refresh=refresh)
        if not skills:
            return "(no skills found)"
        lines = []
        used = 0
        for skill in skills:
            line = f"- {skill.name}: {skill.description}"
            if lines and used + len(line) + 1 > self.catalog_budget:
                lines.append("- ... additional skills omitted by catalog budget")
                break
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines)

    def load(self, name: str, refresh: bool = True) -> str:
        if refresh:
            self.scan()
        skill = self._skills.get(name)
        if not skill:
            available = ", ".join(item.name for item in self.list()) or "(none)"
            return f"Skill not found: {name}. Available: {available}"
        return (
            "<skill>\n"
            f"Name: {skill.name}\n"
            f"Directory: {skill.directory}\n\n"
            f"{skill.content}\n"
            "</skill>"
        )
