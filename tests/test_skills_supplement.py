"""Supplemental tests for zcli.skills — _validate_name, scan edge cases, load without refresh."""

from __future__ import annotations

from pathlib import Path

from zcli.skills import SkillRegistry


def write_skill(root: Path, directory: str, content: str) -> Path:
    target = root / directory
    target.mkdir(parents=True)
    manifest = target / "SKILL.md"
    manifest.write_text(content, encoding="utf-8")
    return manifest


# ── _validate_name ───────────────────────────────────────────────────────

def test_validate_name_valid():
    assert SkillRegistry._validate_name("code-review") == "code-review"
    assert SkillRegistry._validate_name("  my-skill  ") == "my-skill"


def test_validate_name_empty():
    try:
        SkillRegistry._validate_name("")
        assert False, "Should have raised"
    except ValueError:
        pass


def test_validate_name_too_long():
    try:
        SkillRegistry._validate_name("a" * 101)
        assert False, "Should have raised"
    except ValueError:
        pass


def test_validate_name_control_chars():
    try:
        SkillRegistry._validate_name("bad\nskill")
        assert False, "Should have raised"
    except ValueError:
        pass


# ── _parse_frontmatter ───────────────────────────────────────────────────

def test_parse_frontmatter_not_a_dict():
    try:
        SkillRegistry._parse_frontmatter("---\n- list item\n---\nbody")
        assert False, "Should have raised"
    except ValueError as e:
        assert "mapping" in str(e)


# ── _fallback_description ────────────────────────────────────────────────

def test_fallback_description_from_heading():
    desc = SkillRegistry._fallback_description("# My Skill\n\nSome instructions.", "myskill")

    assert desc == "My Skill"


def test_fallback_description_from_plain_text():
    desc = SkillRegistry._fallback_description("First line of the skill.", "myskill")

    assert desc == "First line of the skill."


def test_fallback_description_empty_body():
    desc = SkillRegistry._fallback_description("", "myskill")

    assert "myskill" in desc


# ── scan edge cases ──────────────────────────────────────────────────────

def test_scan_directory_does_not_exist(tmp_path: Path):
    registry = SkillRegistry(tmp_path / "nonexistent")

    assert registry.list() == ()
    assert registry.catalog() == "(no skills found)"


def test_scan_skips_files(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "README.md").write_text("not a skill", encoding="utf-8")

    registry = SkillRegistry(skills_dir)

    assert len(registry.list()) == 0


def test_scan_directory_without_skill_md(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    subdir = skills_dir / "no-manifest"
    subdir.mkdir(parents=True)
    (subdir / "helper.py").write_text("# helper", encoding="utf-8")

    registry = SkillRegistry(skills_dir)

    assert len(registry.list()) == 0


def test_scan_with_bom_encoding(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    target = skills_dir / "bom-skill"
    target.mkdir(parents=True)
    manifest = target / "SKILL.md"
    # Write with UTF-8 BOM
    manifest.write_bytes(b"\xef\xbb\xbf---\nname: bom-skill\ndescription: BOM test\n---\nBody here")

    registry = SkillRegistry(skills_dir)

    assert "bom-skill" in [s.name for s in registry.list()]


# ── load without refresh ─────────────────────────────────────────────────

def test_load_without_refresh(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    write_skill(skills_dir, "static", "---\nname: static-skill\ndescription: Static\n---\nStatic body")

    registry = SkillRegistry(skills_dir)
    # Load with refresh=False should use cached skills
    content = registry.load("static-skill", refresh=False)

    assert "Static body" in content


def test_load_missing_skill_lists_available(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    write_skill(skills_dir, "only-one", "---\nname: only-one\ndescription: The only skill\n---\nBody")

    registry = SkillRegistry(skills_dir)
    result = registry.load("missing-skill")

    assert "not found" in result
    assert "only-one" in result


# ── list with refresh ────────────────────────────────────────────────────

def test_list_refresh_rescans(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    registry = SkillRegistry(skills_dir)
    assert len(registry.list()) == 0

    write_skill(skills_dir, "new", "---\nname: new-skill\ndescription: Fresh\n---\nFresh body")

    assert len(registry.list(refresh=True)) == 1
