# API 契约

## 对外 CLI 接口

```
zcli [--workspace PATH] [--session NAME] [--new] [--list-sessions]
```

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `--workspace` | Path | `$ZCLI_WORKSPACE` 或 cwd | Agent 可访问的工作目录 |
| `--session` | str | `"default"` | 会话 ID |
| `--new` | flag | false | 强制新建会话（同名存在则报错） |
| `--list-sessions` | flag | false | 列出所有会话并退出 |

## 内置命令

在 REPL 提示符 `zcli >>` 下输入：

| 命令 | 效果 |
|------|------|
| `/exit` `/quit` | 退出 |
| `/memory` | 显示长期记忆索引 |
| `/sessions` | 列出已保存会话 |
| `/todos` | 显示当前 Session Todo |
| `/tasks` | 显示持久 Task Graph |
| `/skills` | 显示 Skill Catalog 和扫描诊断 |
| `/mcp` | 显示 MCP 配置、连接状态和工具数量 |

## 配置契约

通过 `.env` 或环境变量配置：

| 变量 | 必需 | 默认 | 说明 |
|------|------|------|------|
| `MODEL_ID` | 否 | `claude-sonnet-4-6` | 模型 ID |
| `ANTHROPIC_BASE_URL` | 否 | `https://api.anthropic.com` | API 端点 |
| `ANTHROPIC_API_KEY` | 是* | — | API 密钥（Anthropic SDK 读取） |
| `ZCLI_WORKSPACE` | 否 | cwd | 默认工作区 |
| `ZCLI_DATA_DIR` | 否 | `<workspace>/.zcli` | 数据目录 |
| `ZCLI_CONTEXT_LIMIT` | 否 | `50000` | 上下文 token 上限 |

## Agent 内部接口

### `Agent.run_turn(session, query, emit=print) -> str`

- **输入**: Session 对象 + 用户查询字符串
- **输出**: LLM 最终文本回复
- **副作用**: 修改 session.messages、可能触发 compact、可能抽取 memory
- **规划状态**: 修改 `session.todos` / `rounds_since_todo`，并读写 `.zcli/tasks/`
- **emit**: 回调函数，默认 `print`，用于输出流式文本和工具结果

### `ToolRegistry.execute(name, arguments) -> str`

- 14 个内置工具：`bash`, `read_file`, `write_file`, `edit_file`, `glob`, `remember`, `todo_write`, `create_task`, `list_tasks`, `get_task`, `claim_task`, `complete_task`, `load_skill`, `connect_mcp`
- 连接后动态增加 `mcp__<server>__<tool>` 工具；定义来自远端 `tools/list`
- 所有工具返回字符串（成功消息或错误信息）
- bash/文件工具、MCP 连接和 destructive MCP 工具受 `PermissionPolicy` 约束
