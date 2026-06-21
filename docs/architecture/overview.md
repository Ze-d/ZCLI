# 整体架构

## 分层设计

```
┌─────────────────────────────────────────┐
│  CLI 层 (cli.py)                         │
│  argparse → Settings → Agent → REPL      │
├─────────────────────────────────────────┤
│  Agent 层 (agent.py)                     │
│  事件循环 · 工具编排 · Todo · 记忆抽取     │
├─────────────────────────────────────────┤
│  Harness 层 (hooks.py / context.py)      │
│  生命周期 Hook · 分层压缩 · API 错误恢复   │
├─────────────────────────────────────────┤
│  存储 & 工具层                            │
│  session.py  memory.py  tools.py  mcp.py  │
│  permissions.py  config.py  display.py   │
└─────────────────────────────────────────┘
```

## 三阶段流水线

每次 `run_turn()` 调用经历三个阶段：

1. **Pre-turn** — 注入相关记忆到用户消息，追加到会话并持久化
2. **Tool loop** — 循环调用 LLM，执行工具，收集结果，直到 LLM 不再请求工具
3. **Post-turn** — 自动抽取长期记忆（异步容错，失败不影响主流程）

## 核心模式

- **REPL**: 单线程 read-eval-print 循环，支持 `/exit` `/memory` `/sessions` `/todos` `/tasks` `/skills` `/mcp`
- **Tool-use loop**: Agent 在单轮中可多次调用工具，直到 LLM 产出纯文本回复
- **Context compaction**: 大结果落盘 → 历史裁剪 → 旧工具结果压缩；仍超限才调用 LLM 摘要
- **Memory extraction**: 每轮结束后 LLM 自动抽取偏好和项目事实持久化
- **Permission gate**: 所有 bash 命令经过安全策略检查（硬拒绝 + 路径 jail）
- **Lifecycle hooks**: 输入、工具前后和停止阶段通过可注册 Hook 扩展，权限由默认 PreToolUse Hook 执行
- **Two-level planning**: Session Todo 管当前步骤；持久 Task Graph 管依赖、认领和跨 Session 进度
- **Two-level skill loading**: System Prompt 只放 Catalog，完整 SKILL.md 由 `load_skill` 按需加载
- **Late-bound MCP tools**: stdio 或 Streamable HTTP 连接后发现工具，以命名空间合入下一轮动态工具池
- **Delegation layers**: 一次性 Subagent、后台 Teammate、Task 自动认领与文件邮箱
- **Git isolation**: Task 可绑定独立 Worktree，删除前检查工作状态

分层策略、阈值和协议不变量见 [context-compaction.md](context-compaction.md)。
Hook 事件和扩展约定见 [hooks.md](hooks.md)。
两层规划模型见 [planning-and-tasks.md](planning-and-tasks.md)。
Skill 加载模型见 [skills.md](skills.md)。

MCP 的多 transport 连接、动态工具池与权限模型见 [mcp.md](mcp.md)。
Agent 委派与 Git 隔离见 [agents-teams-worktrees.md](agents-teams-worktrees.md)。
