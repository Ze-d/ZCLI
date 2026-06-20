# ZCLI — Personal Coding Agent

ZCLI 是一个轻量级个人编程 Agent，运行在终端中，具备多轮对话、工具调用、长期记忆和会话持久化能力。兼容 Anthropic / DeepSeek / MiniMax / GLM / Kimi 等厂商的 Anthropic-compatible API。

## 快速导航

| 想了解 | 去看 |
|--------|------|
| 整体架构 | [architecture/overview.md](architecture/overview.md) |
| 模块与职责 | [architecture/module-map.md](architecture/module-map.md) |
| 数据流 & 状态流转 | [architecture/data-flow.md](architecture/data-flow.md) |
| 环境搭建 | [development/setup.md](development/setup.md) |
| 常用命令 | [development/commands.md](development/commands.md) |
| 环境变量 | [development/env-vars.md](development/env-vars.md) |
| 测试策略 | [testing/test-strategy.md](testing/test-strategy.md) |
| 技术选型 | [decisions/ADR-0001-tech-stack.md](decisions/ADR-0001-tech-stack.md) |
| 部署 & 排查 | [operations/](operations/) |

## 项目事实

- **语言**: Python 3.11+
- **包管理**: setuptools + pip editable install
- **核心依赖**: `anthropic` `python-dotenv` `pyyaml`
- **入口**: `zcli` 命令 / `python -m zcli`
- **测试**: pytest, 10 个测试覆盖核心路径
