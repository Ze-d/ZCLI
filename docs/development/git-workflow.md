# Git 工作流

## 分支策略

```
main          ← 稳定分支，可发布
feature/*     ← 功能开发分支
fix/*         ← 缺陷修复分支
```

## 提交规范

```
<type>: <简短描述>

<详细说明（可选）>

Co-Authored-By: Claude <noreply@anthropic.com>
```

类型: `feat` `fix` `docs` `refactor` `test` `chore`

## 示例

```
feat: add context compaction for long sessions

When messages exceed context_limit (50k tokens), automatically
summarize older messages to keep the session within bounds.

Co-Authored-By: Claude <noreply@anthropic.com>
```

## 注意事项

- 不直接在 `main` 上开发
- 不提交 `.env` 文件（已在 `.gitignore`）
- 不提交 `.zcli/` 数据目录
- PR 合并前确保全部测试通过
