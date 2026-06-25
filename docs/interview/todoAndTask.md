这条描述可以拆成两层：`TodoWrite` 解决“当前对话怎么持续规划”，`Task Graph` 解决“跨会话、可并行、可依赖的 durable work 怎么管理”。

**1. TodoWrite：当前 Session 内的执行清单**

`todo_write` 是一个工具，定义在 [tools.py](C:/02-study/MyProjects/ZCLI/zcli/tools.py:90)。它接收：

```json
[
  {"content": "inspect code", "status": "completed"},
  {"content": "implement fix", "status": "in_progress"}
]
```

真正执行逻辑在 [tools.py](C:/02-study/MyProjects/ZCLI/zcli/tools.py:244)：

- 必须有当前 `session`，否则报错；
- 调用 `_normalize_todos()` 校验格式和状态；
- 写入 `session.todos`；
- 重置 `session.rounds_since_todo = 0`；
- 返回格式化后的 checklist。

`Session` 里确实有这两个字段：[session.py](C:/02-study/MyProjects/ZCLI/zcli/session.py:112)

```python
todos: list[dict] = field(default_factory=list)
rounds_since_todo: int = 0
```

Agent 会把当前 todos 注入 system prompt：[agent.py](C:/02-study/MyProjects/ZCLI/zcli/agent.py:94)

```text
Current session todos:
- [in_progress] write tests
```

还有一个防遗忘机制：如果连续 3 次非 `todo_write` 工具调用后还没更新 todo，Agent 会自动插入提醒：[agent.py](C:/02-study/MyProjects/ZCLI/zcli/agent.py:156)

```text
<reminder>Update your todos.</reminder>
```

面试里可以说：

> TodoWrite 是面向当前 session 的短期计划机制。我把 todo 状态存在 session 里，并在 system prompt 中持续注入，这样模型每轮都能看到当前执行进度。同时用 `rounds_since_todo` 记录连续工具调用次数，超过阈值会提醒模型更新 todo，避免长任务中计划状态漂移。

**2. 持久化 Task Graph：跨会话任务 DAG**

Task Graph 的核心在 [tasks.py](C:/02-study/MyProjects/ZCLI/zcli/tasks.py:34)。

`Task` 数据结构在 [tasks.py](C:/02-study/MyProjects/ZCLI/zcli/tasks.py:22)：

```python
@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: str
    owner: str | None
    blockedBy: list[str]
    created_at: str
    updated_at: str
    worktree: str | None = None
```

它比 Todo 更重，适合长期任务，因为它有：

- `status`：`pending / in_progress / completed`
- `owner`：谁认领了任务
- `blockedBy`：依赖哪些 task 完成
- `worktree`：绑定的隔离工作区
- 文件持久化：每个 task 写成 `.zcli/tasks/task_xxx.json`

创建任务在 [tasks.py](C:/02-study/MyProjects/ZCLI/zcli/tasks.py:51)。它会校验 subject 非空、依赖 id 合法，并去重 `blockedBy`。

工具层暴露了：

- `create_task`：[tools.py](C:/02-study/MyProjects/ZCLI/zcli/tools.py:255)
- `list_tasks`：[tools.py](C:/02-study/MyProjects/ZCLI/zcli/tools.py:259)
- `get_task`：[tools.py](C:/02-study/MyProjects/ZCLI/zcli/tools.py:262)
- `claim_task`：[tools.py](C:/02-study/MyProjects/ZCLI/zcli/tools.py:265)
- `complete_task`：[tools.py](C:/02-study/MyProjects/ZCLI/zcli/tools.py:268)

Agent 也会把 durable task graph 注入 system prompt：[agent.py](C:/02-study/MyProjects/ZCLI/zcli/agent.py:98)

```text
Durable task graph:
task_xxx: API layer [pending] blockedBy=task_yyy
```

面试里可以说：

> Task Graph 是跨 session 的持久任务系统。我用文件系统保存每个 task，并把任务依赖表达成 `blockedBy` 列表，本质上是一个轻量 DAG。Agent 每轮会看到 durable task graph，所以即使会话恢复或者任务被分给 subagent，任务状态也不会丢。

**3. 任务依赖：blockedBy 与 can_start**

依赖判断在 [tasks.py](C:/02-study/MyProjects/ZCLI/zcli/tasks.py:104)：

```python
def can_start(self, task_id: str) -> bool:
    return all(
        dependency exists and dependency.status == "completed"
        for dependency in task.blockedBy
    )
```

也就是说，一个任务只有所有 `blockedBy` 任务都完成后才能开始。

`claim()` 会检查依赖：[tasks.py](C:/02-study/MyProjects/ZCLI/zcli/tasks.py:112)

- 如果不是 `pending`，不能认领；
- 如果已有 owner，不能重复认领；
- 如果依赖未完成，返回 blocked 信息；
- 通过检查后，把任务改成 `in_progress` 并设置 owner。

`complete()` 在 [tasks.py](C:/02-study/MyProjects/ZCLI/zcli/tasks.py:131)：

- 只有 `in_progress` 才能完成；
- 完成后状态变为 `completed`；
- 会扫描哪些 pending 任务因为它完成而被解锁；
- 返回 `Unblocked: ...` 提示。

这对应测试 [test_tasks.py](C:/02-study/MyProjects/ZCLI/tests/test_tasks.py:6)：先创建 `schema`，再创建依赖 `schema` 的 `api`，`api` 一开始不能 claim，等 `schema` completed 后才可以 claim。

**4. 认领：给多 Agent 协作准备的所有权机制**

认领不只是改状态，它解决的是并发协作里的“谁负责这个任务”。

`TaskStore.claim()` 设置：

```python
task.owner = owner
task.status = "in_progress"
```

Subagent 里也会消费这个机制：[subagents.py](C:/02-study/MyProjects/ZCLI/zcli/subagents.py:90)

如果传入 `task_id`：

- 先加载 task；
- 如果 task 绑定了 worktree，就切到对应 worktree；
- 如果 task 是 pending，subagent 会自动 claim；
- 如果 task 已经 in_progress 且 owner 不是当前 subagent，就拒绝执行。

关键代码在 [subagents.py](C:/02-study/MyProjects/ZCLI/zcli/subagents.py:91) 到 [subagents.py](C:/02-study/MyProjects/ZCLI/zcli/subagents.py:99)。

还有一个 `claim_next()`：[tasks.py](C:/02-study/MyProjects/ZCLI/zcli/tasks.py:167)，会找到第一个：

- `pending`
- 无 owner
- 依赖已完成

的任务并认领。Team 里的 teammate 支持 `autoClaim`，会自动拿下一个可执行任务：[teams.py](C:/02-study/MyProjects/ZCLI/zcli/teams.py:244)。

面试里可以说：

> 认领机制是为了支持多 agent 并发协作。任务从 pending 被 claim 后会进入 in_progress，并记录 owner。Subagent 或 teammate 在执行任务前会检查 owner，避免两个执行体同时处理同一个 durable task。autoClaim 则允许后台 teammate 自动领取已经解除依赖的任务。

**5. Worktree 绑定：把任务和隔离代码空间关联起来**

Worktree 管理在 [worktrees.py](C:/02-study/MyProjects/ZCLI/zcli/worktrees.py:31)。

创建 worktree 的入口是 [worktrees.py](C:/02-study/MyProjects/ZCLI/zcli/worktrees.py:98)：

```python
def create(self, name: str, task_id: str = "") -> str:
```

它会：

- 校验 worktree 名称；
- 可选校验 task 是否存在；
- 读取当前 `HEAD`；
- 创建 `git worktree add ... -b zcli/<name>`；
- 写入 `.zcli/worktrees.json` 注册表；
- 如果传了 `task_id`，调用 `tasks.bind_worktree(task_id, name)`；
- 写入事件日志 `.zcli/worktree-events.jsonl`。

任务绑定字段在 `Task.worktree` 上。绑定逻辑在 [tasks.py](C:/02-study/MyProjects/ZCLI/zcli/tasks.py:150)，Worktree 层的绑定接口在 [worktrees.py](C:/02-study/MyProjects/ZCLI/zcli/worktrees.py:122)。

Subagent 执行 task 时会优先使用 task 绑定的 worktree：[subagents.py](C:/02-study/MyProjects/ZCLI/zcli/subagents.py:91)

```python
if task.worktree:
    workspace = self.worktrees.resolve(task.worktree)
```

所以绑定后的效果是：这个 task 的执行天然落在隔离的 git worktree 里，而不是主 workspace。

删除 worktree 时也会解绑任务：[worktrees.py](C:/02-study/MyProjects/ZCLI/zcli/worktrees.py:153)。它会先检查是否有未提交改动或新提交，如果有且没有 `discard_changes=true`，会拒绝删除，避免误删工作成果。

面试里可以说：

> Worktree 绑定解决的是并行开发隔离问题。一个 durable task 可以绑定到一个 managed git worktree，subagent 执行该 task 时会自动切到对应 workspace。这样不同任务可以在不同分支和目录里并行推进，减少文件冲突。删除 worktree 时会检查 dirty files 和 commits，并同步解绑 task。

**一段面试版总结**

你可以这样讲：

> 这个项目里我实现了两层任务系统。`TodoWrite` 是 session 级的短期执行清单，用来约束当前对话里的多步工作。它会把 todos 写入 session，并在 system prompt 中持续注入；如果模型连续多轮工具调用没有更新 todo，会自动提醒。
>
> 另一层是持久化 Task Graph，用文件系统保存 durable task。每个 task 有 `pending / in_progress / completed` 状态、`owner`、`blockedBy` 依赖和可选 `worktree` 绑定。任务认领时会检查依赖是否完成，只有所有 blockedBy 任务完成后才能从 pending 进入 in_progress；完成任务后会扫描并提示被解锁的后续任务。
>
> 这个 Task Graph 也服务于多 agent 协作：subagent 执行 task 前会自动 claim，检查 owner，避免重复处理；teammate 支持 autoClaim 自动领取可执行任务。对于需要并行改代码的任务，我还支持把 task 绑定到 git worktree，subagent 执行时自动切到对应隔离工作区，从而实现任务依赖、状态流转、认领和代码隔离的一体化管理。
>
<!-- > 如何确保task没有环，task之间是如何依赖的，会有数据或者状态转递吗 -->
<!-- 每个task维护一个blockedby，在创建的时候只会被已经存在的task阻塞，不会成环；只是状态门控，没有数据流依赖 -->