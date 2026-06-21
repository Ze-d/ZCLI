# 分层上下文压缩

ZCLI 参考 `learn-claude-code` 的 s08 和 s20，将上下文处理设计为由便宜到昂贵的四层流水线。入口是 `ContextManager.prepare()`：

```text
tool_result_budget
  → snip_compact
  → micro_compact
  → estimate_tokens
  → compact_history（仅在仍超限时）
```

目标不是简单删除历史，而是在控制 token 的同时保留可恢复性和 Anthropic 消息协议的合法性。

## 第一层：大工具结果落盘

单个工具结果超过 `persist_threshold`（默认 30,000 字符），或当前轮工具结果总量超过 `tool_result_budget_bytes`（默认 200,000 字符）时，完整输出写入：

```text
.zcli/tool-results/<tool_use_id>.txt
```

消息中的正文替换为路径、前 2,000 字符预览和 `<persisted-output>` 标记。模型不再承担完整日志的 token 成本，但后续仍可读取原文件。

## 第二层：历史裁剪

消息数超过 `max_messages`（默认 50）时，`snip_compact()` 保留开头三条与最近消息，中间替换为：

```text
[snipped N messages]
```

裁剪边界会检查以下配对，不会只保留其中一半：

```text
assistant: tool_use
user: tool_result
```

这是 Anthropic Messages API 的结构约束，也是压缩测试中的关键不变量。

## 第三层：旧工具结果压缩

`micro_compact()` 保留最近 `keep_recent_tool_results` 个完整工具结果（默认 3）。更早且超过 120 字符的结果被替换为：

```text
[Earlier tool result compacted. Re-run if needed.]
```

工具调用记录仍然存在，因此模型知道之前执行过什么，并可在必要时重新执行。

## 第四层：LLM 摘要

前三层完成后，`estimate_tokens()` 使用 `JSON 字符数 / 4` 做低成本估算。如果仍超过 `ZCLI_CONTEXT_LIMIT`（默认 50,000），系统会：

1. 将完整消息原子写入 `.zcli/transcripts/compact_<timestamp>.jsonl`；
2. 调用模型总结目标、偏好、约束、关键发现、文件修改、错误和剩余工作；
3. 使用一条 `[Compacted]` 摘要消息替换历史；
4. 将摘要保存到 Session 的 `summary` 字段。

LLM 摘要具有额外调用成本且存在信息损失，所以放在流水线最后。

## Reactive compact

字符估算不是精确 tokenizer。如果 API 仍返回 `prompt_is_too_long`、`context_length_exceeded` 或类似错误，Agent 会执行应急压缩：

1. 保存 `reactive_<timestamp>.jsonl` transcript；
2. 尝试生成恢复摘要，失败则使用安全占位摘要；
3. 保留最近五条消息；
4. 如果边界落在 `tool_result`，向前扩展以保留对应 `tool_use`；
5. 使用压缩后的上下文重试一次。

## 数据目录

```text
.zcli/
  tool-results/   # 大型工具输出
  transcripts/    # compact/reactive compact 前的完整历史
  sessions/       # 压缩后的当前会话和 summary
```

## 测试不变量

- 便宜层必须先于 LLM 摘要执行；
- 大型输出落盘后可以完整恢复；
- 最近工具结果保持完整，旧结果才被微压缩；
- `tool_use/tool_result` 永不成为孤立消息；
- compact 与 reactive compact 都必须保存 transcript；
- 未超过阈值时不得调用摘要模型。

