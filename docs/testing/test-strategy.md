# 测试策略

## 测试层次

```
┌─────────────────────────────┐
│  手动功能测试 (Prompt 验证)  │  ← docs/PROMPT_FUNCTIONAL_TESTS.md
├─────────────────────────────┤
│  集成测试 (test_agent.py)    │  ← 4 tests: session, compact, memory
├─────────────────────────────┤
│  单元测试 (test_*.py)        │  ← 6 tests: memory, session, tools
└─────────────────────────────┘
```

## 当前覆盖

| 模块 | 测试数 | 覆盖内容 |
|------|--------|----------|
| `agent.py` | 4 | session 持久化、compact 触发/切分/阈值 |
| `memory.py` | 2 | remember+retrieve, save_extracted JSON |
| `session.py` | 2 | round-trip, path escape 拒绝 |
| `tools.py` | 2 | 工作区隔离, remember 工具 |

## 推荐补充

1. **PermissionPolicy 单元测试** — 危险命令拒绝、路径逃逸检测
2. **CLI 集成测试** — `--help` `--list-sessions` `--new` 参数
3. **Config 测试** — 环境变量优先级、默认值
4. **端到端测试** — mock Anthropic client，验证完整 tool loop
