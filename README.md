# ZCLI

ZCLI 是一个从 `learn-claude-code/s20` 蓝图迁移出的个人 Coding Agent 初版。它没有直接复制 2100 行单文件，而是先完成最关键的两层持久化：

- Session：每次用户输入、模型响应和工具结果后原子写盘，可跨进程继续对话。
- Memory：独立 Markdown 记忆、`MEMORY.md` 索引、相关记忆注入、显式 `remember` 工具和每轮自动提取。

当前还包含受工作区约束的 `bash/read/write/edit/glob` 工具、基础权限策略和上下文压缩。Task、Team、Cron、Worktree 和真实 MCP 将作为后续可选模块迁移。

## 安装

```powershell
cd C:\02-study\MyProjects\ZCLI
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
```

编辑 `.env`，配置 `ANTHROPIC_API_KEY` 和 `MODEL_ID`。

## 使用

```powershell
# 当前目录作为 Agent 工作区
zcli

# 指定工作区和会话
zcli --workspace C:\02-study\MyProjects\my-project --session my-project

# 查看会话
zcli --list-sessions
```

CLI 内置命令：

- `/memory`：查看长期记忆索引
- `/sessions`：查看保存的会话
- `/exit`：退出

运行数据默认保存在工作区的 `.zcli/`，也可以通过 `ZCLI_DATA_DIR` 改为统一的个人数据目录。

## 目录

```text
zcli/
  agent.py        Agent Loop、压缩和自动记忆提取
  config.py       环境配置
  memory.py       长期记忆
  session.py      会话持久化
  permissions.py 权限策略
  tools.py        工具注册与执行
  cli.py          命令行入口
```

## 当前边界

这是个人 Agent 的最小可靠内核，不是完整 Claude Code 克隆：

- Shell 仍通过系统 shell 执行，危险操作依赖 deny/ask 策略；请不要把它暴露为无人值守的公共服务。
- 自动记忆提取会多产生一次小模型调用。
- 尚未迁移 s20 的 Team、Cron、Task Graph、Worktree 和 Mock MCP。

