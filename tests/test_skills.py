from pathlib import Path
from types import SimpleNamespace

from zcli.agent import Agent
from zcli.config import Settings
from zcli.skills import SkillRegistry


def write_skill(root: Path, directory: str, content: str) -> Path:
    target = root / directory
    target.mkdir(parents=True)
    manifest = target / "SKILL.md"
    manifest.write_text(content, encoding="utf-8")
    return manifest


def test_catalog_is_metadata_only_and_load_is_full_content(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    write_skill(
        skills_dir,
        "review",
        "---\nname: code-review\ndescription: Review Python safely\n---\n\n# Instructions\nSECRET-BODY-MARKER",
    )
    registry = SkillRegistry(skills_dir)

    catalog = registry.catalog(refresh=False)

    assert "code-review: Review Python safely" in catalog
    assert "SECRET-BODY-MARKER" not in catalog
    assert "SECRET-BODY-MARKER" in registry.load("code-review", refresh=False)


def test_skill_without_frontmatter_uses_directory_and_heading(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    write_skill(skills_dir, "plain-skill", "# Plain skill description\n\nFollow this.")

    skill = SkillRegistry(skills_dir).list()[0]

    assert skill.name == "plain-skill"
    assert skill.description == "Plain skill description"


def test_registry_hot_rescans_and_reports_missing_skill(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    registry = SkillRegistry(skills_dir)
    assert registry.catalog() == "(no skills found)"

    write_skill(skills_dir, "new", "---\nname: new-skill\ndescription: Added at runtime\n---\nUse it.")

    assert "new-skill" in registry.catalog()
    assert "Available: new-skill" in registry.load("missing")


def test_malformed_and_duplicate_skills_are_diagnosed(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    write_skill(skills_dir, "a", "---\nname: duplicate\ndescription: first\n---\nA")
    write_skill(skills_dir, "b", "---\nname: duplicate\ndescription: second\n---\nB")
    write_skill(skills_dir, "broken", "---\nname: [unterminated\n---\nBroken")

    registry = SkillRegistry(skills_dir)

    assert len(registry.list()) == 1
    assert any("duplicate skill name" in error for error in registry.errors)
    assert any("YAMLError" in error or "ParserError" in error for error in registry.errors)


def test_catalog_budget_omits_extra_metadata(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    for index in range(3):
        write_skill(
            skills_dir,
            f"skill-{index}",
            f"---\nname: skill-{index}\ndescription: {'x' * 40}\n---\nBody {index}",
        )

    catalog = SkillRegistry(skills_dir, catalog_budget=70).catalog(refresh=False)

    assert "additional skills omitted" in catalog


class Block:
    def __init__(self, **values):
        self.values = values

    def model_dump(self, exclude_none=True):
        return self.values


class SkillMessages:
    def __init__(self):
        self.main_calls = 0
        self.first_system = ""
        self.second_messages = None

    def create(self, **kwargs):
        if "tools" not in kwargs:
            return SimpleNamespace(content=[Block(type="text", text="[]")], stop_reason="end_turn")
        self.main_calls += 1
        if self.main_calls == 1:
            self.first_system = kwargs["system"]
            return SimpleNamespace(
                content=[Block(type="tool_use", id="skill-1", name="load_skill", input={"name": "code-review"})],
                stop_reason="tool_use",
            )
        self.second_messages = kwargs["messages"]
        return SimpleNamespace(content=[Block(type="text", text="reviewed")], stop_reason="end_turn")


def test_agent_loads_skill_through_tool_result(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_skill(
        workspace / "skills",
        "review",
        "---\nname: code-review\ndescription: Review Python code\n---\nFULL-REVIEW-INSTRUCTIONS",
    )
    messages = SkillMessages()
    agent = Agent(
        Settings(workspace, tmp_path / "data", "fake", None),
        client=SimpleNamespace(messages=messages),
        interactive=False,
    )

    output = agent.run_turn(agent.sessions.create("skill"), "review code", emit=lambda _: None)

    assert output == "reviewed"
    assert "code-review: Review Python code" in messages.first_system
    assert "FULL-REVIEW-INSTRUCTIONS" not in messages.first_system
    assert "FULL-REVIEW-INSTRUCTIONS" in str(messages.second_messages)
