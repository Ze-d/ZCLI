# MCP 外部工具接入

ZCLI 参考 `learn-claude-code` s19/s20，将 MCP 工具实现为后绑定工具：启动时只暴露 `connect_mcp`，连接服务器并完成工具发现后，再把远端工具合入下一次 LLM 请求的工具池。

## 配置

支持三个配置位置，后者覆盖前者：

1. `~/.zcli/mcp.json`
2. `<workspace>/.mcp.json`
3. `<workspace>/.zcli/mcp.json`

```json
{
  "mcpServers": {
    "echo": {
      "command": "python",
      "args": ["examples/mcp/echo_server.py"],
      "env": {"TOKEN": "${ECHO_TOKEN}"},
      "cwd": ".",
      "timeout": 30
    }
  }
}
```

当前支持 stdio transport。`cwd` 必须位于工作区内；`env` 的整值可使用 `${NAME}` 从进程环境读取，避免把密钥写进配置。

## 执行流程

```text
connect_mcp(name)
  → 启动 stdio 子进程（需要用户审批）
  → initialize / notifications/initialized
  → tools/list
  → 转换为 mcp__<server>__<tool>
  → 下一轮 ToolRegistry.definitions 动态包含新工具
  → tools/call
```

服务器名和工具名中不属于 `[A-Za-z0-9_-]` 的字符会变成 `_`，并检查规范化后的名称冲突。远端 `inputSchema` 原样作为模型工具 schema；文本、结构化和错误结果统一转换为字符串 tool result。

## 权限与生命周期

- 启动任意 MCP 子进程都需要交互审批；非交互模式默认拒绝。
- 声明 `annotations.destructiveHint=true` 的工具每次调用都需要审批。
- `readOnlyHint` 与 `destructiveHint` 会显示在工具描述中。
- MCP 调用仍经过 `PreToolUse`、`PostToolUse` 和上下文大结果落盘。
- CLI 退出时关闭全部子进程，超时后按 terminate、kill 顺序回收。

## 当前边界

已实现真实 stdio 的工具发现和调用。尚未实现 HTTP/SSE/WebSocket transport、OAuth、Resources/Prompts、服务端通知、工具列表变更订阅及自动重连。这些属于完整 MCP runtime，而非本阶段的工具桥接核心。
