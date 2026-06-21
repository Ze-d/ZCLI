# tool_use 缺少 tool_result 导致会话永久 400

## 现象

Provider 返回：

```text
tool_use ids were found without tool_result blocks immediately after
```

一旦坏消息写入 Session，后续任何 Prompt 都会携带同一段非法历史，因此持续返回 400。上下文裁剪可能改变错误中的消息索引，但不是根因。

## 本次实际根因

`.zcli/sessions/test-start.json` 中存在：

```text
assistant: tool_use(call_00_yDr9..., bash)
user:      下一轮普通 Prompt
```

工具调用响应先被保存，进程却在结果写回前中断，导致两条消息之间缺少规定的 `tool_result`。该调用是历史中的 `bash`，并非 Zotero Streamable HTTP 调用；损坏历史恰好在测试 MCP 时暴露。

## 修复

这是进程意外中断产生的低频恢复问题，不进入 Agent 热路径。`SessionStore.load()` 在恢复 Session 时调用一次 `repair_tool_protocol()`：

- `tool_use` 后没有结果：插入 interrupted `tool_result`；
- 多工具调用只返回部分结果：补齐缺失结果；
- 无对应调用的孤立结果：移除；
- 结果顺序不一致：按工具调用顺序整理；
- 缺失 ID 的非法工具调用块：移除。

修复后立即原子保存，因此旧 Session 可以继续使用，无需删除整个对话历史。Agent Loop 和每次 Provider 调用前不再重复扫描。

## 验证

```powershell
python -m pytest -q tests/test_session.py
```

重点覆盖：Session 加载时恢复缺失结果、部分结果和孤立结果。
