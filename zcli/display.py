"""Terminal display helpers — logo, colors, and startup banner."""

from __future__ import annotations

import shutil
import sys
from typing import Sequence

from .config import Settings

# ── ANSI escape sequences ──────────────────────────────────────────────
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"

# 8-bit colors — avoid termcolored dependencies
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_BLUE = "\033[34m"
_MAGENTA = "\033[35m"
_RED = "\033[31m"
_WHITE = "\033[37m"

# bright variants
_BRIGHT_CYAN = "\033[96m"
_BRIGHT_GREEN = "\033[92m"
_BRIGHT_YELLOW = "\033[93m"
_BRIGHT_BLUE = "\033[94m"
_BRIGHT_MAGENTA = "\033[95m"
_BRIGHT_WHITE = "\033[97m"

# ── Helpers ────────────────────────────────────────────────────────────

def _c(text: str, color: str) -> str:
    """Wrap *text* with *color* and reset."""
    return f"{color}{text}{_RESET}"

def bold(text: str) -> str:      return _c(text, _BOLD)
def dim(text: str) -> str:       return _c(text, _DIM)
def cyan(text: str) -> str:      return _c(text, _CYAN)
def green(text: str) -> str:     return _c(text, _GREEN)
def yellow(text: str) -> str:    return _c(text, _YELLOW)
def blue(text: str) -> str:      return _c(text, _BLUE)
def magenta(text: str) -> str:   return _c(text, _MAGENTA)
def red(text: str) -> str:       return _c(text, _RED)
def white(text: str) -> str:     return _c(text, _WHITE)
def bright_cyan(text: str) -> str:    return _c(text, _BRIGHT_CYAN)

# ── Logo ───────────────────────────────────────────────────────────────

ZCLI_LOGO = r"""
 ██████╗ ██████╗██╗     ██╗
╚══███╔╝██╔════╝██║     ██║
  ███╔╝ ██║     ██║     ██║
 ███╔╝  ██║     ██║     ██║
███████╗╚██████╗███████╗██║
╚══════╝ ╚═════╝╚══════╝╚═╝
"""

# ── Capability descriptions ────────────────────────────────────────────

_CAPABILITIES: Sequence[tuple[str, str]] = [
    ("Chat",         "Multi-turn, tool-use loop, memory injection"),
    ("Memory",       "Auto-extract preferences & facts per turn"),
    ("Session",      "Atomic JSON persistence, multi-session"),
    ("Compact",      "Auto-summarize long context"),
    ("Multi-LLM",    "Anthropic / DeepSeek / MiniMax / GLM / Kimi …"),
    ("Sandbox",     "Path jail + hard-deny dangerous commands"),
]

# ── Banner ─────────────────────────────────────────────────────────────

def show_banner(settings: Settings, session_id: str, version: str = "0.1.0") -> None:
    """Print the startup banner with logo, model, session, and capabilities."""

    term_width = shutil.get_terminal_size().columns
    tag = f"v{version}"

    # ── header line ────────────────────────────────────────────────
    print(bright_cyan("─" * min(term_width, 80)))

    # ── logo + tagline ─────────────────────────────────────────────
    for line in ZCLI_LOGO.strip("\n").splitlines():
        print(cyan(line))
    print(f"  {bold(white('Personal Coding Agent'))}  {dim(tag)}")
    print()

    # ── model & endpoint ───────────────────────────────────────────
    print(f"  {dim('Model')}     {green(settings.model)}")
    if settings.base_url:
        print(f"  {dim('Endpoint')}  {dim(settings.base_url)}")
    print(f"  {dim('Workspace')}  {yellow(str(settings.workspace))}")
    print(f"  {dim('Session')}   {magenta(session_id)}")
    print()

    # ── capabilities ───────────────────────────────────────────────
    print(f"  {bold('Capabilities')}  {dim(f'({len(_CAPABILITIES)} tools & features)')}")
    for icon_label, desc in _CAPABILITIES:
        print(f"    {icon_label:<18}{dim(desc)}")
    print()

    # ── commands ───────────────────────────────────────────────────
    print(f"  {bold('Commands')}    /exit  /quit  /memory  /sessions")
    print(bright_cyan("─" * min(term_width, 80)))
    print()

    # flush in case stdout is line-buffered behind a pipe
    sys.stdout.flush()
