# Hooks 生命周期扩展

ZCLI 参考 `learn-claude-code` s04，将横切行为挂在稳定的 Agent Loop 周围，而不是不断向循环中加入权限、日志和收尾分支。

## 四个核心事件

| 事件 | 触发时机 | 支持的行为 |
|---|---|---|
| `UserPromptSubmit` | 用户输入进入 Session 前 | 阻断输入、注入附加上下文 |
| `PreToolUse` | 每个工具执行前 | 权限检查、审计、阻断工具 |
| `PostToolUse` | 工具成功分发后 | 检查或改写返回结果 |
| `Stop` | 模型不再请求工具、Agent 即将返回前 | 收尾；请求一次模型续跑 |

核心类型位于 `zcli/hooks.py`：

- `HookManager`：按注册顺序保存和触发回调；
- `HookContext`：携带 Session、query、工具名、输入、输出和 `emit`；
- `HookResult`：表达阻断、附加上下文、更新输出或 Stop continuation。

## 注册示例

```python
from zcli.hooks import POST_TOOL_USE, USER_PROMPT_SUBMIT, HookResult


def inject_project_rule(context):
    return HookResult(additional_context="本项目禁止修改 generated/ 目录。")


def redact_output(context):
    if context.output and "secret" in context.output:
        return HookResult(updated_output=context.output.replace("secret", "***"))


agent.hooks.register(USER_PROMPT_SUBMIT, inject_project_rule)
agent.hooks.register(POST_TOOL_USE, redact_output)
```

为了兼容 s04 的简单返回约定，回调也可以返回字符串：

| 事件 | 字符串含义 |
|---|---|
| `UserPromptSubmit` | 附加到本轮用户上下文 |
| `PreToolUse` | 阻断原因 |
| `PostToolUse` | 替换后的工具输出 |
| `Stop` | 注入 Session 并续跑一次的 Prompt |

复杂 Hook 应优先返回 `HookResult`，避免语义歧义。

## 权限 Hook 与安全不变量

`permission_hook` 是 Agent 创建时注册的第一个 `PreToolUse` Hook。它读取原始工具名和参数，在分发前执行 `PermissionPolicy`：

```text
tool_use
  → PreToolUse(permission_hook)
      ├─ deny → 生成 Permission denied tool_result
      └─ allow → ToolRegistry.execute(permission_checked=True)
```

扩展 Hook 没有“强制 allow”能力，因此不能覆盖默认 deny/ask。`ToolRegistry.execute()` 在 Agent 之外直接调用时仍会独立检查权限，防止绕过 Hook 执行危险命令。

## 异常策略

- `PreToolUse` Hook 抛异常时 fail closed：阻止工具，避免安全检查异常导致放行；
- 其他事件异常会通过 `emit` 报告，然后继续主流程；
- 回调返回非法类型同样按 Hook 异常处理；
- Hook 列表触发前会复制，因此回调内注册/注销不会改变当前轮迭代。

## Stop 防循环

Stop Hook 可以返回 continuation，请求模型检查或补充答案。ZCLI 每个用户轮次最多执行一次 Stop continuation：

```text
模型准备停止
  → Stop Hook 返回 continuation
  → 注入一条 user 消息并继续
  → 模型再次停止
  → 不再重复触发 Stop Hook，正常返回
```

这对应 Claude Code 的 `stopHookActive` 思路，避免 Hook 自己制造无限循环。

## 当前边界

- 当前实现四个核心事件，不是 Claude Code 的完整事件集合；
- Hook 通过 Python API 注册，尚无 `settings.json` 或外部脚本配置；
- `PostToolUse` 仅在工具实际执行后触发，被 `PreToolUse` 阻断的工具不会触发；
- Hook 状态存在于当前 Agent 进程，不单独持久化。

