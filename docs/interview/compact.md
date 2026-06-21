分层压缩的核心思想是：先采用成本最低、信息损失最小的方式缩小上下文，最后才调用 LLM 生成摘要。

执行顺序位于 [context.py](C:/02-study/MyProjects/ZCLI/zcli/context.py) 的 `prepare()`：

```text
大结果落盘
→ 历史裁剪
→ 旧工具结果压缩
→ 检查 token
→ LLM 摘要
```

### 1. 大结果落盘

工具可能返回非常大的内容，例如测试日志或构建输出。

当单个结果超过默认的 30,000 字符时，完整内容写入：

```text
.zcli/tool-results/<tool_use_id>.txt
```

发送给模型的内容则替换为：

```xml
<persisted-output>
Full output: .../tool-1.txt
Preview:
前 2000 个字符
</persisted-output>
```

这样既降低上下文占用，又没有真正丢失数据。Agent 后续仍可读取原文件。

对应方法：

```python
persist_large_output()
tool_result_budget()
```

其中 `tool_result_budget()` 还会限制单轮工具结果总量，默认不超过 200,000 字符。

### 2. 历史裁剪

当消息数量超过默认的 50 条时，`snip_compact()` 会保留：

- 最前面的少量消息
- 最近的消息
- 中间插入一条裁剪标记

例如：

```text
用户最初目标
早期关键响应
[snipped 34 messages]
最近几轮对话
```

它特别处理了工具调用边界：

```text
assistant: tool_use
user: tool_result
```

这两条消息必须成对保留，否则 Anthropic API 会拒绝请求。

### 3. 旧工具结果压缩

工具结果通常比普通对话大，而且旧结果的价值会随时间降低。

`micro_compact()` 默认保留最近 3 个完整工具结果，将更早且超过 120 字符的结果替换为：

```text
[Earlier tool result compacted. Re-run if needed.]
```

它只删除结果正文，不删除工具调用记录，因此模型仍然知道：

- 之前调用过什么工具
- 对话流程发生过工具操作
- 如有需要可以重新执行

### 4. LLM 摘要

前三层执行完后，系统通过字符数粗略估算 token：

```python
token ≈ JSON字符数 / 4
```

如果仍超过 `ZCLI_CONTEXT_LIMIT`，才调用模型生成摘要。

摘要要求保留：

- 当前目标
- 用户偏好和约束
- 关键发现
- 修改过的文件
- 错误信息
- 剩余工作

完整历史会先保存到：

```text
.zcli/transcripts/compact_<时间>.jsonl
```

随后上下文被替换为：

```text
[Compacted]

<LLM 生成的工作摘要>
```

因此 LLM 摘要是损失最大、成本最高的一层，放在最后使用。

### Prompt 超限时的应急压缩

如果估算没有及时触发，但 API 实际返回：

```text
context_length_exceeded
prompt_is_too_long
```

系统会执行 `reactive_compact()`：

1. 保存完整 transcript。
2. 尝试生成摘要。
3. 保留最近 5 条消息。
4. 确保工具调用和结果不被拆开。
5. 重新请求模型。

整体效果可以概括为：

```text
能放文件就不删除
能删除旧结果就不删对话
能裁剪中间历史就不调用模型
前三者仍不够，最后才生成摘要
```