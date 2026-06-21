from zcli.permissions import PermissionPolicy


def test_non_interactive_approval_command_is_denied(tmp_path):
    policy = PermissionPolicy(tmp_path, interactive=False)
    assert policy.check_command("git push") == "command requires interactive approval"


def test_hard_deny_does_not_require_approval(tmp_path):
    policy = PermissionPolicy(tmp_path, interactive=False)
    assert policy.check_command("rm -rf /") == "command matches the hard deny policy"
