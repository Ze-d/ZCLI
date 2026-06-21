# ZCLI

[![CI](https://github.com/Ze-d/ZCLI/actions/workflows/ci.yml/badge.svg)](https://github.com/Ze-d/ZCLI/actions/workflows/ci.yml)

> 你的终端个人编程 Agent

ZCLI 是一个轻量级 CLI 编程 Agent，支持多轮对话、文件操作、Bash 执行、生命周期 Hooks、TodoWrite、持久化 Task Graph、长期记忆、会话持久化、分层上下文压缩和 API 错误恢复。兼容 Anthropic / DeepSeek / MiniMax / GLM / Kimi 等厂商。

上下文处理参考 `learn-claude-code` 的 s08、s11 和 s20：大工具结果先落盘，再裁剪旧消息和旧工具结果，仍超限时保存完整 transcript 并生成摘要。API 调用支持 429/529 指数退避、529 fallback model、`max_tokens` 扩容与续写，以及 prompt-too-long 后的 reactive compact。

## 快速安装

### pipx (推荐，环境隔离)

```bash
# 从 GitHub 安装
pipx install git+https://github.com/Ze-d/ZCLI.git

# 或从本地安装
pipx install /path/to/ZCLI
```

### pip (全局安装)

```bash
# 从 GitHub
pip install git+https://github.com/Ze-d/ZCLI.git

# 从本地构建
pip install /path/to/ZCLI

# 未来从 PyPI 安装
pip install zcli-agent
```

### 开发安装

```bash
git clone https://github.com/Ze-d/ZCLI.git
cd ZCLI
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -e ".[dev]"
```

## 配置

```bash
# 复制配置模板
cp .env.example .env
```

编辑 `.env`，填入你的 API key：

```ini
ANTHROPIC_API_KEY=sk-ant-xxx
MODEL_ID=claude-sonnet-4-6

# 可选：使用其他厂商
# ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
# MODEL_ID=deepseek-chat
```

| 变量 | 必需 | 默认 | 说明 |
|------|------|------|------|
| `ANTHROPIC_API_KEY` | 是 | — | API 密钥 |
| `MODEL_ID` | 否 | `claude-sonnet-4-6` | 模型 ID |
| `ANTHROPIC_BASE_URL` | 否 | `https://api.anthropic.com` | API 端点 |
| `ZCLI_WORKSPACE` | 否 | 当前目录 | 工作区 |
| `ZCLI_DATA_DIR` | 否 | `<workspace>/.zcli` | 数据目录 |
| `ZCLI_CONTEXT_LIMIT` | 否 | `50000` | 触发完整摘要压缩的估算 token 阈值 |
| `FALLBACK_MODEL_ID` | 否 | — | 连续 529 后切换的备用模型 |
| `ZCLI_MAX_TOKENS` | 否 | `8000` | 常规模型输出上限 |
| `ZCLI_ESCALATED_MAX_TOKENS` | 否 | `16000` | 首次输出截断后的重试上限 |
| `ZCLI_MAX_RETRIES` | 否 | `3` | 429/529 最大调用次数 |
| `ZCLI_MAX_RECOVERY_RETRIES` | 否 | `2` | 扩容后仍截断时的续写次数 |

## 使用

```bash
# 启动 Agent
zcli

# 指定工作区
zcli --workspace ~/my-project

# 多会话管理
zcli --session my-work
zcli --new --session clean-start

# 查看保存的会话
zcli --list-sessions
```

REPL 内置命令：

| 命令 | 效果 |
|------|------|
| `/exit` `/quit` | 退出 |
| `/memory` | 查看长期记忆 |
| `/sessions` | 列出已保存会话 |
| `/todos` | 查看当前 Session 的 Todo 清单 |
| `/tasks` | 查看持久化 Task Graph |

## 构建 & 发布

### 自动发布（GitHub Actions）

推送 `v*` tag 自动触发构建 → PyPI + GitHub Release：

```bash
git tag v0.2.0
git push origin v0.2.0
```

首次使用需在 PyPI 配置 [Trusted Publisher](https://docs.pypi.org/trusted-publishers/)（OIDC），指向 GitHub 仓库 `Ze-d/ZCLI`。

### 手动构建

```bash
pip install build twine
python -m build --no-isolation  # Windows / --no-isolation 可省略

# 产物在 dist/
# zcli_agent-0.1.0-py3-none-any.whl
# zcli_agent-0.1.0.tar.gz

twine upload dist/*
```

## 文档

详细文档见 [docs/](docs/):
- [架构总览](docs/architecture/overview.md)
- [TodoWrite 与 Task Graph](docs/architecture/planning-and-tasks.md)
- [模块职责](docs/architecture/module-map.md)
- [环境变量](docs/development/env-vars.md)
- [测试策略](docs/testing/test-strategy.md)

## 技术栈

Python 3.11+ · anthropic · python-dotenv · pyyaml · pytest

## License

MIT
