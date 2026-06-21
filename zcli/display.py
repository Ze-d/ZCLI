"""Terminal display helpers — logo, colors, and startup banner."""

from __future__ import annotations

import ctypes
import re
import shutil
import sys
from typing import Sequence

from .config import Settings

# ── Enable ANSI on Windows Terminal ────────────────────────────────────
def _enable_windows_ansi() -> None:
    """Enable virtual terminal processing on Windows 10+."""
    if sys.platform != "win32":
        return
    kernel32 = ctypes.windll.kernel32
    for handle_id in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
        handle = kernel32.GetStdHandle(handle_id)
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING

_enable_windows_ansi()

# ── ANSI escape sequences ──────────────────────────────────────────────
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"

# 4-bit colors
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_MAGENTA = "\033[35m"
_WHITE = "\033[37m"

# bright variants
_BRIGHT_CYAN = "\033[96m"
_BRIGHT_WHITE = "\033[97m"

# ── Style helpers (flat, no nesting needed) ────────────────────────────

def _style(text: str, *codes: str) -> str:
    """Apply one or more SGR codes, single reset at end."""
    return f"{''.join(codes)}{text}{_RESET}"

def dim(text: str) -> str:             return _style(text, _DIM)
def bold(text: str) -> str:            return _style(text, _BOLD)
def cyan(text: str) -> str:            return _style(text, _CYAN)
def green(text: str) -> str:           return _style(text, _GREEN)
def yellow(text: str) -> str:          return _style(text, _YELLOW)
def magenta(text: str) -> str:         return _style(text, _MAGENTA)
def bright_cyan(text: str) -> str:     return _style(text, _BRIGHT_CYAN)
def bold_white(text: str) -> str:      return _style(text, _BOLD, _WHITE)


_LEADING_LABEL = re.compile(r"^(\[[^\]\r\n]+\])")
_PARENTHESIZED_HINT = re.compile(r"^(\([^\)\r\n]+\))$")


def prompt_text(session_id: str = "") -> str:
    """Build the colored REPL prompt without leaking ANSI into user input."""
    session = f" {magenta(f'({session_id})')}" if session_id else ""
    return f"{_style('zcli', _BOLD, _BRIGHT_CYAN)}{session} {green('>>')} "


def format_console_message(message: str) -> str:
    """Color a leading ``[status]`` label or a standalone ``(hint)``."""
    label = _LEADING_LABEL.match(message)
    if label:
        colored = _style(label.group(1), _BOLD, _MAGENTA)
        return colored + message[label.end():]
    hint = _PARENTHESIZED_HINT.match(message)
    if hint:
        return yellow(hint.group(1))
    return message


def console_emit(message: str) -> None:
    """Print an agent event with terminal-only decoration."""
    print(format_console_message(message))

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
    ("Planning",     "Session todos + durable dependency task graph"),
    ("Skills",       "Catalog in prompt, full instructions on demand"),
    ("MCP",          "Connect stdio/HTTP servers and add tools dynamically"),
    ("Agents",       "Isolated subagents + autonomous teammate threads"),
    ("Worktrees",    "Task-bound git worktree isolation"),
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
    print(f"  {bold_white('Personal Coding Agent')}  {dim(tag)}")
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
    print(f"  {bold('Commands')}    /exit /memory /sessions /todos /tasks /skills /mcp /team /worktrees")
    print(bright_cyan("─" * min(term_width, 80)))
    print()

    # flush in case stdout is line-buffered behind a pipe
    sys.stdout.flush()
