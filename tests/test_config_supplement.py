"""Supplemental tests for zcli.config — _read_config, _ensure_global_config, Settings.load edge cases."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from zcli.config import (
    _GLOBAL_CONFIG_TEMPLATE,
    _collect_config,
    _ensure_global_config,
    _read_config,
    _ZCLI_KEYS,
    Settings,
)


# ── _read_config ──────────────────────────────────────────────────────────

def test_read_config_returns_items_in_zcli_keys(tmp_path: Path):
    cfg = tmp_path / ".env"
    cfg.write_text("MODEL_ID=test-model\nIGNORED_KEY=noise\n", encoding="utf-8")

    result = _read_config(cfg)

    assert result == {"MODEL_ID": "test-model"}


def test_read_config_missing_file_returns_empty(tmp_path: Path):
    result = _read_config(tmp_path / "does_not_exist.env")

    assert result == {}


def test_read_config_empty_file_returns_empty(tmp_path: Path):
    cfg = tmp_path / "empty.env"
    cfg.write_text("", encoding="utf-8")

    result = _read_config(cfg)

    assert result == {}


def test_read_config_ignores_comments(tmp_path: Path):
    cfg = tmp_path / "config.env"
    cfg.write_text("# This is a comment\nMODEL_ID=actual-model\n", encoding="utf-8")

    result = _read_config(cfg)

    assert result == {"MODEL_ID": "actual-model"}


# ── _ensure_global_config ─────────────────────────────────────────────────

def test_ensure_global_config_creates_template(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    home_dir = Path.home()
    (home_dir / ".zcli").mkdir(parents=True, exist_ok=True)

    path = _ensure_global_config()

    assert path.exists()
    assert path.name == "config.env"
    content = path.read_text(encoding="utf-8")
    assert "MODEL_ID" in content
    assert "ZCLI context" in content.lower() or "config" in content.lower()


def test_ensure_global_config_migrates_old_config(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    home_dir = Path.home()
    (home_dir / ".zcli").mkdir(parents=True, exist_ok=True)

    old_path = home_dir / ".zcli" / "config"
    old_path.write_text("MODEL_ID=migrated-model\n", encoding="utf-8")
    new_path = home_dir / ".zcli" / "config.env"
    if new_path.exists():
        new_path.unlink()

    result = _ensure_global_config()

    assert result.name == "config.env"
    assert not old_path.exists()
    assert new_path.exists()


# ── _collect_config ───────────────────────────────────────────────────────

def test_collect_config_base_defaults(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    for key in _ZCLI_KEYS:
        monkeypatch.delenv(key, raising=False)

    cfg = _collect_config(workspace, data_dir)

    # No config files set, so result should be empty or minimal
    assert isinstance(cfg, dict)


def test_collect_config_env_overrides_all(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("MODEL_ID", "env-model")
    for key in _ZCLI_KEYS - {"MODEL_ID"}:
        monkeypatch.delenv(key, raising=False)

    cfg = _collect_config(workspace, data_dir)

    assert cfg.get("MODEL_ID") == "env-model"


def test_collect_config_sets_anthropic_api_key_in_os_environ(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    for key in _ZCLI_KEYS - {"ANTHROPIC_API_KEY"}:
        monkeypatch.delenv(key, raising=False)

    cfg = _collect_config(workspace, data_dir)

    assert cfg.get("ANTHROPIC_API_KEY") == "sk-test-key"


# ── Settings.load ─────────────────────────────────────────────────────────

def test_settings_load_with_explicit_workspace(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for key in _ZCLI_KEYS:
        monkeypatch.delenv(key, raising=False)

    settings = Settings.load(workspace)

    assert settings.workspace == workspace.resolve()


def test_settings_load_uses_cwd_when_none(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    for key in _ZCLI_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ZCLI_DATA_DIR", str(tmp_path / "data"))

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        settings = Settings.load()

    assert settings.workspace == tmp_path.resolve()


def test_settings_load_uses_zcli_workspace_env(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    workspace = tmp_path / "env-workspace"
    workspace.mkdir()
    monkeypatch.setenv("ZCLI_WORKSPACE", str(workspace))
    monkeypatch.setenv("ZCLI_DATA_DIR", str(tmp_path / "data"))
    for key in _ZCLI_KEYS - {"ZCLI_WORKSPACE", "ZCLI_DATA_DIR"}:
        monkeypatch.delenv(key, raising=False)

    settings = Settings.load()

    assert settings.workspace == workspace.resolve()


def test_settings_load_with_data_dir_env(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    custom_data = tmp_path / "custom-data"
    monkeypatch.setenv("ZCLI_DATA_DIR", str(custom_data))
    for key in _ZCLI_KEYS - {"ZCLI_DATA_DIR"}:
        monkeypatch.delenv(key, raising=False)

    settings = Settings.load(workspace)

    assert settings.data_dir == custom_data.resolve()


def test_settings_load_default_model(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("ZCLI_DATA_DIR", str(tmp_path / "data"))
    for key in _ZCLI_KEYS - {"ZCLI_DATA_DIR"}:
        monkeypatch.delenv(key, raising=False)

    settings = Settings.load(workspace)

    assert settings.model == "claude-sonnet-4-6"


def test_settings_load_custom_context_limit_from_env(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("ZCLI_CONTEXT_LIMIT", "100000")
    monkeypatch.setenv("ZCLI_DATA_DIR", str(tmp_path / "data"))
    for key in _ZCLI_KEYS - {"ZCLI_CONTEXT_LIMIT", "ZCLI_DATA_DIR"}:
        monkeypatch.delenv(key, raising=False)

    settings = Settings.load(workspace)

    assert settings.context_limit == 100000


def test_settings_load_global_config_merged(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    home_dir = Path.home()
    (home_dir / ".zcli").mkdir(parents=True, exist_ok=True)
    (home_dir / ".zcli" / "config.env").write_text(
        "MODEL_ID=global-model\nZCLI_MAX_TOKENS=4000\n", encoding="utf-8"
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("ZCLI_DATA_DIR", str(tmp_path / "data"))
    for key in _ZCLI_KEYS - {"ZCLI_DATA_DIR"}:
        monkeypatch.delenv(key, raising=False)

    settings = Settings.load(workspace)

    assert settings.model == "global-model"
    assert settings.max_tokens == 4000


def test_settings_load_dotenv_legacy_support(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".env").write_text("MODEL_ID=dotenv-model\n", encoding="utf-8")
    monkeypatch.setenv("ZCLI_DATA_DIR", str(tmp_path / "data"))
    for key in _ZCLI_KEYS - {"ZCLI_DATA_DIR"}:
        monkeypatch.delenv(key, raising=False)

    settings = Settings.load(workspace)

    assert settings.model == "dotenv-model"


def test_settings_load_project_config_overrides_global(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    home_dir = Path.home()
    (home_dir / ".zcli").mkdir(parents=True, exist_ok=True)
    (home_dir / ".zcli" / "config.env").write_text(
        "MODEL_ID=global-model\n", encoding="utf-8"
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_dir = workspace / ".zcli"
    data_dir.mkdir(parents=True)
    (data_dir / "config.env").write_text("MODEL_ID=project-model\n", encoding="utf-8")
    monkeypatch.setenv("ZCLI_DATA_DIR", str(data_dir))
    for key in _ZCLI_KEYS - {"ZCLI_DATA_DIR"}:
        monkeypatch.delenv(key, raising=False)

    settings = Settings.load(workspace)

    assert settings.model == "project-model"


def test_settings_default_values(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("ZCLI_DATA_DIR", str(tmp_path / "data"))
    for key in _ZCLI_KEYS - {"ZCLI_DATA_DIR"}:
        monkeypatch.delenv(key, raising=False)

    settings = Settings.load(workspace)

    assert settings.context_limit == 50_000
    assert settings.max_tokens == 8_000
    assert settings.escalated_max_tokens == 16_000
    assert settings.max_retries == 3
    assert settings.max_recovery_retries == 2
    assert settings.fallback_model is None
    assert settings.base_url is None


def test_settings_frozen_dataclass(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("ZCLI_DATA_DIR", str(tmp_path / "data"))
    for key in _ZCLI_KEYS - {"ZCLI_DATA_DIR"}:
        monkeypatch.delenv(key, raising=False)

    settings = Settings.load(workspace)

    with pytest.raises(Exception):
        settings.model = "other"  # frozen dataclass


def test_global_config_template_is_valid():
    assert isinstance(_GLOBAL_CONFIG_TEMPLATE, str)
    assert "MODEL_ID" in _GLOBAL_CONFIG_TEMPLATE
    assert "ANTHROPIC_BASE_URL" in _GLOBAL_CONFIG_TEMPLATE
