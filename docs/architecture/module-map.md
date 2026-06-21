# 模块职责表

| 模块 | 文件 | 职责 | 关键类/函数 |
|------|------|------|-------------|
| CLI 入口 | `zcli/cli.py` | 参数解析、会话选择、REPL 循环 | `main()`, `build_parser()` |
| `__main__` | `zcli/__main__.py` | `python -m zcli` 支持 | 调用 `main()` |
| 包标识 | `zcli/__init__.py` | 版本号 | `__version__ = "0.1.0"` |
| Agent 核心 | `zcli/agent.py` | LLM 编排、工具循环、记忆抽取 | `Agent.run_turn()` |
| 上下文管理 | `zcli/context.py` | 分层压缩、大结果与 transcript 持久化 | `ContextManager` |
| 错误恢复 | `zcli/recovery.py` | 429/529 重试、fallback、超限识别 | `RecoveryState`, `with_retry()` |
| Hook 系统 | `zcli/hooks.py` | 生命周期扩展、权限 Hook、阻断与续跑 | `HookManager`, `HookResult` |
| 任务图 | `zcli/tasks.py` | 持久任务、依赖、认领与完成 | `Task`, `TaskStore` |
| 配置 | `zcli/config.py` | 环境变量 / .env 加载 | `Settings` (frozen dataclass) |
| 会话存储 | `zcli/session.py` | JSON 持久化、CRUD、原子写 | `Session`, `SessionStore` |
| 长期记忆 | `zcli/memory.py` | Markdown+YAML 文件存储、索引、检索 | `MemoryStore` |
| Skill 注册 | `zcli/skills.py` | 扫描、Catalog、Frontmatter、按需加载 | `SkillRegistry`, `Skill` |
| MCP 客户端 | `zcli/mcp.py` | 配置合并、stdio/HTTP transport、发现、调用、会话关闭 | `MCPManager`, `StdioMCPClient`, `StreamableHTTPMCPClient` |
| Subagent | `zcli/subagents.py` | 隔离工具循环、工具白名单、Task/Worktree 上下文 | `SubagentRunner` |
| Team | `zcli/teams.py` | Teammate 线程、文件邮箱、计划/关闭协议、自动认领 | `TeamManager`, `MessageBus` |
| Worktree | `zcli/worktrees.py` | Git 隔离目录、任务绑定、安全移除、事件日志 | `WorktreeManager` |
| 工具注册 | `zcli/tools.py` | 27 个内置工具与 MCP 动态工具的定义、权限和分发 | `ToolRegistry` |
| 权限策略 | `zcli/permissions.py` | 路径逃逸检测、危险命令拒绝、交互审批 | `PermissionPolicy` |
| 终端展示 | `zcli/display.py` | ANSI 颜色、LOGO、启动 banner | `show_banner()` |

## 依赖关系

```
cli.py ──→ agent.py ──→ session.py
           │              memory.py
           │              tools.py ──→ permissions.py
           ├── context.py
           ├── recovery.py
           ├── hooks.py
           ├── tasks.py
           ├── skills.py
           ├── mcp.py
           ├── subagents.py ──→ teams.py
           ├── worktrees.py ──→ tasks.py
           └── config.py
           └── display.py
```

`config.py` 被几乎所有模块依赖（通过 `Settings` 注入）。`tools.py` 依赖 `permissions.py` 做安全检查。
