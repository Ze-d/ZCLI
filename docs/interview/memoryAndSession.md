这条可以理解成：你给 ZCLI 做了一套“让 Agent 有连续性”的状态层。它不是单纯保存聊天记录，而是把长期记忆、会话恢复、工具调用协议修复放在一起，解决 CLI Agent 重启后还能继续工作的问题。

**1. Memory：长期记忆系统**

核心在 [memory.py](C:/02-study/MyProjects/ZCLI/zcli/memory.py:20)。

`MemoryStore` 负责把记忆存到 `.zcli/memory/` 下：

- 每条记忆是一个 Markdown 文件，带 YAML frontmatter；
- `MEMORY.md` 是索引文件；
- 支持 `user / feedback / project / reference` 四类记忆；
- `remember()` 写入单条记忆并重建索引：[memory.py](C:/02-study/MyProjects/ZCLI/zcli/memory.py:33)。

它的查询不是向量检索，而是一个轻量关键词匹配：

- `_terms()` 支持英文词和中文单字分词；
- `relevant()` 用 query 和 memory 内容的词交集打分：[memory.py](C:/02-study/MyProjects/ZCLI/zcli/memory.py:85)；
- `render_relevant()` 把最相关的记忆渲染成 `<relevant_memories>` 块：[memory.py](C:/02-study/MyProjects/ZCLI/zcli/memory.py:97)。

Agent 每次构造 prompt 时会注入两层记忆：

- `Long-term memory catalog`：所有记忆的轻量索引；
- `<relevant_memories>`：和当前问题相关的记忆正文。

对应代码在 [agent.py](C:/02-study/MyProjects/ZCLI/zcli/agent.py:86)。

**2. 偏好自动提取**

这部分在 [agent.py](C:/02-study/MyProjects/ZCLI/zcli/agent.py:347)。

流程是：

1. 用户正常对话；
2. Agent 完成本轮回答，且模型不再请求工具；
3. `run_turn()` 调用 `_extract_memories(turn_messages)`：[agent.py](C:/02-study/MyProjects/ZCLI/zcli/agent.py:256)；
4. 再发一次轻量 LLM 调用，让模型只提取“持久偏好、重复反馈、稳定项目事实”；
5. 要求模型只返回 JSON array；
6. `MemoryStore.save_extracted()` 解析并落盘：[memory.py](C:/02-study/MyProjects/ZCLI/zcli/memory.py:105)。

这里的亮点是它是“非侵入式”的：用户不用显式说“记住”，系统也能从对话里提取偏好。并且 `_extract_memories()` 外层有 `try/except`，记忆提取失败不会影响正常对话。

面试可以这样讲：

> 我把记忆提取放在主对话完成之后，作为一个容错的后处理流程。主链路先保证用户请求成功，之后再用一次小模型调用从本轮对话中提取稳定偏好或项目事实，写入 Markdown 记忆库。下次请求时，系统会注入全量记忆索引和当前 query 相关的记忆正文，从而实现长期个性化。

**3. Session：多会话恢复**

Session 核心在 [session.py](C:/02-study/MyProjects/ZCLI/zcli/session.py:105)。

`Session` 保存的不只是 messages：

- `id`
- `created_at / updated_at`
- `messages`
- `summary`
- `todos`
- `rounds_since_todo`

也就是说，一个 session 是“对话历史 + 压缩摘要 + 当前 todo 状态”的组合。

`SessionStore` 负责：

- `create()` 创建新会话：[session.py](C:/02-study/MyProjects/ZCLI/zcli/session.py:126)；
- `load()` 加载已有会话：[session.py](C:/02-study/MyProjects/ZCLI/zcli/session.py:138)；
- `load_or_create()` 支持恢复或自动创建：[session.py](C:/02-study/MyProjects/ZCLI/zcli/session.py:145)；
- `save()` 原子写 JSON 文件：[session.py](C:/02-study/MyProjects/ZCLI/zcli/session.py:149)；
- `list()` 列出多个会话：[session.py](C:/02-study/MyProjects/ZCLI/zcli/session.py:161)。

CLI 里通过 `--session` 和 `--list-sessions` 暴露出来：[cli.py](C:/02-study/MyProjects/ZCLI/zcli/cli.py:15)。

Agent 在关键节点都会保存 session：

- 用户消息进入历史后保存；
- compact 后保存；
- assistant 回复后保存；
- tool result 写入后保存。

这些保存点集中在 [agent.py](C:/02-study/MyProjects/ZCLI/zcli/agent.py:123) 的 `run_turn()` 里。

面试可以强调：

> 我没有把 session 当成简单日志，而是把它设计成 Agent 可恢复的运行状态。每轮对话、工具调用、todo 状态、上下文压缩摘要都会持久化，所以用户可以用不同 session id 维护多个任务上下文，进程重启后也能继续。

**4. 异常工具调用历史修复**

这是最有工程含量的一点，在 [session.py](C:/02-study/MyProjects/ZCLI/zcli/session.py:26)。

Anthropic 的工具协议要求：

```text
assistant: tool_use
user:      tool_result
```

而且 `tool_result` 必须紧跟对应的 `tool_use`。如果进程在保存了 `tool_use` 后崩溃，但还没保存 `tool_result`，这个 session 以后每次发送都会带着非法历史，导致 Provider 持续 400。

你的修复是：在 `SessionStore.load()` 时调用 `repair_tool_protocol()`：

```python
session.messages, repairs = repair_tool_protocol(session.messages)
if repairs:
    self.save(session)
```

对应 [session.py](C:/02-study/MyProjects/ZCLI/zcli/session.py:138)。

它处理几类坏历史：

- `tool_use` 后没有 `tool_result`：补一个 interrupted error result；
- 多个工具调用只返回部分结果：补齐缺失结果；
- 孤立的 `tool_result`：删除；
- 结果顺序错乱：按 tool_use 顺序重排；
- 没有 id 的非法 tool_use：移除。

这点可以讲得很漂亮：

> 我遇到过一个恢复类问题：工具调用响应已经写入 session，但进程在工具结果写回前中断，导致历史里出现 orphan tool_use。Provider 会认为消息协议非法，之后这个 session 永久 400。我的解决方案不是让用户删除会话，而是在 session load 阶段做一次协议修复，补齐 interrupted tool_result，并把修复后的 session 原子保存。这样旧会话可以继续使用，修复逻辑也不会进入每次 Agent 调用的热路径。

**一段面试版总结**

你可以这样说：

> 这个项目里我实现了 Memory 和 Session 两层状态系统。Memory 负责长期偏好和项目事实，底层用 Markdown + YAML frontmatter 存储，并维护一个 `MEMORY.md` 索引。每轮对话结束后，我会用一次轻量 LLM 调用自动提取稳定偏好、用户反馈或项目事实，解析成结构化 JSON 后写入记忆库。下一轮请求时，Agent 会把记忆索引和与当前 query 相关的记忆正文注入上下文。
>
> Session 负责短中期运行状态恢复，包括消息历史、summary、todo 状态等。每次用户消息、assistant 回复、工具结果、上下文压缩后都会原子保存，因此支持多个 session id 并行恢复。比较关键的是我还处理了工具调用历史损坏的问题：如果进程在 tool_use 后、tool_result 前中断，Provider 会因为协议不合法持续返回 400。我在 Session 加载时做协议修复，补齐 interrupted tool_result、移除孤立结果并重排结果顺序，保证历史重新满足模型 API 的工具调用不变量。