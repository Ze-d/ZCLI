# MCP 实现面试讲解

## 1. 一句话介绍

我在 ZCLI 中实现了一个支持 stdio 和 Streamable HTTP 的真实 MCP 工具桥接层：既能启动本地子进程，也能连接已经运行的 Zotero 一类 HTTP Server，完成初始化和工具发现后，再把远端工具以 `mcp__server__tool` 的形式动态合入下一轮 LLM 工具池。

这套设计参考了 `learn-claude-code` s19/s20 的后绑定工具思路，但没有停留在教学版 mock，而是实现了真实子进程、Streamable HTTP、JSON/SSE 双响应、Session ID、超时、权限审批和连接关闭。

## 2. MCP 解决什么问题

没有 MCP 时，每接一个外部系统都要在 Agent 内部手写工具：

- 接 Jira，要写查询 Issue、创建 Ticket 的代码；
- 接知识库，要写搜索和读取文档的代码；
- 接部署平台，要写发布、回滚和查看日志的代码；
- 每个工具还要重复处理 schema、调用、错误和鉴权。

MCP 把这部分变成标准协议：

```text
Agent / MCP Client                 外部 MCP Server
       │                                  │
       ├──── initialize ─────────────────>│
       ├──── tools/list ─────────────────>│
       │<─── 工具名称、描述、Schema ───────┤
       ├──── tools/call ─────────────────>│
       │<─── content / isError ───────────┤
```

因此 ZCLI 不需要知道外部工具由 Python、Java 还是 TypeScript 编写，只需要遵循 MCP 协议。

## 3. 核心设计：后绑定工具

MCP 工具在 Agent 启动时并不存在，只有连接 Server 并执行 `tools/list` 后才能知道。

```text
首次模型调用
  工具池 = 14 个内置工具 + connect_mcp
                  │
                  ▼
模型调用 connect_mcp("echo")
                  │
                  ▼
initialize → tools/list → 注册 mcp__echo__echo
                  │
                  ▼
下一次模型调用
  工具池 = 内置工具 + mcp__echo__echo
```

这叫后绑定或 late binding：能力不是在编译期或启动期固定，而是在运行期连接、发现并加入工具池。

它也是本实现最核心的架构点。

---

# 模块结构

## 4. 各模块职责

```text
zcli/mcp.py
  ├─ MCPServerConfig   配置模型
  ├─ MCPTool           远端工具模型
  ├─ load_mcp_config   多层配置合并与校验
  ├─ StdioMCPClient    子进程与 JSON-RPC 通信
  ├─ StreamableHTTPMCPClient 连接独立 HTTP Server
  └─ MCPManager        连接管理、发现、路由和关闭

zcli/tools.py
  ├─ 注册 connect_mcp
  ├─ 动态拼接 MCP tool definitions
  ├─ 把 mcp__* 调用路由给 MCPManager
  └─ 接入权限策略

zcli/agent.py
  ├─ 创建并注入 MCPManager
  ├─ 把 MCP 状态放入 System Prompt
  └─ 退出时关闭 MCP 子进程

zcli/cli.py
  ├─ /mcp 查看配置和连接状态
  └─ finally 中调用 agent.close()
```

我把“协议通信”和“Agent 工具编排”分开：`StdioMCPClient` 不关心 LLM，`ToolRegistry` 也不关心 JSON-RPC 细节。

## 5. 两个核心数据模型

### MCPServerConfig

```python
@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    transport: str = "stdio"
    command: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    timeout: float = 30.0
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
```

它同时描述两种连接方式：stdio 使用命令、参数、环境变量和工作目录；Streamable HTTP 使用 URL、自定义鉴权 Header 和请求超时。

### MCPTool

```python
@dataclass(frozen=True)
class MCPTool:
    server_name: str
    remote_name: str
    name: str
    description: str
    input_schema: dict
    annotations: dict
```

这里同时保留两个名称：

- `remote_name`：调用 `tools/call` 时发给 Server 的原始名称；
- `name`：暴露给模型的公共名称，例如 `mcp__docs__search`。

分开保存非常重要，因为公共名称经过命名空间和规范化处理，不能直接当作远端工具名。

---

# 配置加载

## 6. 三层配置优先级

ZCLI 按以下顺序合并 MCP 配置，后者覆盖前者：

```text
~/.zcli/mcp.json
        ↓
<workspace>/.mcp.json
        ↓
<workspace>/.zcli/mcp.json
```

分别对应：

- 用户级默认配置；
- 可共享的项目配置；
- 当前项目的本地覆盖配置。

配置格式：

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

## 7. 配置安全与容错

配置加载不是简单地 `json.loads()`，还做了以下校验：

1. Server 名称必须是非空字符串；
2. `command` 必须是非空字符串；
3. `args` 必须是字符串数组；
4. `env` 的键和值都必须是字符串；
5. `cwd` 解析后不能逃逸工作区；
6. 规范化后的 Server 名不能发生冲突；
7. 单个错误记录到 `errors`，不让整个 CLI 崩溃。

环境变量支持模板引用：

```json
{"TOKEN": "${DEPLOY_TOKEN}"}
```

运行时从进程环境获取真实值。变量不存在时直接报错，而不是把 `${DEPLOY_TOKEN}` 当作真实令牌传给 Server。

HTTP Header 也支持模板替换，例如 `Bearer ${MCP_TOKEN}`。URL 只允许 `http`/`https`，禁止在 URL userinfo 中写账号密码，也禁止覆盖 Session ID、协议版本、Host、Content-Type 等 transport 保留 Header。

---

# Transport 与协议实现

## 8. 为什么选择 stdio

stdio 是最适合第一版真实 MCP 的 transport：

- 跨平台，Python `subprocess` 可以直接实现；
- 不需要端口管理和网络服务发现；
- Server 生命周期可以跟随 ZCLI；
- 能完整演示 MCP 的初始化、发现和调用主链路。

ZCLI 使用以下方式启动 Server：

```python
subprocess.Popen(
    [config.command, *config.args],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    encoding="utf-8",
    bufsize=1,
)
```

stdin/stdout 传输逐行 JSON-RPC 消息，stderr 单独收集诊断，避免污染协议输出。

## 9. 连接握手

`StdioMCPClient.connect()` 的顺序是：

```text
1. 校验和解析 env、cwd
2. 启动 MCP Server 子进程
3. 启动 stdout 和 stderr 读取线程
4. 发送 initialize 请求
5. 发送 notifications/initialized 通知
6. 发送 tools/list 请求
7. 保存 Server 返回的工具列表
```

初始化请求包含：

```python
{
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {"name": "zcli", "version": "0.1.0"},
}
```

如果任何一步失败，`connect()` 会关闭已经启动的子进程再抛出错误，避免留下孤儿进程。

## 10. JSON-RPC 请求关联

每个请求都有单调递增的 ID：

```python
self._request_id += 1
request_id = self._request_id
```

请求结构：

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/list",
  "params": {}
}
```

收到消息后，根据 ID 找到对应请求。如果响应包含 `error`，转换为 Python 异常；否则返回 `result`。

当前每个 Client 使用 `RLock` 串行请求：

```python
with self._lock:
    发送请求
    等待对应响应
```

这样第一版不用维护 `request_id → Future` 的并发映射，状态更容易保证正确。代价是同一个 Server 的多个工具调用不能并发。

## 11. 为什么要用读取线程和 Queue

如果在工具调用线程里直接执行 `stdout.readline()`，Server 卡住时主 Agent 也会无限阻塞，而且 stderr 输出过多还可能堵满管道。

因此实现中有两条 daemon 线程：

```text
stdout reader ── JSON decode ──> Queue ──> _read_message()
stderr reader ── 截断保存诊断文本
```

主线程通过：

```python
self._messages.get(timeout=self.config.timeout)
```

等待响应，从而获得明确的请求超时。stdout 出现非法 JSON、Server 断开或超时，都会变成可读错误返回 Agent。

## 12. Transport 如何分发

`MCPManager.connect()` 根据配置创建不同客户端：

```python
if config.transport == "streamable_http":
    client = StreamableHTTPMCPClient(config, workspace)
else:
    client = StdioMCPClient(config, workspace)
```

两种 Client 都提供 `connect()`、`call_tool()` 和 `close()`，因此上层的工具发现、命名、权限与 Tool Loop 完全复用。这是一个轻量的 Strategy 模式。

## 13. Streamable HTTP 请求流程

Streamable HTTP 不启动 Server，而是连接已经运行的单一 MCP endpoint。每条 JSON-RPC 消息使用独立 HTTP POST，并发送：

```text
Accept: application/json, text/event-stream
Content-Type: application/json
Mcp-Session-Id: <初始化返回值>
MCP-Protocol-Version: <协商版本>
```

初始化请求没有 Session ID；`InitializeResult` 返回后保存协商的协议版本，再发送 `notifications/initialized` 和 `tools/list`。

## 14. 为什么同时支持 JSON 和 SSE

Streamable HTTP Server 对请求可以返回：

- `application/json`：单个 JSON-RPC 响应；
- `text/event-stream`：在 SSE 流中发送通知、请求，最终发送对应响应。

实现会逐行解析 SSE 的 `data:` 字段，忽略当前不处理的通知，直到找到相同 request ID 的响应后主动结束读取。如果流结束仍没有匹配响应，则返回明确错误。

## 15. HTTP Session 与关闭

Server 可以在初始化响应中返回 `Mcp-Session-Id`。ZCLI 校验其可见 ASCII 范围，并在所有后续 HTTP 请求中携带。若有 Session 的请求返回 404，会重新初始化会话并重试原请求一次。

关闭时，stdio 关闭 stdin 并逐级 terminate/kill；Streamable HTTP 在存在 Session ID 时发送 DELETE，然后关闭 HTTP Client。两种 transport 的资源生命周期由同一个 `MCPManager.close()` 管理。

---

# 工具发现与动态注册

## 16. 工具名称规范化

不同 Server 可能都有 `search`、`get` 或 `deploy` 工具，因此不能直接把远端名称暴露给模型。

命名规则是：

```text
mcp__<normalized_server>__<normalized_tool>
```

例如：

```text
Server: test.docs
Tool:   echo.text
结果:   mcp__test_docs__echo_text
```

规范化规则会把不属于 `[A-Za-z0-9_-]` 的字符替换为 `_`。注册前还会检查冲突，避免 `a.b` 和 `a/b` 最终都变成 `a_b`。

## 17. 远端 Schema 如何进入模型工具池

`tools/list` 返回的工具包含：

- `name`；
- `description`；
- `inputSchema`；
- `annotations`。

`MCPManager.connect()` 把它转换成 `MCPTool`，然后 `MCPTool.definition()` 转成 Anthropic-compatible 工具定义：

```python
{
    "name": "mcp__echo__echo",
    "description": "Return the supplied text. (read-only)",
    "input_schema": remote_input_schema,
}
```

远端 `inputSchema` 原样交给模型，因此 ZCLI 不需要预先知道参数结构。

## 18. 动态工具池为什么能立即生效

`ToolRegistry.definitions` 是属性，不是启动时缓存的固定列表：

```python
return builtins + self.mcp.definitions()
```

Agent 每次进入 LLM 调用都会重新读取：

```python
client.messages.create(
    tools=self.tools.definitions,
    ...
)
```

所以一次循环中发生下面的变化：

```text
第 N 次 LLM 请求：只有 connect_mcp
模型调用 connect_mcp，Manager 注册远端工具
第 N+1 次 LLM 请求：definitions 重新计算，新工具已经出现
```

不需要重启 Agent，也不需要修改核心循环。这是动态工具池与现有 Tool Loop 能自然组合的原因。

## 19. 工具调用路由

内置工具从 `handlers` 字典取得处理函数；MCP 工具则通过 Manager 路由：

```python
handler = self.handlers.get(name)
if handler:
    return handler(**arguments)
return self.mcp.call(name, arguments)
```

Manager 根据公共名称找到：

```text
MCPTool
  ├─ server_name → 选择 MCP Client
  └─ remote_name → tools/call 的真实 name
```

最终发送：

```python
{
    "name": tool.remote_name,
    "arguments": arguments,
}
```

---

# 结果、权限和生命周期

## 20. MCP 结果如何进入 Agent Loop

`tools/call` 可能返回多个 content block。当前实现：

- `type=text`：取出文本；
- 其他结构化 block：序列化为 JSON；
- 多个 block：用换行连接；
- `isError=true`：添加 `MCP error:` 前缀；
- 协议异常：包装为 `MCP call error`。

转换后仍是普通字符串 tool result，因此可以复用现有机制：

```text
MCP 输出
  → PostToolUse Hook
  → 终端工具轨迹
  → 大结果落盘/压缩
  → Session 持久化
  → 下一轮模型输入
```

MCP 没有绕开 Agent Harness，而是作为普通工具来源接入同一条执行链。

## 21. 两层权限控制

### 连接权限

stdio 配置中的 `command` 会执行本地程序，Streamable HTTP 配置会访问外部 URL，所以调用 `connect_mcp` 必须得到用户批准：

```text
Potentially sensitive action:
  connect to MCP server 'echo'
Allow? [y/N]
```

非交互模式默认拒绝，遵循 fail-closed。

### 工具权限

Server 可以声明：

```json
{"annotations": {"destructiveHint": true}}
```

ZCLI 对这样的工具每次调用都要求批准；`readOnlyHint` 和 `destructiveHint` 也会显示在工具描述中，帮助模型和用户理解风险。

权限检查仍由默认 `PreToolUse` Hook 统一执行，扩展 Hook 不能绕过它。

## 22. 连接生命周期

`MCPManager` 持有所有已连接 Client：

```python
self.clients: dict[str, StdioMCPClient]
```

CLI 用 `try/finally` 保证退出时调用：

```text
agent.close()
  → MCPManager.close()
  → StdioMCPClient.close()
```

stdio 关闭顺序：

1. 关闭 stdin，给正常 Server 一个 EOF；
2. 等待 2 秒；
3. 未退出则 `terminate()`；
4. 再未退出则 `kill()`。

这是资源管理中的渐进式升级，既允许 Server 正常清理，也保证 ZCLI 不会长期残留子进程。

HTTP Server 已经独立运行，ZCLI 不终止服务进程；如果 Server 建立了 MCP Session，只发送 DELETE 结束自己的逻辑会话。

## 23. System Prompt 与 CLI 状态

System Prompt 会动态加入：

```text
MCP servers:
- echo: available
- docs: connected, 2 tools
```

模型因此知道哪些 Server 可以连接、哪些已经可用。

用户也可以通过 `/mcp` 查看同样状态和配置诊断。这个命令不调用模型，也不会启动 Server。

---

# 测试与设计权衡

## 24. 如何测试真实 MCP，而不是只测 mock

测试同时使用真实 Python 子进程和独立 `ThreadingHTTPServer` fixture：前者验证 stdio，后者模拟已经运行的外部 MCP endpoint。

主要覆盖：

1. `initialize → initialized → tools/list → tools/call` 完整链路；
2. 远端工具 Schema 和 annotations 转换；
3. `mcp__server__tool` 名称规范化；
4. 规范化名称冲突；
5. 配置覆盖、环境变量缺失和 cwd 逃逸；
6. 连接与 destructive 工具权限；
7. Agent 首次请求没有远端工具，连接后的下一次请求出现；
8. 调用结果进入 Session；
9. Manager 关闭后 Client 和工具注册被清空。
10. HTTP JSON 发现、SSE 调用、Session ID、协议版本和 DELETE。

这里最重要的是第 7 项，它验证的不是单独函数，而是“连接后动态改变下一轮工具池”的架构行为。

## 25. 为什么没有直接依赖 MCP SDK

这一版没有引入 MCP SDK，而是实现了 stdio 和 Streamable HTTP 的最小 Tools 子集，原因是：

- 可以把 initialize、list、call、Session 和 JSON/SSE 关联机制讲清楚；
- 避免为只使用 Tools 引入更大的运行时依赖；
- 更容易控制错误包装、权限和 ZCLI 工具池集成。

代价也很明确：协议面仍然较窄，随着 OAuth、Resources、GET 通知流和断点续传加入，自研协议层的维护成本会快速上升。生产化下一阶段更适合迁移到官方 SDK，并保留现有 `MCPManager` 作为适配层。

## 26. 当前限制

目前实现的是“真实 MCP 工具桥接”，不是完整 MCP Runtime：

1. 支持 stdio 和 Streamable HTTP，但不支持旧版 HTTP+SSE 或 WebSocket；
2. 不支持 OAuth 和令牌刷新；
3. 不支持 Resources、Prompts；
4. SSE POST 中可跳过通知，但不处理 Server 发起的请求，也没有独立 GET 通知流；
5. 不支持 Last-Event-ID 断点续传；
6. 不订阅工具列表变化；
7. 仅对 Session 404 重建一次，不提供通用断线自动重连；
8. 同一 Client 的请求由锁串行执行；
9. annotations 当前主要处理 read-only 和 destructive 提示。

面试时应该主动说明这些边界。把“完成核心链路”和“支持完整规范”区分开，比笼统声称完整支持 MCP 更可信。

## 27. 可以怎样继续演进

建议按这个顺序扩展：

1. 使用官方 SDK 替换手写协议层；
2. 增加 OAuth 与安全凭据存储；
3. 增加 GET 通知流、断点续传、指数退避和自动重连；
4. 用 `request_id → Future` 支持同 Server 并发调用；
5. 支持 tools list changed 通知和动态注销；
6. 接入 OAuth、凭据安全存储和刷新；
7. 支持 Resources、Prompts 和 Server notifications；
8. 进一步细化 MCP annotations 与权限策略。

---

# 面试常见追问

## 28. 为什么不在启动时自动连接所有 MCP Server

因为连接意味着执行本地命令或访问外部服务，可能有安全风险和资源成本。按需连接让用户先审批，也避免启动大量当前任务根本用不到的 Server。

## 29. 为什么要使用 `mcp__server__tool` 命名

为了避免不同 Server 的工具重名，同时让日志、权限提示和 Session 能明确追踪调用来源。名称还会规范化并检查冲突。

## 30. 为什么连接后模型下一轮才能使用新工具

当前 LLM 请求的工具定义在请求发出时已经固定。`connect_mcp` 是这次请求返回的工具调用，只有执行完发现后，下一次 `messages.create()` 才能携带新的 definitions。

## 31. MCP 工具会不会绕过原来的权限和 Hook

不会。它只改变工具来源，执行仍经过 `PreToolUse → ToolRegistry.execute → PostToolUse`，所以审批、输出改写、大结果落盘和 Session 保存都能复用。

## 32. 如果 Server 输出非法 JSON 怎么办

stdout 读取线程捕获 JSON 解析异常并放入 Queue，等待请求的一方把它转换成 `invalid MCP message`。连接阶段失败还会关闭子进程。

## 33. 如果 Server 一直不响应怎么办

主线程通过 Queue 的超时等待，不会无限阻塞。超时转换成 `TimeoutError`，再由 Manager 包装成 MCP 连接或调用错误。

## 34. 为什么 stderr 不直接打印

stdio MCP 的 stdout 是协议通道，stderr 是诊断通道。单独读取能防止管道堵塞，也避免 Server 日志混入 JSON-RPC；断开时只截取有限诊断内容返回。

## 35. 配置文件是否可信

不能完全信任，因为 `command` 会被执行。所以连接必须审批，`cwd` 不能逃逸工作区，密钥推荐通过环境变量注入，并且配置应当像脚本一样接受代码审查。

## 36. 为什么每个 Client 使用锁

当前实现是同步请求模型，一个请求发送后等待一个对应响应。锁保证不会有两个线程同时消费同一个响应 Queue。它牺牲并发换取第一版协议状态的简单和可靠。

## 37. MCP 与 Skill 有什么区别

- Skill 提供“怎么做”的指令和流程知识；
- MCP 提供“能做什么”的外部可执行能力。

Skill 可能告诉模型如何执行代码审查，MCP 则可能提供查询 Jira 或触发部署的真实工具。二者可以组合：先加载发布 Skill，再调用部署 MCP。

---

# 口述版本

## 38. 一分钟讲解

> 我在 ZCLI 中实现了 stdio 和 Streamable HTTP 两种 MCP transport。核心思路是后绑定工具：用户批准 connect_mcp 后，Manager 根据配置选择启动本地子进程，或者连接已经运行的 HTTP endpoint；客户端完成 initialize、initialized 和 tools/list，再把远端工具转换为 mcp__server__tool 合入动态工具池。HTTP 同时支持 JSON 和 SSE 响应，保存 Session ID 与协商协议版本，关闭时发送 DELETE。MCP 调用仍复用原有 Hook、权限、压缩和 Session 链路。目前完成的是 Tools 核心链路，OAuth、Resources 和 GET 通知流仍是明确边界。

## 39. 两分钟讲解

> 这个功能解决的是 Agent 外部能力扩展问题。以前接 Jira、知识库或部署平台都要在 Agent 里手写工具，MCP 则把发现和调用标准化。
>
> 实现分为三层。第一层是配置层，按用户级、项目级和项目本地三级合并 mcp.json，校验 stdio 的 command、env、cwd，以及 HTTP 的 URL、Headers 和超时，密钥通过环境变量模板引用。第二层是 transport 层，StdioMCPClient 用 subprocess 和逐行 JSON-RPC；StreamableHTTPMCPClient 对单一 endpoint 发送 POST，同时解析 JSON 和 SSE，保存初始化返回的 Session ID，并在后续请求发送协议版本。两种 Client 都提供 connect、call_tool、close，由 Manager 按 transport 选择。第三层是 Agent 集成层，MCPManager 把远端工具包装成 MCPTool，并用 mcp__server__tool 解决重名。ToolRegistry 每次 LLM 请求都动态拼接 definitions，所以 connect_mcp 完成后的下一轮请求就会出现新工具。
>
> MCP 工具没有走旁路，它仍经过 PreToolUse、权限、PostToolUse、大输出落盘和 Session 持久化。连接本身会执行本地命令，所以必须审批；Server 标记 destructiveHint 的工具也必须逐次审批。CLI 退出时会关闭 stdin，并逐级 terminate、kill 回收子进程。
>
> 测试不是只 mock 一个函数，而是同时启动本地 MCP 子进程和独立 HTTP fixture，验证完整握手、JSON/SSE、Session Header、发现、动态工具刷新、权限和关闭。如果继续生产化，我会用官方 SDK 扩展 OAuth、GET 通知流、断点续传、自动重连和并发请求。

## 40. 最后一句总结

MCP 实现的关键不只是“能调用外部工具”，而是把外部能力以受控、可发现、可动态注册的方式接入同一套 Agent Harness。
