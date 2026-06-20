# 数据流 & 状态流转

## 完整数据流

```
用户输入 (query)
  │
  ▼
cli.py: REPL 循环
  │ 内置命令? → /exit /memory /sessions → 直接处理
  │ 否 → agent.run_turn(session, query)
  ▼
agent.py: Pre-turn
  ├─ memory.render_relevant(query)  → 相关记忆片段
  ├─ session.messages.append(user_msg)
  └─ sessions.save(session)        → 原子写盘
  ▼
agent.py: Tool loop (while True)
  ├─ _compact_if_needed(session)   → 超限则摘要
  ├─ client.messages.create()      → LLM 调用
  ├─ session.messages.append(assistant_msg)
  ├─ 有 tool_use?
  │   ├─ tools.execute(name, input)
  │   ├─ emit("[tool_name] output[:300]")
  │   ├─ session.messages.append(tool_results)
  │   └─ 继续循环
  └─ 无 tool_use?
      └─ 跳出循环
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
    summary 在 compact 时更新
    sessions.save() → 原子写 .zcli/sessions/<id>.json
        │
        ▼
  下次 load_or_create() 自动恢复
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

## Context Compaction 触发条件

- `estimated_size > context_limit` (默认 50,000 tokens)
- `len(messages) >= 8`
- 切分点: 保留最近 ~6 条，从 assistant 边界切分
- 旧消息 → LLM 摘要 → `<session_summary>` 块替换
