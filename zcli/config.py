from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


# Keys that ZCLI cares about (filter noise from os.environ)
_ZCLI_KEYS = frozenset({
    "MODEL_ID",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_API_KEY",
    "ZCLI_WORKSPACE",
    "ZCLI_DATA_DIR",
    "ZCLI_CONTEXT_LIMIT",
    "FALLBACK_MODEL_ID",
    "ZCLI_MAX_TOKENS",
    "ZCLI_ESCALATED_MAX_TOKENS",
    "ZCLI_MAX_RETRIES",
    "ZCLI_MAX_RECOVERY_RETRIES",
})

# Default template for ~/.zcli/config.env
_GLOBAL_CONFIG_TEMPLATE = """\
# ZCLI global config — overrides built-in defaults, overridden by:
#   <workspace>/.zcli/config.env  >  .env  >  environment variables
#
# Uncomment and edit:

# Model ID
# MODEL_ID=claude-sonnet-4-6

# API base URL (omit for default Anthropic endpoint)
# ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic

# API Key (prefer setting this as an environment variable for security)
# ANTHROPIC_API_KEY=sk-ant-xxx

# Context limit in tokens
# ZCLI_CONTEXT_LIMIT=50000

# Recovery
# FALLBACK_MODEL_ID=
# ZCLI_MAX_TOKENS=8000
# ZCLI_ESCALATED_MAX_TOKENS=16000
# ZCLI_MAX_RETRIES=3
# ZCLI_MAX_RECOVERY_RETRIES=2
"""


def _read_config(path: Path) -> dict[str, str]:
    """Read KEY=VALUE file, strip comments, return clean dict."""
    if not path.exists():
        return {}
    raw = dotenv_values(path)
    return {k: v for k, v in raw.items() if v is not None and k in _ZCLI_KEYS}


def _ensure_global_config() -> Path:
    """Create ~/.zcli/config.env with a template on first run. Returns the path.

    Migrates old ~/.zcli/config → ~/.zcli/config.env if found.
    """
    global_dir = Path.home() / ".zcli"
    global_dir.mkdir(parents=True, exist_ok=True)

    old_path = global_dir / "config"
    new_path = global_dir / "config.env"

    # Migrate old extensionless config
    if old_path.exists() and not new_path.exists():
        old_path.rename(new_path)

    if not new_path.exists():
        new_path.write_text(_GLOBAL_CONFIG_TEMPLATE, encoding="utf-8")

    return new_path


def _collect_config(workspace: Path, data_dir: Path) -> dict[str, str]:
    """Merge config sources by priority (highest wins at the end).

    Priority (lowest → highest):
      1. built-in defaults
      2. .env                     (legacy, workspace root)
      3. ~/.zcli/config.env       (global user config)
      4. <workspace>/.zcli/config.env (project config)
      5. environment variables    (highest)
    """
    merged: dict[str, str] = {}

    # 2. legacy .env
    env_cfg = _read_config(workspace / ".env")
    merged.update(env_cfg)

    # 3. global user config (overrides .env)
    global_cfg = _read_config(_ensure_global_config())
    merged.update(global_cfg)

    # 4. project config (overrides global) — read both old and new names
    project_cfg = _read_config(data_dir / "config.env")
    if not project_cfg:
        project_cfg = _read_config(data_dir / "config")  # legacy
    merged.update(project_cfg)

    # 5. environment variables (highest priority)
    for key in _ZCLI_KEYS:
        val = os.getenv(key)
        if val is not None:
            merged[key] = val

    # Ensure ANTHROPIC_API_KEY is visible to the Anthropic SDK
    if "ANTHROPIC_API_KEY" in merged and "ANTHROPIC_API_KEY" not in os.environ:
        os.environ["ANTHROPIC_API_KEY"] = merged["ANTHROPIC_API_KEY"]

    return merged


@dataclass(frozen=True)
class Settings:
    workspace: Path
    data_dir: Path
    model: str
    base_url: str | None
    context_limit: int = 50_000
    max_tokens: int = 8_000
    escalated_max_tokens: int = 16_000
    fallback_model: str | None = None
    max_retries: int = 3
    max_recovery_retries: int = 2

    @classmethod
    def load(cls, workspace: str | Path | None = None) -> "Settings":
        root = Path(workspace or os.getenv("ZCLI_WORKSPACE") or Path.cwd()).resolve()
        data = Path(os.getenv("ZCLI_DATA_DIR") or root / ".zcli").resolve()

        cfg = _collect_config(root, data)

        return cls(
            workspace=root,
            data_dir=data,
            model=cfg.get("MODEL_ID", "claude-sonnet-4-6"),
            base_url=cfg.get("ANTHROPIC_BASE_URL"),
            context_limit=int(cfg.get("ZCLI_CONTEXT_LIMIT", "50000")),
            max_tokens=int(cfg.get("ZCLI_MAX_TOKENS", "8000")),
            escalated_max_tokens=int(cfg.get("ZCLI_ESCALATED_MAX_TOKENS", "16000")),
            fallback_model=cfg.get("FALLBACK_MODEL_ID"),
            max_retries=int(cfg.get("ZCLI_MAX_RETRIES", "3")),
            max_recovery_retries=int(cfg.get("ZCLI_MAX_RECOVERY_RETRIES", "2")),
        )
