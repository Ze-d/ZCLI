# 数据流 & 状态流转

## 完整数据流

```
用户输入 (query)
  │
  ▼
cli.py: REPL 循环
  │ 内置命令? → /exit /memory /sessions /todos /tasks → 直接处理
  │ 否 → agent.run_turn(session, query)
  ▼
agent.py: Pre-turn
  ├─ hooks.trigger(UserPromptSubmit) → 阻断或附加上下文
  ├─ memory.render_relevant(query)  → 相关记忆片段
  ├─ session.messages.append(user_msg)
  └─ sessions.save(session)        → 原子写盘
  ▼
agent.py: Tool loop (while True)
  ├─ rounds_since_todo >= 3? → 注入 Todo reminder
  ├─ context.prepare(messages)
  │   └─ 大结果落盘 → 历史裁剪 → 旧结果压缩 → 必要时摘要
  ├─ recovery.with_retry(...)
  │   └─ 429/529 退避；连续 529 可切 fallback model
  ├─ client.messages.create()      → LLM 调用
  ├─ session.messages.append(assistant_msg)
  ├─ 有 tool_use?
  │   ├─ hooks.trigger(PreToolUse)
  │   │   ├─ blocked → 权限/Hook 拒绝结果
  │   │   └─ allow → tools.execute(name, input)
  │   ├─ hooks.trigger(PostToolUse) → 检查/改写输出
  │   ├─ emit("[tool_name] output[:300]")
  │   ├─ session.messages.append(tool_results)
  │   └─ 继续循环
  └─ 无 tool_use?
      ├─ hooks.trigger(Stop)
      ├─ continuation → 注入一次 user 消息并继续
      └─ 无 continuation → 跳出循环
  ▼
agent.py: Post-turn
  └─ _extract_memories(turn_messages) → 容错异步抽取
  ▼
返回 text 给 cli.py
```

## Session 状态流转

```
Session 生命周期:

  load_or_create(id)
    ├─ 文件存在 → 加载 JSON → Session 对象
    └─ 不存在   → Session(id, messages=[], summary=None)
        │
        ▼
  run_turn() 每轮:
    messages 追加 user/assistant/tool_result
    todos 与 rounds_since_todo 随 Session 保存
    summary 在 compact 时更新
    sessions.save() → 原子写 .zcli/sessions/<id>.json
        │
        ▼
  下次 load_or_create() 自动恢复
```

## Planning 状态

```text
Session Todo:
  .zcli/sessions/<id>.json
    ├─ todos[]
    └─ rounds_since_todo

Durable Task Graph:
  .zcli/tasks/task_<id>.json
    pending → in_progress → completed
    blockedBy 全部 completed 后才允许 claim
```

## Memory 存储模型

```
.zcli/memory/
  ├── MEMORY.md          ← 索引文件 (每行一个条目)
  └── <slug>.md          ← 单条记忆 (YAML frontmatter + body)

每条记忆:
  ---
  name: <slug>
  description: <一句话摘要>
  metadata:
    type: user | feedback | project | reference
  ---
  <body>
```

## Context Compaction

每次模型调用前都会执行便宜压缩层；各层有独立触发条件：

- 当前轮工具结果总量超过 200,000 字符：最大的结果优先落盘；
- 消息数超过 50：裁剪中间历史，但保持工具调用配对；
- 工具结果超过 3 个：较早的大结果替换为短占位；
- 处理后估算 token 仍超过 `ZCLI_CONTEXT_LIMIT`：保存 transcript，调用 LLM 摘要并以 `[Compacted]` 消息替换历史；
- API 实际报告 prompt-too-long：执行 reactive compact，保留摘要与最近五条消息后重试。

详细流程见 [context-compaction.md](context-compaction.md)。
