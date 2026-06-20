# 测试用例

## 待实现

### test_permissions.py

- [ ] `test_hard_deny_rm_rf_root` — `rm -rf /` 被拒绝
- [ ] `test_hard_deny_mkfs` — `mkfs` 被拒绝
- [ ] `test_hard_deny_dd` — `dd if=/dev/zero` 被拒绝
- [ ] `test_hard_deny_shutdown` — `shutdown` 被拒绝
- [ ] `test_path_escape_dotdot` — `../../etc/passwd` 被拒绝
- [ ] `test_path_escape_abs` — 绝对路径被拒绝
- [ ] `test_workspace_relative_ok` — `src/main.py` 通过
- [ ] `test_interactive_approve_rm` — `rm file.txt` 需审批

### test_cli.py

- [ ] `test_help_flag` — `--help` 返回 0 且包含 usage
- [ ] `test_list_sessions_empty` — 空数据目录输出为空
- [ ] `test_new_session_rejects_existing` — `--new --session existing` 报错
- [ ] `test_default_session_created` — 首次运行自动创建 default

### test_config.py

- [ ] `test_default_model` — 未设置时默认 `claude-sonnet-4-6`
- [ ] `test_custom_model_from_env` — `MODEL_ID` 覆盖默认
- [ ] `test_base_url_optional` — 未设置时 `base_url=None`
- [ ] `test_workspace_from_env` — `ZCLI_WORKSPACE` 生效
