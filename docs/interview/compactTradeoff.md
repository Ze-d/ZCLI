# 大工具结果 Artifact 化：设计取舍与第一版实现

这次改造针对分层上下文压缩中的第一个问题：**大工具结果落盘后，如何保证模型能够安全、低成本地重新读取完整结果。**

核心代码：

- [artifacts.py](C:/02-study/MyProjects/ZCLI/zcli/artifacts.py:36)：Artifact 存储与读取；
- [tools.py](C:/02-study/MyProjects/ZCLI/zcli/tools.py:99)：Artifact 工具定义和 Session 授权；
- [agent.py](C:/02-study/MyProjects/ZCLI/zcli/agent.py:60)：执行链路接入；
- [context.py](C:/02-study/MyProjects/ZCLI/zcli/context.py:61)：上下文预算接入；
- [test_artifacts.py](C:/02-study/MyProjects/ZCLI/tests/test_artifacts.py:1)：完整性和隔离测试。

## 一、旧方案的问题

旧实现会把超过 30,000 字符的工具结果写入：

```text
.zcli/tool-results/<tool_use_id>.txt
```

上下文只保留文件路径和前 2,000 个字符。但它存在三个问题。

### 1. 落盘前已经截断

旧版 `bash` 和 `read_file` 最多返回前 50,000 字符，Agent 收到结果后才执行落盘。

```text
真实输出 500,000 字符
→ 工具截断为 50,000 字符
→ 落盘 50,000 字符
→ 后 450,000 字符永久丢失
```

因此旧方案保存的并不一定是完整结果。

### 2. 普通 `read_file` 不适合召回大结果

- 不能按 offset 或范围读取；
- 不能针对错误、符号或关键词搜索；
- 读取出的结果可能再次超过落盘阈值；
- `data_dir` 位于 workspace 外时可能被路径权限拒绝。

所以“文件仍然存在”不等于“Agent 可以有效恢复信息”。

### 3. 文件路径没有 Session 隔离语义

Artifact 属于会话工作记忆，不应该只凭一个全局路径或 ID 被其他 Session 访问。

设计原则是：

> `artifact_id` 只负责标识资源，不能充当访问凭证；实际访问主键是 `(session_id, artifact_id)`。

## 二、第一版范围

第一版只实现最小闭环：

```text
完整输出
→ Session 私有 Artifact
→ head/tail 预览
→ inspect / search / chunk read 按需召回
```

暂不实现：

- LLM 自动摘要；
- Map-Reduce 全量分析；
- 向量或语义检索；
- Subagent 自动分析；
- 二进制 Artifact；
- 工具输出流式写盘；
- 自动清理和生命周期策略。

这样先解决“完整保存”和“按需读取”，避免同时引入存储、检索、模型调用和调度四类复杂度。

## 三、Artifact 数据模型

Artifact 按 Session 分目录保存：

```text
.zcli/artifacts/
└── <session_id>/
    └── <artifact_id>/
        ├── content.txt
        └── metadata.json
```

元数据包含：

```text
artifact_id
session_id
tool_use_id
source_tool
chars
lines
created_at
content_hash
encoding
```

`content.txt` 和 `metadata.json` 都通过临时文件加 `os.replace()` 原子写入。

Artifact ID 和 Session ID 都经过格式校验，不能包含路径分隔符，避免路径穿越。

## 四、执行链路

### 1. 工具先返回完整文本

`bash` 和 `read_file` 不再提前截断为 50,000 字符。工具结果首先完整返回给 Agent。

### 2. Agent 判断是否 Artifact 化

工具输出超过 30,000 字符时：

```python
compact_output = self.artifacts.persist_if_large(
    session.id,
    call["id"],
    call["name"],
    output,
)
```

完整正文写入当前 Session 的 Artifact 目录，上下文只保留：

```text
<artifact-result>
Artifact ID: artifact_xxx
Source tool: bash
Size: 500000 chars, 8000 lines

Head preview:
...

Tail preview:
...

Use inspect_artifact, search_artifact, or read_artifact_chunk...
</artifact-result>
```

预览采用 head 1,200 字符加 tail 800 字符。相比只保留开头，尾部更容易覆盖测试总结、退出状态和异常根因。

### 3. 聚合预算也使用 Artifact

即使每个结果都没有超过 30,000 字符，多条结果合计仍可能超过 200,000 字符。

`ContextManager.tool_result_budget()` 会从最大的结果开始强制 Artifact 化，直到当前轮工具结果回到预算内。

这同时修复了旧实现中的一个问题：旧逻辑调用 `persist_large_output()` 时仍受单结果阈值限制，可能出现“总量超限但一条也没有真正落盘”。

## 五、三个读取工具

### `inspect_artifact`

用于快速了解 Artifact：

```json
{
  "artifact_id": "artifact_xxx"
}
```

返回大小、行数、来源工具、哈希、创建时间和 head/tail 预览。

### `search_artifact`

用于按普通文本或正则定位：

```json
{
  "artifact_id": "artifact_xxx",
  "query": "ERROR|Traceback",
  "regex": true,
  "context_lines": 10,
  "max_matches": 20
}
```

实现采用逐行扫描，不需要把完整 Artifact 再次加载到内存。返回结果包含：

- 命中行号；
- 字符 offset；
- 命中位置前后的上下文；
- 最多 20,000 字符的硬限制。

### `read_artifact_chunk`

用于读取已知位置附近的原文：

```json
{
  "artifact_id": "artifact_xxx",
  "offset": 120000,
  "limit": 8000
}
```

返回 `next_offset` 和 `has_more`，模型可以继续分页。单次最多返回 20,000 字符，避免读取结果再次触发 Artifact 化。

第一版使用字符 offset 而不是纯行号，因为日志和 JSON 可能出现单行数十万字符的情况。

## 六、Session 隔离

三个 Artifact 工具的 Schema 都只允许模型传入 `artifact_id`，不允许传入 `session_id`。

执行时由系统注入当前会话：

```python
self.artifacts.read_chunk(
    session.id,
    artifact_id,
    offset,
    limit,
)
```

因此：

```text
Session A 创建 Artifact
→ Session A 可以读取
→ 恢复 Session A 后仍可读取
→ Session B 即使知道 artifact_id 也无法读取
```

跨 Session 访问统一返回：

```text
artifact not found in current session
```

不区分“资源不存在”和“资源属于其他 Session”，避免泄露其他会话的资源信息。

## 七、为什么不直接使用 Subagent 或 Map-Reduce

Search、Chunk Read、Map-Reduce 和 Subagent 并不是严格的四级替代关系：

- Search、Chunk Read 是数据访问方式；
- Map-Reduce 是全量分析算法；
- Subagent 是上下文隔离与任务调度方式。

第一版优先提供便宜、确定性的基础能力：

```text
有关键词 → Search
有已知位置 → Chunk Read
```

后续只有在要求完整覆盖时才增加 Map-Reduce；只有调查跨多个 Artifact、需要多轮自主探索时才使用 Subagent。Subagent 内部仍然需要调用 Search 和 Chunk Read。

## 八、当前限制

1. 工具输出仍会在内存中完整构造一次，极大输出可能造成内存压力；
2. Artifact 只支持 UTF-8 文本；
3. 字符 offset 读取越靠后，需要从文件开头扫描越多内容；
4. 普通搜索区分大小写；
5. 正则表达式没有独立的执行超时；
6. Artifact 暂时没有 TTL、配额和垃圾回收；
7. Subagent 默认没有继承主 Session Artifact 的授权能力。

如果继续演进，优先级建议为：

```text
流式写盘
→ Artifact 生命周期与配额
→ 更高效的 offset/行索引
→ 面向具体问题的结构化 Map-Reduce
→ 显式授权的 Subagent Artifact 分析
```

## 九、测试结果

新增测试覆盖：

- 500K 结果完整保存并可通过分块读取重建；
- head/tail 预览；
- 文本和正则搜索；
- 超长单行分块；
- 20K 返回预算；
- 非法 Artifact ID 和路径穿越；
- Session A 与 Session B 的读取隔离；
- `data_dir` 位于 workspace 外时仍可通过专用工具访问；
- 聚合结果预算触发 Artifact 化；
- Agent 工具循环端到端保存完整大结果；
- `read_file` 不再提前截断。

最终全量回归：

```text
82 passed
```

## 十、面试版总结

> 原来的大结果落盘只能降低 Prompt 大小，但没有形成可靠的召回闭环：部分工具会在落盘前截断，而且普通文件读取无法搜索、分页，也缺少 Session 隔离。  
> 我将其重构为 Session-scoped Artifact Store。大结果先完整持久化，上下文仅保留逻辑 ID、大小以及 head/tail 预览；模型可以通过 inspect、search 和基于字符 offset 的 chunk read 按需获取证据。所有访问都由系统隐式绑定当前 Session，Artifact ID 只负责寻址，不能作为跨会话访问凭证。  
> 第一版刻意没有直接加入 Map-Reduce 和 Subagent，而是先完成低成本、可验证的存储与召回闭环。需要完整覆盖或复杂调查时，再在这层基础能力之上升级。
