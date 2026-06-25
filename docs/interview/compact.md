这条描述对应的核心代码在 [context.py](C:/02-study/MyProjects/ZCLI/zcli/context.py:1)，调用入口在 [agent.py](C:/02-study/MyProjects/ZCLI/zcli/agent.py:161)。

它解决的问题是：Agent 的 `session.messages` 会不断增长，尤其工具调用结果可能非常大。如果每次都把完整历史发给模型，会很快超过上下文窗口，或者成本非常高。所以这里设计的是一个**分层、逐级加重**的压缩链路。

**整体入口**

每次真正调用模型前，`Agent.run_turn()` 都会先执行：

```python
prepared, summary = self.context.prepare(
    session.messages,
    lambda messages: self._summarize(messages, state, emit),
)
```

也就是：不是等到报错才处理，而是在每次模型请求前主动整理上下文。

`prepare()` 在 [context.py](C:/02-study/MyProjects/ZCLI/zcli/context.py:181)：

```python
messages = self.tool_result_budget(messages)
messages = self.snip_compact(messages)
messages = self.micro_compact(messages)
if estimate_tokens(messages) > self.context_limit:
    return self.compact_history(messages, summarize)
return messages, None
```

它按四层执行：

1. 大结果落盘
2. 历史裁剪
3. 旧工具结果压缩
4. LLM 摘要压缩

**第一层：大结果落盘**

对应 [context.py](C:/02-study/MyProjects/ZCLI/zcli/context.py:71)。

`persist_large_output()` 判断工具输出是否超过阈值，默认 `30_000` 字符。超过就写到：

```text
.zcli/tool-results/<tool_use_id>.txt
```

然后上下文里只保留一个占位摘要：

```text
<persisted-output>
Full output: ...
Preview:
前 2000 字符
</persisted-output>
```

这个设计的好处是：模型还能看到输出的预览和文件路径，但不会把几万甚至几十万字符都塞进上下文。

还有一层预算控制在 [context.py](C:/02-study/MyProjects/ZCLI/zcli/context.py:86)：`tool_result_budget()` 只处理最后一条 user 消息中的工具结果。如果工具结果总量超过 `200_000` 字符，就从最大的结果开始落盘，直到回到预算内。

面试可以说：

> 第一层是针对工具输出的局部压缩。大结果不会直接进入模型上下文，而是落盘保存，prompt 中只保留路径和 preview，这样既保留可追溯性，又控制 token 规模。

**第二层：历史裁剪**

对应 [context.py](C:/02-study/MyProjects/ZCLI/zcli/context.py:114)。

`snip_compact()` 处理的是消息数量太多的问题。默认 `max_messages=50`，超过后：

- 保留开头几条；
- 保留最近一批消息；
- 中间替换成：

```text
[snipped N messages]
```

但这里有一个很关键的细节：它会尽量避免破坏工具调用协议。

因为 Anthropic 工具调用要求：

```text
assistant: tool_use
user: tool_result
```

这两条必须成对出现。如果裁剪时把其中一半裁掉，就会导致后续 API 请求非法。

所以 `snip_compact()` 会检查边界：

- 如果 head 末尾是 `tool_use`，就继续保留后面的 `tool_result`；
- 如果 tail 开头是 `tool_result`，就把前面的 `tool_use` 也拉进来。

面试可以说：

> 第二层是消息级裁剪。它不是粗暴截断，而是保留头部目标、尾部最近上下文，并且特别维护 tool_use/tool_result 的邻接不变量，避免压缩后破坏模型 API 协议。

**第三层：旧工具结果压缩**

对应 [context.py](C:/02-study/MyProjects/ZCLI/zcli/context.py:134)。

`micro_compact()` 专门处理旧的工具结果。默认只保留最近 3 个完整工具结果，较早且超过 120 字符的结果会被替换为：

```text
[Earlier tool result compacted. Re-run if needed.]
```

这和第一层不一样：

- 第一层是“大结果落盘”，还保留完整输出文件；
- 第三层是“旧结果缩略”，告诉模型早期结果已经不重要，必要时重新运行工具。

这适合 coding agent，因为最近几轮工具结果最有用，太早的 `ls`、`grep`、测试输出通常价值下降。

**第四层：LLM 摘要**

如果前三层之后，估算 token 仍超过 `context_limit`，就进入重压缩：[context.py](C:/02-study/MyProjects/ZCLI/zcli/context.py:151)。

`compact_history()` 会：

1. 把完整消息历史写入 transcript；
2. 调用 `_summarize()` 让 LLM 总结；
3. 用一条消息替换整个历史：

```text
[Compacted]

<summary>
```

摘要逻辑在 [agent.py](C:/02-study/MyProjects/ZCLI/zcli/agent.py:331)。prompt 会要求保留：

- 当前目标；
- 用户偏好和约束；
- 关键发现；
- 修改过的文件；
- 错误；
- 剩余工作。

所以这不是简单总结聊天，而是为了“让工作能继续”的状态摘要。

**异常兜底：reactive compact**

除了主动压缩，还有被动恢复。代码在 [agent.py](C:/02-study/MyProjects/ZCLI/zcli/agent.py:174)。

如果 provider 仍然返回 prompt too long，Agent 会执行：

```python
session.messages, session.summary = self.context.reactive_compact(...)
```

对应 [context.py](C:/02-study/MyProjects/ZCLI/zcli/context.py:164)。

`reactive_compact()` 会：

- 写 transcript；
- 尝试生成摘要；
- 保留最近 5 条消息；
- 如果边界上是工具结果，也会把对应 tool_use 一起保留；
- 然后重试一次。

这说明系统有两道防线：平时主动压缩，遇到真实超限错误时再反应式压缩。

**一段面试版总结**

你可以这样说：

> 我设计了一套分层上下文压缩机制，放在每次模型调用前执行。第一层针对大工具输出，把超过阈值的结果落盘，只在上下文里保留文件路径和 preview；第二层针对历史消息过多的问题，保留开头目标和最近上下文，中间用 snipped 占位，同时保证 tool_use 和 tool_result 不被拆开；第三层对较早的工具结果做 micro compact，只保留最近几个完整结果；如果这些轻量压缩后仍超过上下文限制，最后才调用 LLM 生成摘要，用 `[Compacted] + summary` 替换历史。
>
> 这个设计的重点是分层：便宜、确定性的压缩优先，昂贵的 LLM 摘要最后使用。同时它保留 transcript 和大结果文件路径，保证信息不是直接丢失；并且压缩过程维护工具调用协议，避免因为裁剪上下文导致后续 API 请求非法。
>
<!-- 为什么采用这个顺序进行压缩 -->
<!-- 这个顺序是按压缩成本和信息损失排序的。先处理新产生的大工具结果，因为它最可能瞬间撑爆上下文，而且落盘后仍可追溯；再裁剪长历史，因为这能直接减少消息数量，并且避免对即将被裁掉的旧消息做无效 micro compact；之后再压缩保留下来的旧工具结果；最后如果仍然超限，才调用 LLM 摘要。micro_compact 不会把工具调用历史删到三条，它只是保留最近三个完整工具结果，把更早的大结果内容替换成占位文本，tool_use/tool_result 的消息结构仍然保留。 -->

<!-- 我有几个问题：1.最后一条大结果直接落盘了，会不会影响大模型的回答质量。2.直接进行剪裁的时候，只有最开始三轮的消息和最近的若干，会不会造成大模型的失忆 -->

<!-- 在上下文预算有限时，优先保留目标、最近状态、工具协议完整性和可恢复路径；对大输出和旧历史做有损降级，但通过文件落盘、transcript、summary、memory、todo/task 状态减少不可恢复的信息丢失。
    可以进一步优化 preview 策略，比如保留 head + tail，而不是只保留前 2000 字符；对测试日志可以优先提取 error/fail/traceback 附近片段；或者让 persist 阶段生成一个结构化摘要。当前实现是通用版本，偏简单可靠。 -->