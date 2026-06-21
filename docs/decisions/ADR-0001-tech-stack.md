# ADR-0001: 技术栈选型

**日期**: 2026-06  
**状态**: Accepted

## 上下文

需要构建一个个人 CLI 编码 Agent，要求：轻量、持久化、多厂商 LLM 兼容、终端原生运行。

## 决策

| 决策点 | 选择 | 备选 | 理由 |
|--------|------|------|------|
| LLM SDK | `anthropic` | openai, langchain | Anthropic-compatible API 被多家厂商支持；SDK 原生 tool-use |
| 配置管理 | `python-dotenv` + dataclass | pydantic-settings, argparse 内置 | 零依赖负担，够用 |
| 会话持久化 | 手写 JSON 原子写 | SQLite, pickle | 人可读、可手修、可 git diff |
| 记忆存储 | Markdown + YAML frontmatter | SQLite, Chroma | 人可读，兼容 Obsidian，无需向量数据库 |
| 包管理 | setuptools + pyproject.toml | Poetry, Hatch | 标准工具链，无额外学习成本 |
| 测试 | pytest | unittest | 生态标准 |
| CLI 框架 | argparse | click, typer | 标准库，依赖最小化 |
| 终端着色 | ANSI 转义序列 | rich, colorama | 零依赖，场景简单不复杂 |
| 安全沙箱 | 自写 PermissionPolicy | 无 | 路径 jail + 命令黑名单 + 交互审批 |

## 后果

- **正面**: 总依赖仅 3 个（anthropic, python-dotenv, pyyaml），安装快速，审计面小
- **负面**: 无流式输出、无多 Agent 编排；MCP 已覆盖 stdio/Streamable HTTP Tools，但尚非完整 runtime
- **风险**: Anthropic SDK API 变更需要跟进
