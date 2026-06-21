# MCP 外部工具接入

ZCLI 参考 `learn-claude-code` s19/s20，将 MCP 工具实现为后绑定工具：启动时只暴露 `connect_mcp`，通过 stdio 或 Streamable HTTP 连接服务器并完成工具发现后，再把远端工具合入下一次 LLM 请求的工具池。

## 配置

支持三个配置位置，后者覆盖前者：

1. `~/.zcli/mcp.json`
2. `<workspace>/.mcp.json`
3. `<workspace>/.zcli/mcp.json`

stdio Server 由 ZCLI 启动：

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

已经独立运行的 Streamable HTTP Server 只需配置 URL：

```json
{
  "mcpServers": {
    "zotero": {
      "transport": "streamable_http",
      "url": "http://127.0.0.1:23120/mcp",
      "headers": {
        "Authorization": "Bearer ${ZOTERO_MCP_TOKEN}"
      },
      "timeout": 30
    }
  }
}
```

未写 `transport` 时默认为 `stdio`。stdio 的 `cwd` 必须位于工作区内；`env` 和 HTTP `headers` 支持 `${NAME}` 环境变量替换，避免把密钥写进配置。HTTP URL 只允许 `http`/`https`，禁止 URL userinfo 和覆盖 MCP 保留请求头。

## 执行流程

```text
connect_mcp(name)
  → transport 分发
      ├─ stdio：启动配置的子进程
      └─ streamable_http：连接已经运行的 MCP endpoint
  → initialize / notifications/initialized
  → tools/list
  → 转换为 mcp__<server>__<tool>
  → 下一轮 ToolRegistry.definitions 动态包含新工具
  → tools/call
```

Streamable HTTP 对每条 JSON-RPC 消息发送独立 POST，同时接受 `application/json` 和 `text/event-stream` 响应。初始化返回的 `Mcp-Session-Id` 会用于后续请求，并携带协商后的 `MCP-Protocol-Version`；会话返回 404 时自动重新初始化一次。

服务器名和工具名中不属于 `[A-Za-z0-9_-]` 的字符会变成 `_`，并检查规范化后的名称冲突。远端 `inputSchema` 原样作为模型工具 schema；文本、结构化和错误结果统一转换为字符串 tool result。

## 权限与生命周期

- 连接任意 MCP Server 都需要交互审批；非交互模式默认拒绝。
- 声明 `annotations.destructiveHint=true` 的工具每次调用都需要审批。
- `readOnlyHint` 与 `destructiveHint` 会显示在工具描述中。
- MCP 调用仍经过 `PreToolUse`、`PostToolUse` 和上下文大结果落盘。
- CLI 退出时关闭全部连接：stdio 按 EOF、terminate、kill 回收子进程；有 Session ID 的 HTTP Server 发送 DELETE 终止会话。

## 当前边界

已实现真实 stdio 和 Streamable HTTP 的工具发现与调用，并支持 HTTP JSON/SSE 请求响应。尚未实现旧版 HTTP+SSE transport、WebSocket、OAuth、Resources/Prompts、独立 GET 通知流、SSE 断点续传、工具列表变更订阅及通用自动重连。这些属于完整 MCP runtime，而非当前 Tools 桥接核心。
