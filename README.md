# ZCLI

[![CI](https://github.com/Ze-d/ZCLI/actions/workflows/ci.yml/badge.svg)](https://github.com/Ze-d/ZCLI/actions/workflows/ci.yml)

> 你的终端个人编程 Agent

ZCLI 是一个轻量级 CLI 编程 Agent，支持多轮对话、文件操作、Bash 执行、长期记忆和会话持久化。兼容 Anthropic / DeepSeek / MiniMax / GLM / Kimi 等厂商。

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
- [模块职责](docs/architecture/module-map.md)
- [环境变量](docs/development/env-vars.md)
- [测试策略](docs/testing/test-strategy.md)

## 技术栈

Python 3.11+ · anthropic · python-dotenv · pyyaml · pytest

## License

MIT
