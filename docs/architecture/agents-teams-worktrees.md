# Subagent、Team 与 Worktree

ZCLI 参考 `learn-claude-code` s15-s18，将委派能力分成三层，而不是把所有并发工作都叫作“子 Agent”。

## 三层模型

| 层级 | 生命周期 | 上下文 | 返回方式 | 适用场景 |
|---|---|---|---|---|
| Subagent | 同步、一次性 | 独立 messages | 结果直接作为 tool_result | 调研、审查、单个有界任务 |
| Teammate | 后台线程、命名成员 | 每个工作项独立 | 文件邮箱异步通知 Lead | 多角色协作、计划、自动认领任务 |
| Worktree | 显式创建到保留/移除 | 独立 Git 目录与分支 | Task 的 `worktree` 字段绑定 | 并行写代码，避免文件冲突 |

## Subagent

`run_subagent(name, role, prompt, task_id?, worktree?)` 创建隔离的工具循环。它不会继承 Lead 的 Session 历史，只接收委派 Prompt 和可选 Task JSON。

工具采用白名单：文件读写、glob、非交互安全 Bash，以及 Task 的查看、认领和完成。Subagent 看不到 `run_subagent`、Team、Worktree、Memory、Skill 加载或 MCP 连接工具，因此不能递归创建 Agent，也不能扩大授权范围。

指定 Task 时会以 Subagent 名称认领；Task 已绑定 Worktree 时，文件和 Shell 工具自动以该 Worktree 为工作区。

## Team

`TeamManager` 用 daemon 线程运行命名 Teammate，并使用 `.zcli/team-mailboxes/<name>.jsonl` 通信。邮箱读取是消费语义；文件操作在进程内锁保护下完成。

Lead 工具：

- `spawn_teammate`、`list_teammates`
- `send_message`、`check_inbox`
- `request_plan`、`review_plan`
- `request_shutdown`

Teammate 完成初始工作后进入 IDLE：先处理普通消息、计划和关闭协议。默认 `autoClaim=false`，一次性 reviewer 不会误领无关的遗留 Task；只有创建时显式设置 `autoClaim=true` 的 worker，才会在没有消息时扫描 Task Graph，原子认领第一个依赖已满足的 pending Task。默认空闲 60 秒后结束。Teammate 可以给 Lead 或其他成员发消息，但不能再生成 Teammate。

Lead 每轮开始时自动消费自己的 Inbox，并以 `<team_inbox>` 注入当前用户消息；也可以显式调用 `check_inbox` 或使用 `/team`。

## Worktree

Worktree 由 `WorktreeManager` 统一管理，记录放在 `.zcli/worktrees.json`，目录默认位于 `.zcli/worktrees/<name>`，分支名为 `zcli/<name>`。

```text
create_worktree(name, task_id?)
  → 校验名称和 Task
  → git rev-parse HEAD
  → git worktree add -b zcli/<name>
  → 保存 base SHA 和注册表
  → 可选绑定 Task
```

`remove_worktree` 默认检查未提交文件和相对 base SHA 的新增提交，存在任何工作时拒绝删除。`discard_changes=true` 需要权限审批；移除成功后清理分支、注册表和 Task 绑定。`keep_worktree` 只记录保留事件，不修改任务状态。

## 状态关系

```text
TaskStore                         WorktreeManager
task.worktree ─────────────────> managed path / branch
     │
     └─ teammate auto-claim
             │
             └─ SubagentRunner(workspace=worktree path)
```

Task 状态与 Worktree 生命周期解耦：创建 Worktree 不会自动认领 Task；移除 Worktree 不会自动完成 Task。

## 安全边界

- Agent/Worktree 名称使用白名单，拒绝路径穿越。
- Worktree 只能操作注册表中的受管目录。
- Subagent 使用非交互权限策略，需要审批的 Bash 命令会直接拒绝。
- Teammate 没有递归生成 Agent 或移除 Worktree 的工具。
- Worktree 删除必须经过 Lead 的 PreToolUse 权限检查。
- Team 是单进程线程模型；TaskStore 只有进程内锁，不支持多个 ZCLI 进程并发抢占。
- Bash 仍是系统 Shell，不是容器级沙箱；非交互策略只会拒绝已知危险/需审批命令。

## 当前边界

- Teammate 运行在线程中，不是独立进程或远程 worker；无法强制中断正在进行的 Provider HTTP 请求。
- 消息与 Task 持久化，但 Teammate 线程本身不会跨 ZCLI 进程恢复。
- Worktree 不自动 merge、push 或创建 PR，保留后由用户审查。
- 同一工作区的并行非 Worktree 写操作仍可能冲突。
