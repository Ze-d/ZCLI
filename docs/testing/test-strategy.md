# 测试策略

## 测试层次

```
┌─────────────────────────────┐
│  手动功能测试 (Prompt 验证)  │  ← docs/PROMPT_FUNCTIONAL_TESTS.md
├─────────────────────────────┤
│  集成测试 (test_agent.py)    │  ← tool loop、compact、恢复、memory
├─────────────────────────────┤
│  单元测试 (test_*.py)        │  ← tasks、todos、hooks、context、recovery、memory、session、tools
└─────────────────────────────┘
```

## 当前覆盖

| 模块 | 测试数 | 覆盖内容 |
|------|--------|----------|
| `agent.py` | — | session 持久化、完整 compact、max_tokens 扩容、reactive compact |
| `context.py` | — | 四层执行顺序、大结果落盘、预算、工具配对、transcript |
| `recovery.py` | — | 429/529 重试、fallback model、非瞬时错误、超限识别 |
| `hooks.py` | — | 注册顺序、上下文合并、fail-closed、四事件集成、Stop 防循环 |
| `tasks.py` | — | DAG 依赖、状态机、解锁、缺失依赖、跨实例恢复 |
| TodoWrite | — | 输入校验、Session 持久化、system prompt 注入、三轮提醒 |
| `memory.py` | 2 | remember+retrieve, save_extracted JSON |
| `session.py` | 2 | round-trip, path escape 拒绝 |
| `tools.py` | 2 | 工作区隔离, remember 工具 |

## 推荐补充

1. **PermissionPolicy 单元测试** — 危险命令拒绝、路径逃逸检测
2. **CLI 集成测试** — `--help` `--list-sessions` `--new` 参数
3. **CLI 集成测试** — REPL 输入、异常显示和退出行为
4. **属性测试** — 随机消息序列压缩后仍满足工具配对不变量
