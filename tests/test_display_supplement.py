"""Supplemental tests for zcli.display — show_banner, prompt_text without session, style helpers."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import patch

from zcli.config import Settings
from zcli.display import (
    bold,
    bold_white,
    bright_cyan,
    cyan,
    dim,
    format_console_message,
    green,
    magenta,
    prompt_text,
    show_banner,
    yellow,
)


# ── prompt_text ──────────────────────────────────────────────────────────

def test_prompt_text_without_session_id():
    rendered = prompt_text()

    assert "\033[" in rendered  # Has ANSI color codes
    assert "zcli" in rendered
    assert ">>" in rendered
    # No session id means no magenta parenthesized part
    assert "(" not in rendered  # No session ID display


def test_prompt_text_with_session_id():
    rendered = prompt_text("my-session")

    assert "(my-session)" in rendered


def test_prompt_text_ends_with_space():
    rendered = prompt_text("default")

    assert rendered.endswith(" ")


# ── format_console_message ───────────────────────────────────────────────

def test_format_console_message_parenthesized_hint():
    rendered = format_console_message("(no results)")

    assert rendered.startswith("\033[")
    assert "(no results)" in rendered


def test_format_console_message_label_with_brackets():
    rendered = format_console_message("[ERROR] something went wrong")

    assert rendered.startswith("\033[")
    assert "[ERROR]" in rendered
    assert "something went wrong" in rendered


def test_format_console_message_plain():
    rendered = format_console_message("just a regular message")

    assert rendered == "just a regular message"


# ── style helpers ────────────────────────────────────────────────────────

def test_dim():
    result = dim("text")
    assert "\033[2m" in result
    assert "text" in result
    assert result.endswith("\033[0m")


def test_bold():
    result = bold("text")
    assert "\033[1m" in result
    assert "text" in result


def test_cyan():
    result = cyan("text")
    assert "\033[36m" in result


def test_green():
    result = green("text")
    assert "\033[32m" in result


def test_yellow():
    result = yellow("text")
    assert "\033[33m" in result


def test_magenta():
    result = magenta("text")
    assert "\033[35m" in result


def test_bright_cyan():
    result = bright_cyan("text")
    assert "\033[96m" in result


def test_bold_white():
    result = bold_white("text")
    assert "\033[1m" in result
    assert "\033[37m" in result


# ── show_banner ──────────────────────────────────────────────────────────

def test_show_banner_output_contains_key_parts(tmp_path: Path):
    settings = Settings(tmp_path / "workspace", tmp_path / "data", "test-model", None)

    with StringIO() as buf:
        with patch("sys.stdout", buf):
            show_banner(settings, "test-session", "0.1.0")
        output = buf.getvalue()

    # Banner contains logo (ZCLI in box art) and model/session info
    assert "test-model" in output
    assert "test-session" in output
    assert "0.1.0" in output
    # The logo uses box-drawing chars for "ZCLI" — check for the ASCII fallback
    assert "Personal Coding Agent" in output


def test_show_banner_with_base_url(tmp_path: Path):
    settings = Settings(tmp_path / "workspace", tmp_path / "data", "claude", "https://api.example.com")

    with StringIO() as buf:
        with patch("sys.stdout", buf):
            show_banner(settings, "sess", "0.1.0")
        output = buf.getvalue()

    assert "https://api.example.com" in output
