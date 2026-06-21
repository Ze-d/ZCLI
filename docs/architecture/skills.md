# Skill 两级加载

ZCLI 参考 `learn-claude-code` s07，把项目规范和工作流组织为按需加载的 Skill，避免把所有说明全文塞进每次模型请求。

## 目录约定

```text
<workspace>/skills/
  code-review/SKILL.md
  api-design/SKILL.md
```

`SKILL.md` 可以包含 YAML frontmatter：

```markdown
---
name: code-review
description: Review Python code for correctness and security
---

# Instructions
1. Read the changed files.
2. Prioritize correctness and security findings.
```

当前解析 `name` 和 `description`。没有 frontmatter 时，名称回退为目录名，描述回退为正文第一条非空标题或文本。

## 两级加载

### 第一级：Catalog

每次组装 System Prompt 时，`SkillRegistry.catalog()` 重扫目录，只注入名称与描述：

```text
Skills catalog:
- code-review: Review Python code for correctness and security

When a skill is relevant, call load_skill(name) before following its instructions.
```

Catalog 默认限制为 8,000 字符，完整正文不会提前进入 Prompt。

### 第二级：完整内容

模型判断 Skill 相关后调用：

```json
{"name": "code-review"}
```

`load_skill` 只按注册表名称查找，不接受任意文件路径。完整 `SKILL.md` 作为 tool_result 进入当前消息历史，同时包含 Skill 目录，方便后续读取 `references/`、`scripts/` 或 `assets/`。

## 运行时重扫与诊断

Catalog 和 `load_skill` 默认都会重新扫描 `<workspace>/skills/`，运行期间新增或修改 Skill 无需重启。

- 损坏 YAML、未闭合 frontmatter：跳过并记录错误；
- 重复 `name`：保留按目录排序扫描到的第一个，记录重复项；
- 逃出 skills 根目录的目录链接：拒绝；
- 缺少 `SKILL.md`：忽略。

CLI 使用 `/skills` 查看 Catalog 和扫描诊断。

## 安全与上下文

- 用户输入只做注册表精确查找，不拼接路径；
- Catalog 只包含元数据，正文不会泄漏进 System Prompt；
- Skill tool_result 接受现有大结果落盘和上下文压缩；
- Skill 指导的后续文件或 Shell 操作仍经过现有权限边界。

## 当前边界

- 仅扫描当前工作区 `skills/`，尚未合并用户级、插件、MCP 或内置 Skill；
- 仅支持 inline 加载，不支持 `context: fork`；
- 尚未实现 `allowed-tools`、`paths`、`model`、`hooks` 等高级字段；
- Catalog 使用字符预算，不是精确 token 预算；
- Skill 内容不能提升权限，也不能覆盖 System Prompt。

