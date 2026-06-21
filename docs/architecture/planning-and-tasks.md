# TodoWrite 与 Task Graph

ZCLI 参考 `learn-claude-code` s05 和 s12，同时保留两层规划系统。它们不是重复功能，而是服务于不同时间尺度。

| | TodoWrite | Task Graph |
|---|---|---|
| 用途 | 当前工作的步骤清单 | 跨 Session 的持久任务 DAG |
| 存储 | Session JSON 的 `todos` | `.zcli/tasks/task_*.json` |
| 依赖 | 无 | `blockedBy` |
| 认领 | 无 | `owner` + `claim_task` |
| 状态 | pending / in_progress / completed | pending / in_progress / completed |

## TodoWrite

模型通过 `todo_write` 一次提交完整清单：

```json
{
  "todos": [
    {"content": "检查现有代码", "status": "completed"},
    {"content": "实现功能", "status": "in_progress"},
    {"content": "运行测试", "status": "pending"}
  ]
}
```

每次更新都会替换当前 Session 的完整列表并重置提醒计数。Todo 随 Session 原子保存，重启相同 Session 后仍可恢复；新 Session 有独立清单。

连续执行三个非 `todo_write` 工具后，Agent 在下一次模型调用前注入：

```xml
<reminder>Update your todos.</reminder>
```

这是教学版 s05 的 nag reminder。提醒计数同样保存在 Session 中。

## Task Graph

持久任务状态机：

```text
pending ──claim_task──> in_progress ──complete_task──> completed
```

工具集合：

- `create_task(subject, description, blockedBy)`
- `list_tasks()`
- `get_task(task_id)`
- `claim_task(task_id, owner)`
- `complete_task(task_id)`

`claim_task` 只有在所有 `blockedBy` 任务存在且为 `completed` 时才能成功。完成上游任务后，返回值会列出本次新解锁的直接下游任务。

每个任务独立保存为 JSON，并通过临时文件加 `os.replace()` 原子更新。重新启动 Agent 或切换 Session 不会丢失 Task Graph。

Task 的可选 `worktree` 字段可以绑定 ZCLI 管理的 Git Worktree。空闲 Teammate 会原子认领依赖已满足的任务；Subagent 随后以成员名作为 owner，并在绑定的隔离目录中执行文件与 Shell 工具。

## System Prompt 注入

每次模型调用前，ZCLI 会注入：

- 当前 Session Todo 列表；
- 持久任务摘要（最多 4,000 字符）。

因此模型在上下文压缩或进程重启后仍能看到计划状态。CLI 也提供只读命令：

- `/todos`：显示当前 Session Todo；
- `/tasks`：显示持久 Task Graph。

## 当前边界

- Task Graph 沿用 s12 教学版，不做依赖环检测；
- 进程内使用线程锁和原子写，但没有跨进程文件锁；
- 暂无 release/unassign，任务不能从 `in_progress` 回退为 `pending`；
- `owner` 可记录 Lead、Subagent 或 Teammate；空闲成员支持自动认领；
- 尚未扩展 `TaskCreated` / `TaskCompleted` Hook 事件。
