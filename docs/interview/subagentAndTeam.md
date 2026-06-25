这条描述讲的是：你在 ZCLI 里做了一套“多执行体协作机制”。主 Agent 不必所有事都自己做，可以把任务委派给一次性 Subagent，或者启动后台 Teammate 持续工作；同时用文件邮箱通信，用 Git Worktree 做代码隔离，并通过 Task Graph 控制自动认领范围。

**1. Subagent：一次性同步委派**

核心在 [subagents.py](C:/02-study/MyProjects/ZCLI/zcli/subagents.py:60)。

`SubagentRunner.run()` 接收：

```python
name: str
role: str
prompt: str
task_id: str = ""
worktree: str = ""
```

它适合做“边界清楚的一次性任务”，比如：

- 检查某个模块；
- 写一组测试；
- 调研某个问题；
- 在指定 task/worktree 下完成局部修改。

Subagent 不是完整主 Agent，它的工具被限制在 [subagents.py](C:/02-study/MyProjects/ZCLI/zcli/subagents.py:15)：

```python
SUBAGENT_TOOLS = {
    "bash",
    "read_file",
    "write_file",
    "edit_file",
    "glob",
    "list_tasks",
    "get_task",
    "claim_task",
    "complete_task",
}
```

它不能创建新的 subagent，也不能操作团队系统。这就是“受控委派”：给它足够完成任务的工具，但不允许无限扩张执行范围。

如果传入 `task_id`，Subagent 会加载 task：[subagents.py](C:/02-study/MyProjects/ZCLI/zcli/subagents.py:90)

- 如果 task 绑定了 worktree，就切换到对应 worktree；
- 如果 task 是 `pending`，自动 claim；
- 如果 task 已被别人 owner，拒绝执行；
- 完成任务时也会检查 owner，避免别的 agent 误 complete。

面试可以说：

> Subagent 是同步的一次性执行体。我给它限制了工具白名单，并且和 Task Graph 集成：执行 task 前会检查依赖和 owner，必要时自动认领。这样主 Agent 可以把明确边界的工作委派出去，但不会失控地产生更多 agent 或抢占别人的任务。

**2. 后台 Teammate：长期异步协作**

核心在 [teams.py](C:/02-study/MyProjects/ZCLI/zcli/teams.py:115)。

`TeamManager.spawn()` 会启动一个后台线程：[teams.py](C:/02-study/MyProjects/ZCLI/zcli/teams.py:145)

```python
threading.Thread(
    target=self._teammate_loop,
    daemon=True,
)
```

Teammate 和 Subagent 的区别是：

- Subagent：同步、一次性、主 Agent 等结果；
- Teammate：后台线程、可以持续 idle、可接收消息继续工作。

每个 teammate 有状态：[teams.py](C:/02-study/MyProjects/ZCLI/zcli/teams.py:105)

```python
name
role
status
started_at
auto_claim
last_result
```

生命周期大致是：

```text
starting -> working -> idle -> completed/stopped/failed
```

`_teammate_loop()` 在 [teams.py](C:/02-study/MyProjects/ZCLI/zcli/teams.py:211)。它会：

1. 先执行初始 prompt；
2. 把结果发给 lead；
3. 进入 idle 循环；
4. 轮询邮箱；
5. 收到消息就继续执行；
6. 如果开启 autoClaim，就自动领取可执行 task；
7. 超时或收到 shutdown 后停止。

面试可以说：

> Teammate 是异步后台执行体，适合长任务或并行探索。它通过线程运行，有自己的状态机，完成初始任务后不会马上消失，而是进入 idle，继续监听邮箱消息或自动认领可执行任务。

**3. 文件邮箱：Agent 之间的通信机制**

文件邮箱在 [teams.py](C:/02-study/MyProjects/ZCLI/zcli/teams.py:24)。

`MessageBus` 把消息写到：

```text
.zcli/team-mailboxes/<agent>.jsonl
```

消息结构是 [teams.py](C:/02-study/MyProjects/ZCLI/zcli/teams.py:16)：

```python
TeamMessage:
    id
    sender
    recipient
    type
    content
    request_id
    timestamp
```

支持的消息类型包括：

- 普通消息：`message`
- 完成通知：`completion`
- 任务完成：`task_completion`
- 计划请求：`plan_request`
- 计划提交：`plan_submission`
- 计划审阅：`plan_review`
- 停止请求：`shutdown_request`
- 停止响应：`shutdown_response`
- 失败：`failure`

`read_types()` 读取后会消费消息：[teams.py](C:/02-study/MyProjects/ZCLI/zcli/teams.py:71)。这意味着邮箱是“可消费队列”，不是只追加日志。

这个设计很适合 CLI 项目：简单、可持久化、进程内线程之间也容易共享，不依赖数据库或消息队列。

面试可以说：

> 我用文件邮箱实现 teammate 和 lead 之间的异步通信。每个 agent 一个 JSONL mailbox，消息带 sender、recipient、type 和 request_id。读取时会消费消息，所以它更像一个轻量队列。这样即使没有引入 Redis 或数据库，也能支持后台 agent 的消息传递、计划审阅和安全停止。

**4. Git Worktree 隔离：并行修改不互相污染**

核心在 [worktrees.py](C:/02-study/MyProjects/ZCLI/zcli/worktrees.py:31)。

`WorktreeManager.create()` 在 [worktrees.py](C:/02-study/MyProjects/ZCLI/zcli/worktrees.py:98)，会执行：

```text
git worktree add <path> -b zcli/<name> <base_sha>
```

它会把 worktree 记录到：

```text
.zcli/worktrees.json
.zcli/worktree-events.jsonl
```

每个 worktree 记录包括：

```python
name
path
branch
base_sha
task_id
created_at
```

如果创建时传入 `task_id`，会调用：

```python
self.tasks.bind_worktree(task_id, name)
```

也就是把 task 和 worktree 绑定起来。

Subagent 执行 task 时会检查 task 是否有绑定 worktree：[subagents.py](C:/02-study/MyProjects/ZCLI/zcli/subagents.py:91)

```python
if task.worktree:
    workspace = self.worktrees.resolve(task.worktree)
```

所以效果是：某个 task 一旦绑定 worktree，执行它的 subagent 会自动在隔离目录里工作，而不是改主工作区。

删除 worktree 时也做了保护：[worktrees.py](C:/02-study/MyProjects/ZCLI/zcli/worktrees.py:153)

- 检查 dirty files；
- 检查相对 base_sha 的 commits；
- 有改动且未显式 `discard_changes=true` 时拒绝删除；
- 删除后解绑 task。

面试可以说：

> Worktree 隔离解决的是并行代码修改冲突。每个 task 可以绑定一个 managed git worktree，subagent 执行该 task 时自动切换 workspace。删除 worktree 前会检查未提交文件和新增 commit，避免误删工作成果。

**5. 受控自动认领：autoClaim**

自动认领在 [teams.py](C:/02-study/MyProjects/ZCLI/zcli/teams.py:244)。

Teammate 如果开启 `autoClaim`，idle 时会调用：

```python
task = self.tasks.claim_next(state.name)
```

`claim_next()` 在 [tasks.py](C:/02-study/MyProjects/ZCLI/zcli/tasks.py:167)，只会领取满足这些条件的任务：

- `status == "pending"`
- 没有 owner
- `can_start(task.id)` 为 true，也就是依赖都已完成

领取后会设置：

```python
task.owner = teammate_name
task.status = "in_progress"
```

这就是“受控”的含义：它不会乱抢任务，只拿未认领、未阻塞、可开始的 pending task。

而且工具定义里也提醒：只有允许 claim unrelated pending tasks 的 worker 才应该开 `autoClaim`。入口在 [tools.py](C:/02-study/MyProjects/ZCLI/zcli/tools.py:116) 的 `spawn_teammate` 工具描述。

**一段面试版总结**

你可以这样讲：

> 我实现了一套多 agent 协作机制。Subagent 是同步的一次性执行体，主 Agent 可以把边界明确的任务委派给它；它只暴露受限工具集，并和 Task Graph 集成，执行 task 前会检查 owner 和依赖，必要时自动认领。Teammate 则是后台线程，适合异步并行工作，它完成初始任务后会进入 idle，继续通过文件邮箱接收消息、提交结果、响应 shutdown 或计划审阅。
>
> Agent 之间的通信我用文件邮箱实现，每个 agent 一个 JSONL mailbox，消息带类型和 request_id，读取后消费，形成一个轻量持久队列。对于并行代码修改，我引入 Git Worktree 隔离：task 可以绑定到 managed worktree，subagent 执行该 task 时自动切到对应工作区，避免污染主 workspace。最后，teammate 支持 autoClaim，但只会自动认领未阻塞、未 owner 的 pending task，所以可以安全地让后台 worker 处理可执行任务。
>
<!-- python不是由于gil的原因不能多线程吗  -->