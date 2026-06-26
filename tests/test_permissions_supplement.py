"""Supplemental tests for zcli.permissions — interactive mode, confirm_action, safe paths."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from zcli.permissions import PermissionPolicy


# ── check_command ─────────────────────────────────────────────────────────

def test_check_command_hard_deny_patterns(tmp_path: Path):
    policy = PermissionPolicy(tmp_path, interactive=True)

    assert "hard deny" in policy.check_command("rm -rf /")
    assert "hard deny" in policy.check_command("rm -rf ~")
    assert "hard deny" in policy.check_command("mkfs.ext4 /dev/sda")
    assert "hard deny" in policy.check_command("dd if=/dev/zero of=/dev/sda")
    assert "hard deny" in policy.check_command("shutdown -h now")
    assert "hard deny" in policy.check_command("reboot")


def test_check_command_requires_approval_when_non_interactive(tmp_path: Path):
    policy = PermissionPolicy(tmp_path, interactive=False)

    assert "requires interactive approval" in policy.check_command("rm file.txt")
    assert "requires interactive approval" in policy.check_command("Remove-Item thing")
    assert "requires interactive approval" in policy.check_command("sudo ls")
    assert "requires interactive approval" in policy.check_command("git push origin main")
    assert "requires interactive approval" in policy.check_command("chmod 777 script.sh")


def test_check_command_asks_in_interactive_mode_and_user_approves(tmp_path: Path):
    policy = PermissionPolicy(tmp_path, interactive=True)

    with patch("builtins.input", return_value="y"):
        result = policy.check_command("rm file.txt")

    assert result is None


def test_check_command_asks_in_interactive_mode_and_user_denies(tmp_path: Path):
    policy = PermissionPolicy(tmp_path, interactive=True)

    with patch("builtins.input", return_value="n"):
        result = policy.check_command("git push")

    assert result == "denied by user"


def test_check_command_asks_in_interactive_mode_user_says_no(tmp_path: Path):
    policy = PermissionPolicy(tmp_path, interactive=True)

    with patch("builtins.input", return_value="no"):
        result = policy.check_command("sudo ls")

    assert result == "denied by user"


def test_check_command_safe_command_passes(tmp_path: Path):
    policy = PermissionPolicy(tmp_path, interactive=False)

    assert policy.check_command("ls -la") is None
    assert policy.check_command("echo hello") is None
    assert policy.check_command("python --version") is None


# ── check_path ────────────────────────────────────────────────────────────

def test_check_path_inside_workspace(tmp_path: Path):
    policy = PermissionPolicy(tmp_path, interactive=False)

    assert policy.check_path("file.txt") is None
    assert policy.check_path("subdir/file.txt") is None


def test_check_path_escapes_workspace(tmp_path: Path):
    policy = PermissionPolicy(tmp_path, interactive=False)

    result = policy.check_path("../outside.txt")
    assert "escapes workspace" in result


def test_check_path_absolute_escape(tmp_path: Path):
    policy = PermissionPolicy(tmp_path / "workspace", interactive=False)

    result = policy.check_path("/etc/passwd")
    assert "escapes workspace" in result


# ── confirm_action ────────────────────────────────────────────────────────

def test_confirm_action_non_interactive_denies(tmp_path: Path):
    policy = PermissionPolicy(tmp_path, interactive=False)

    result = policy.confirm_action("delete everything")

    assert "requires interactive approval" in result


def test_confirm_action_interactive_approve(tmp_path: Path):
    policy = PermissionPolicy(tmp_path, interactive=True)

    with patch("builtins.input", return_value="yes"):
        result = policy.confirm_action("connect to MCP")

    assert result is None


def test_confirm_action_interactive_deny(tmp_path: Path):
    policy = PermissionPolicy(tmp_path, interactive=True)

    with patch("builtins.input", return_value="n"):
        result = policy.confirm_action("remove worktree")

    assert result == "denied by user"


def test_confirm_action_interactive_deny_with_other_input(tmp_path: Path):
    policy = PermissionPolicy(tmp_path, interactive=True)

    with patch("builtins.input", return_value="maybe"):
        result = policy.confirm_action("dangerous action")

    assert result == "denied by user"
