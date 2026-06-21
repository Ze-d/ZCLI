# TodoWrite 与 Task Graph 面试讲解

## 1. 一句话介绍

我在 ZCLI 中实现了两层规划系统：

- **TodoWrite** 管理当前 Session 内的执行步骤，避免 Agent 在长工具链中偏离目标；
- **Task Graph** 管理跨 Session 的持久任务和依赖关系，保证任务按正确顺序推进。

它们不是同一个功能的两个版本，而是分别解决“当前怎么做”和“长期先做什么”的问题。

## 2. 为什么需要两套系统

| | TodoWrite | Task Graph |
|---|---|---|
| 解决的问题 | 当前工作有哪些步骤、做到哪了 | 大目标如何拆分、任务之间谁依赖谁 |
| 生命周期 | 当前 Session | 跨 Session 持久化 |
| 存储 | Session JSON | `.zcli/tasks/task_*.json` |
| 依赖关系 | 没有，是平铺清单 | `blockedBy` 组成 DAG |
| 认领机制 | 没有 | `owner` + `claim_task` |
| 状态 | pending / in_progress / completed | pending / in_progress / completed |

例如“实现登录功能”可以在 Task Graph 中拆为：

```text
设计用户表
  ↓
实现登录接口
  ↓
编写集成测试
```

而“实现登录接口”这个任务内部，又可以用 TodoWrite 管理：

```text
[completed] 阅读现有认证代码
[in_progress] 实现接口
[pending] 补充测试
```

## 3. 整体执行链路

```text
用户提出复杂任务
  ↓
System Prompt 提醒模型使用 todo_write / Task Graph
  ↓
模型调用 todo_write 或 create_task
  ↓
PreToolUse Hook
  ↓
ToolRegistry 分发
  ├─ todo_write → 修改当前 Session.todos
  └─ Task 工具 → TaskStore 读写 .zcli/tasks/
  ↓
SessionStore / TaskStore 原子落盘
  ↓
下一轮 System Prompt 重新注入 Todo 和 Task 摘要
```

核心实现位于：

- `zcli/session.py`：Todo 状态；
- `zcli/tools.py`：Todo 和 Task 工具定义与分发；
- `zcli/tasks.py`：Task Graph 存储和状态机；
- `zcli/agent.py`：提醒、System Prompt 注入和工具循环；
- `zcli/cli.py`：`/todos`、`/tasks` 查询命令。

---

# TodoWrite 实现

## 4. Todo 数据放在哪里

Todo 是 Session 状态的一部分：

```python
@dataclass
class Session:
    id: str
    messages: list[dict]
    summary: str
    todos: list[dict] = field(default_factory=list)
    rounds_since_todo: int = 0
```

每个 Todo 的结构很小：

```json
{
  "content": "运行回归测试",
  "status": "pending"
}
```

状态只能是：

```text
pending / in_progress / completed
```

我没有把 Todo 放在全局变量中，而是放进 Session，原因是：

1. 不同 Session 的计划必须互相隔离；
2. Session 本来就在每次工具执行后原子写盘；
3. 进程重启后可以恢复计划；
4. 上下文压缩只压缩 `messages`，不会丢掉独立的 Todo 状态。

## 5. todo_write 为什么提交完整列表

工具输入是完整 Todo 数组：

```python
todo_write(todos=[
    {"content": "检查代码", "status": "completed"},
    {"content": "实现功能", "status": "in_progress"},
    {"content": "运行测试", "status": "pending"},
])
```

执行时会：

1. 校验输入必须是列表；
2. 校验每项必须有非空 `content`；
3. 校验状态枚举；
4. 使用新列表整体替换 `session.todos`；
5. 把 `rounds_since_todo` 重置为 0；
6. Agent 在工具结果写回后保存 Session。

整体替换比增量修改更适合 LLM：模型每次都提交自己看到的完整计划，不需要设计复杂的 patch 协议，也不容易出现索引错位。

为了兼容部分模型把数组错误序列化成字符串，输入层还支持 JSON 字符串和 Python literal，但最终都会归一化为 `list[dict]`。

## 6. Todo Reminder

参考 `learn-claude-code` s05，Agent 维护一个计数器：

```python
if call["name"] != "todo_write":
    session.rounds_since_todo += 1
```

连续执行三个非 Todo 工具后，在下一次模型调用前注入：

```xml
<reminder>Update your todos.</reminder>
```

然后计数归零。

这个机制解决的问题是：模型虽然一开始列了计划，但执行多个工具以后容易只关注最新工具结果，忘记更新整体进度。

它只是一个教学型启发式，不是严格调度器。更成熟的实现可以根据任务复杂度、Todo 是否存在、状态变化时间动态决定是否提醒。

## 7. Todo 如何重新进入模型上下文

每次调用模型前，`Agent.system_prompt()` 会读取当前 Session Todo：

```text
Current session todos:
- [completed] 检查代码
- [in_progress] 实现功能
- [pending] 运行测试
```

因此即使旧对话已经被 compact，Todo 仍然会从结构化 Session 状态重新注入，而不是依赖模型从历史摘要中猜测。

---

# Task Graph 实现

## 8. Task 数据模型

每个 Task 是一个独立 JSON 文件：

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
```

目录结构：

```text
.zcli/tasks/
  task_a1b2c3.json
  task_d4e5f6.json
```

Task ID 使用 UUID 的前 12 位生成，降低同一时间创建任务时的碰撞风险。ID 还经过正则校验，防止通过任务 ID 逃逸存储目录。

## 9. Task 状态机

```text
pending ──claim──> in_progress ──complete──> completed
```

非法转换会被拒绝：

- pending 不能直接 complete；
- in_progress 不能再次 claim；
- completed 不能再次 complete。

这里把“认领”和“开始执行”合并成一个动作：`claim_task` 同时写入 owner，并将状态改为 `in_progress`。这是参考 s12 教学版采用的简化。

## 10. blockedBy 依赖门禁

`can_start()` 检查一个任务的所有上游依赖：

```python
return all(
    dependency_file.exists()
    and load(dependency).status == "completed"
    for dependency in task.blockedBy
)
```

只要有一个依赖：

- 不存在；或
- 状态不是 completed；

当前任务就不能被认领。

例如：

```text
A: 设计数据结构       completed
B: 实现解析器         blockedBy=[A]
C: 编写集成测试       blockedBy=[B]
```

A 完成后，B 可以认领，但 C 仍然被 B 阻塞。

## 11. 完成任务与下游解锁

`complete_task` 只接受 `in_progress` 任务：

```text
in_progress → completed
```

保存以后扫描直接依赖当前任务的 pending 任务。如果某个下游的全部依赖现在都完成，就在工具结果中返回：

```text
Completed task_xxx (设计数据结构)
Unblocked: 实现解析器
```

这个返回值很重要，因为模型可以立即知道下一步有哪些任务可做，不需要再次扫描整个图。

## 12. 持久化与一致性

TaskStore 使用临时文件加原子替换：

```text
JSON 序列化
  → 写入 task-*.tmp
  → os.replace(tmp, task_xxx.json)
```

这样即使进程在写入中途退出，也不会留下半个 JSON 覆盖原任务文件。

进程内的 claim/complete 使用 `threading.RLock` 包围“重新读取 → 检查 → 修改 → 保存”，减少同一进程多个线程之间的竞争。

但是当前没有跨进程文件锁，所以不能声称支持多个 ZCLI 进程安全地同时认领同一任务。这是实现边界，而不是隐藏掉的问题。

## 13. Task Graph 如何重新进入模型上下文

每次调用模型前，Agent 会读取 TaskStore 并注入最多 4,000 字符的任务摘要：

```text
Durable task graph:
task_a: 设计数据结构 [completed] owner=agent
task_b: 实现解析器 [in_progress] owner=agent blockedBy=task_a
task_c: 编写测试 [pending] blockedBy=task_b
```

详细描述不全部塞进 System Prompt，避免任务多时占满上下文。模型需要细节时调用 `get_task`。

这是一种两级加载：摘要常驻上下文，完整内容按需读取。

---

# 工程设计与面试追问

## 14. 为什么 Task 每个文件一个，而不是一个大 JSON

优点：

- 单个任务更新时写入范围小；
- 文件损坏影响局部；
- 未来容易对单任务加锁；
- 多 Agent 可以围绕单个任务做 ownership 控制；
- 人工检查和调试更直接。

代价是 `list_tasks()` 需要扫描目录；任务量很大时应引入索引或数据库。

## 15. 为什么 Todo 不直接复用 Task Graph

Todo 更新频率高、粒度细，不需要依赖和 owner。如果每个小步骤都写 Task 文件，会增加模型调用复杂度和磁盘写放大。

Task Graph 关注可恢复的工作单元；Todo 关注当前工作单元内部的执行细节。拆开以后，每套数据模型都更简单。

## 16. 与 Context Compact 的关系

Todo 和 Task 没有只存在聊天历史里：

```text
messages 被摘要或裁剪
  ├─ Session.todos 仍然存在
  └─ .zcli/tasks/*.json 仍然存在
```

下一次模型调用时，它们会重新注入 System Prompt。因此规划状态不会依赖摘要模型是否“记住了所有步骤”。

这是 Harness 设计中的一个重要思想：关键状态结构化保存，不把所有可靠性都押在 LLM 上下文里。

## 17. 当前不足与下一步优化

面试时应主动说明边界：

1. **没有环检测**：A blockedBy B、B blockedBy A 会永久阻塞；下一步可在创建或更新依赖时做 DFS/拓扑排序。
2. **没有跨进程锁**：当前只有进程内 RLock；下一步可使用文件锁、SQLite 事务或数据库行锁。
3. **没有任务回退**：缺少 in_progress → pending 的 release/unassign，用于 Agent 中断后的重新认领。
4. **Task 摘要有 4,000 字符上限**：任务很多时需要相关任务选择或分页。
5. **Reminder 是固定阈值**：可以根据 Todo 是否过期、任务复杂度和工具类型动态提醒。
6. **没有 Task 生命周期 Hook**：后续可以扩展 TaskCreated、TaskCompleted 事件。

## 18. 常见面试追问

### Q1：为什么 Todo 要持久化？原项目不是内存状态吗？

教学版用进程内变量强调概念。ZCLI 是个人 Agent，用户会退出并恢复 Session，因此我把 Todo 放进 Session JSON。它仍然属于 Session，而不是跨 Session 的全局任务。

### Q2：如何避免任务被提前执行？

真正的门禁在 `claim()`，不是只靠 Prompt。`claim()` 会重新读取任务并检查所有 blockedBy；依赖未完成时返回 blocked，不改变 owner 和状态。

### Q3：如果模型谎称任务完成怎么办？

状态只有调用 `complete_task` 才会变化，最终以 `.zcli/tasks/*.json` 为准。模型文字不是事实来源，工具结果和持久化状态才是。

### Q4：如何处理两个 Agent 同时 claim？

当前 RLock 只能处理同进程线程，不能保证跨进程安全。我会进一步使用 SQLite 事务或文件锁，在锁内重新读取并执行 compare-and-set。

### Q5：为什么不把整个 Task 描述都放进 Prompt？

任务越多，固定注入成本越高。我只注入状态摘要，详细内容由 get_task 按需加载，类似 Skill 和 Memory 的渐进式加载思想。

### Q6：如何检测依赖环？

把 Task 看成有向图。新增 blockedBy 边之前，从上游节点做 DFS，如果能回到当前节点就拒绝；也可以对整个图做拓扑排序，无法覆盖所有节点就说明存在环。

---

# 面试口述版本

## 19. 1 分钟版本

> 我在 ZCLI 里实现了两层规划系统。TodoWrite 管当前 Session 内的细粒度步骤，完整列表保存在 Session JSON 中，状态包括 pending、in_progress 和 completed。模型连续执行三个非 Todo 工具后，系统会注入提醒要求更新计划；每次模型调用前 Todo 都会重新进入 System Prompt，所以上下文压缩不会丢掉计划。
>
> Task Graph 管跨 Session 的持久任务，每个任务单独保存为 JSON，包含 owner、status 和 blockedBy。claim 时会在代码层检查所有依赖必须完成，而不是只靠 Prompt；complete 后会扫描并返回刚解锁的下游任务。写入使用临时文件加 os.replace，避免产生半文件。
>
> 两套系统分开的原因是时间尺度不同：Todo 回答当前任务怎么做，Task Graph 回答长期任务先做什么。当前实现还没有环检测和跨进程锁，这是后续会用拓扑检查和事务锁完善的部分。

## 20. 2 分钟版本

> 这个模块参考了 learn-claude-code 的 s05 和 s12，但我针对个人 Agent 做了持久化改造。
>
> 第一层是 TodoWrite。它不增加执行能力，而是增加规划能力。模型通过 todo_write 提交完整清单，我会校验内容和状态，然后整体替换 Session.todos 并原子保存。执行三个非 Todo 工具后，Agent 注入 reminder，避免长工具链让模型忘记更新计划。Todo 独立于 messages，所以 compact 后仍能通过 System Prompt 恢复。
>
> 第二层是 Task Graph。每个 Task 有 subject、description、owner、status 和 blockedBy，状态机是 pending 到 in_progress 再到 completed。claim 是强制门禁：只有 blockedBy 全部存在且完成才能认领。complete 后扫描直接下游，把新解锁任务返回模型。Task 每个文件独立保存，并通过临时文件和 os.replace 原子更新；进程内用 RLock 包住状态转换。
>
> Todo 和 Task 没有合并，因为 Todo 是高频、细粒度、会话级状态，Task 是低频、带依赖、跨会话状态。这样既减少工具使用复杂度，也避免把所有关键状态都压在 LLM 对话历史上。
>
> 当前边界是没有依赖环检测、没有跨进程锁，也没有 release 路径。我会分别用 DFS 或拓扑排序、SQLite 事务，以及 unassign 状态转换来完善。
