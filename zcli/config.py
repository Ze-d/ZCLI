from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    workspace: Path
    data_dir: Path
    model: str
    base_url: str | None
    context_limit: int = 50_000
    max_tokens: int = 8_000

    @classmethod
    def load(cls, workspace: str | Path | None = None) -> "Settings":
        load_dotenv(override=False)
        root = Path(workspace or os.getenv("ZCLI_WORKSPACE") or Path.cwd()).resolve()
        data = Path(os.getenv("ZCLI_DATA_DIR") or root / ".zcli").resolve()
        return cls(
            workspace=root,
            data_dir=data,
            model=os.getenv("MODEL_ID", "claude-sonnet-4-6"),
            base_url=os.getenv("ANTHROPIC_BASE_URL"),
            context_limit=int(os.getenv("ZCLI_CONTEXT_LIMIT", "50000")),
        )

