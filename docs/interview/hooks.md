ZCLI 的 Hook 本质上是在 Agent Loop 的四个关键位置触发一组按顺序注册的回调。

```text
用户输入
  ↓ UserPromptSubmit
调用模型
  ↓
模型请求工具
  ↓ PreToolUse
执行工具
  ↓ PostToolUse
模型准备结束
  ↓ Stop
返回用户
```

## 1. Hook 注册

所有 Hook 由 [HookManager](C:/02-study/MyProjects/ZCLI/zcli/hooks.py) 管理：

```python
self._hooks = {
    "UserPromptSubmit": [],
    "PreToolUse": [],
    "PostToolUse": [],
    "Stop": [],
}
```

注册方式：

```python
agent.hooks.register(
    USER_PROMPT_SUBMIT,
    my_hook,
)
```

默认按注册顺序执行，也可以插到最前面：

```python
register(event, callback, prepend=True)
```

权限 Hook 就是通过 `prepend=True` 注册在 `PreToolUse` 首位，避免普通扩展先于权限检查执行。

## 2. HookContext

每次触发 Hook，Agent 会创建一个 `HookContext`，把当前运行信息传给回调：

```python
@dataclass
class HookContext:
    event: str
    agent: Any
    session: Any
    query: str
    tool_name: str
    tool_input: dict
    output: str | None
    response_text: str
    emit: Callable
```

不同事件使用不同字段：

| 事件 | 主要字段 |
|---|---|
| UserPromptSubmit | `query`、`session` |
| PreToolUse | `tool_name`、`tool_input` |
| PostToolUse | `tool_name`、`tool_input`、`output` |
| Stop | `response_text`、`session` |

## 3. HookResult

Hook 使用 `HookResult` 表达它希望 Agent 做什么：

```python
@dataclass
class HookResult:
    blocked: bool = False
    reason: str = ""
    additional_context: str = ""
    updated_output: str | None = None
    continuation: str = ""
```

含义分别是：

- `blocked`：阻止用户输入或工具执行
- `reason`：阻断原因
- `additional_context`：向本轮 Prompt 注入上下文
- `updated_output`：替换工具输出
- `continuation`：阻止 Agent 停止，再执行一轮模型

## 4. UserPromptSubmit

在用户消息写入 Session 前触发，位于 [agent.py](C:/02-study/MyProjects/ZCLI/zcli/agent.py)。

```python
submit = self.hooks.trigger(
    USER_PROMPT_SUBMIT,
    HookContext(query=query, ...),
)
```

如果被阻断：

```python
if submit.blocked:
    return submit.reason
```

如果包含附加上下文，则与记忆和用户输入一起发送：

```text
相关长期记忆

Hook 附加上下文

用户原始问题
```

示例：

```python
def project_rule(context):
    return HookResult(
        additional_context="禁止修改 generated/ 目录。"
    )
```

## 5. PreToolUse

模型产生 `tool_use` 后、工具真正执行前触发：

```python
pre = hooks.trigger(PRE_TOOL_USE, context)

if pre.blocked:
    output = pre.reason
else:
    output = tools.execute(...)
```

默认的 `permission_hook` 就在这里检查：

- Bash 危险命令
- 需要用户确认的命令
- 文件路径是否逃出工作区

如果拒绝，工具不会执行，但仍会产生一个 `tool_result` 返回模型：

```text
Permission denied: path escapes workspace
```

这样模型能知道执行失败，并调整后续行为。

## 6. PostToolUse

工具真实执行完成后触发：

```python
post = hooks.trigger(
    POST_TOOL_USE,
    HookContext(output=output, ...),
)
```

PostToolUse 可以观察或替换输出：

```python
def redact_secret(context):
    if context.output:
        return HookResult(
            updated_output=context.output.replace(
                "secret", "***"
            )
        )
```

替换后的内容才会：

- 显示在终端
- 写入 Session
- 返回给模型
- 参与大结果落盘和上下文压缩

如果工具被 PreToolUse 阻断，则不会触发 PostToolUse。

## 7. Stop

当模型不再请求工具、Agent 准备结束时触发：

```python
stop = hooks.trigger(STOP, context)
```

普通 Stop Hook返回 `None`，Agent 正常结束。

如果返回 continuation：

```python
def review_answer(context):
    return HookResult(
        continuation="检查刚才的答案并修正遗漏。"
    )
```

Agent 会把它追加为一条用户消息，再调用模型一次。

为了防止无限循环，每个用户轮次只允许 Stop Hook 请求一次续跑：

```text
第一次准备停止
→ Stop Hook 请求继续
→ 模型再执行一轮
→ 第二次准备停止时不再触发 Stop Hook
→ 正常返回
```

## 8. 字符串简写

为了兼容 `learn-claude-code` s04 的简单返回方式，Hook 可以直接返回字符串：

| 事件 | 字符串作用 |
|---|---|
| UserPromptSubmit | 注入上下文 |
| PreToolUse | 阻断原因 |
| PostToolUse | 替换工具输出 |
| Stop | 续跑 Prompt |

例如：

```python
def block_delete(context):
    if context.tool_name == "bash":
        return "禁止执行这个 Bash 命令"
```

复杂 Hook 建议返回明确的 `HookResult`。

## 9. Hook 异常

HookManager 会捕获回调异常。

对于 `PreToolUse`：

```text
Hook 异常 → fail closed → 阻止工具执行
```

这是为了防止权限 Hook 自身出错后，危险操作反而被放行。

其他事件异常则：

```text
输出 Hook 错误日志 → 主流程继续
```

因此日志、输出检查或 Stop 收尾 Hook 出错，不会直接破坏整个用户任务。