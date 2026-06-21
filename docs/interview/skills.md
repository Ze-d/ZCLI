# Skill Loading 面试讲解

## 1. 一句话介绍

我在 ZCLI 中实现了一套两级 Skill 加载机制：System Prompt 只注入 Skill 的名称和描述，模型判断相关后再调用 `load_skill` 加载完整 `SKILL.md`，从而避免无关知识长期占用上下文。

这套设计参考了 `learn-claude-code` s07，并增加了运行时重扫、Catalog 预算、重复名称诊断、BOM 兼容和目录逃逸防护。

## 2. Skill 解决什么问题

个人 Agent 通常需要遵守很多项目规范，例如：

- 代码审查流程；
- API 设计规则；
- 数据库规范；
- 发布流程；
- 团队编码约定。

最简单的做法是把所有规范全文放入 System Prompt，但这会产生三个问题：

1. 每次请求都重复消耗 token；
2. 当前任务只与少量规范相关，大部分内容是噪声；
3. Skill 越多，Prompt 越长，模型越难关注当前目标。

因此我使用渐进式加载：

```text
第一级：Catalog
名称 + 描述常驻 System Prompt
        ↓ 模型判断相关
第二级：Content
调用 load_skill 加载完整 SKILL.md
```

## 3. 目录约定

每个 Skill 是工作区 `skills/` 下的一个目录：

```text
<workspace>/skills/
  review-style/
    SKILL.md
    agents/openai.yaml
  api-design/
    SKILL.md
```

ZCLI 当前只要求 `SKILL.md`：

```markdown
---
name: review-style
description: Review text or source files using an evidence-based format.
---

# Review Style

1. Read the target file.
2. Report evidence-based findings.
```

Frontmatter 中：

- `name` 是注册表键和 `load_skill` 参数；
- `description` 是模型判断何时加载 Skill 的主要依据；
- Markdown 正文只在 Skill 被加载后进入上下文。

---

# 核心实现

## 4. Skill 数据模型

`zcli/skills.py` 使用不可变数据类保存扫描结果：

```python
@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    directory: Path
    manifest: Path
    content: str
```

字段分成两类：

- Catalog 元数据：`name`、`description`；
- 加载阶段数据：`directory`、`manifest`、`content`。

这种分离让 Catalog 不需要读取或暴露完整正文，但注册表仍然能在工具调用时快速返回内容。

## 5. SkillRegistry 扫描流程

Agent 启动时创建：

```python
self.skills = SkillRegistry(settings.workspace / "skills")
```

扫描流程：

```text
遍历 skills/ 的直接子目录
  ↓
检查 SKILL.md 是否存在
  ↓
读取 UTF-8 / UTF-8 BOM
  ↓
解析 YAML frontmatter
  ↓
校验名称和目录边界
  ↓
写入 name → Skill 注册表
```

当前只扫描直接子目录，避免无限递归和意外加载深层文件。

## 6. Frontmatter 解析与回退

标准格式由三条横线包围：

```text
---
name: review-style
description: Review source files
---
```

解析使用 `yaml.safe_load()`，避免 YAML 构造任意 Python 对象。

缺少 frontmatter 时不会直接拒绝，而是回退：

- name 使用目录名；
- description 使用正文第一条非空标题或文本；
- 空正文使用 `Instructions from <directory>`。

未闭合 frontmatter、非 Mapping YAML 或损坏 YAML 会被记录为扫描错误，该 Skill 被跳过。

## 7. 第一级：Catalog 注入

每次组装 System Prompt 时调用：

```python
skill_catalog = self.skills.catalog()
```

得到：

```text
Skills catalog:
- review-style: Review text or source files using an evidence-based format
- api-design: Design stable HTTP APIs

When a skill is relevant, call load_skill(name) before following its instructions.
```

关键点是 Catalog 没有 Skill 正文。

例如 `review-style` 正文中的固定标记：

```text
SKILL-REVIEW-OK:
```

在调用 `load_skill` 前不会出现在 System Prompt 中。自动化测试专门验证了这个不变量。

## 8. Catalog 预算

Catalog 默认最多 8,000 字符：

```python
SkillRegistry(skills_dir, catalog_budget=8_000)
```

达到预算后追加：

```text
- ... additional skills omitted by catalog budget
```

这样 Skill 数量增长时，不会无限扩大固定 Prompt。

当前使用字符预算而非精确 tokenizer，是一种低成本近似。更成熟的实现可以按模型 tokenizer 计算预算，或基于当前任务筛选 Catalog。

## 9. 第二级：load_skill

模型从 Catalog 判断 Skill 相关后调用：

```json
{
  "name": "review-style"
}
```

工具链：

```text
模型生成 load_skill tool_use
  ↓
PreToolUse Hook
  ↓
ToolRegistry.execute()
  ↓
SkillRegistry.load(name)
  ↓
完整 SKILL.md 作为 tool_result
  ↓
模型下一轮按 Skill 指令继续工作
```

返回内容包含：

```text
<skill>
Name: review-style
Directory: C:\...\skills\review-style

<完整 SKILL.md>
</skill>
```

目录信息让 Skill 可以继续指导模型读取同目录下的 `references/`、`scripts/` 或 `assets/`。

## 10. 为什么通过注册表加载

`load_skill` 不接受文件路径，只接受注册表名称：

```python
skill = self._skills.get(name)
```

这避免了危险实现：

```python
# 不采用
Path("skills") / user_input / "SKILL.md"
```

如果直接拼接用户输入，攻击者可能传入 `../../secret` 进行路径遍历。

注册表方案的安全边界是：只有扫描阶段确认过的 Skill 才能被加载。缺失 Skill 返回：

```text
Skill not found: definitely-missing-skill. Available: review-style
```

模型可以看到失败事实，但不能获得任何伪造正文。

## 11. 运行时热重扫

`catalog()` 和 `load()` 默认都会重新执行扫描：

```python
catalog(refresh=True)
load(name, refresh=True)
```

因此 Agent 启动后新增或修改 `SKILL.md`，下一轮模型调用或加载时即可生效，不需要重启进程。

代价是每轮 System Prompt 组装都会扫描目录。当前个人项目的 Skill 数量较少，这个成本可接受；规模扩大后可以使用 mtime 缓存或文件监听器。

## 12. 错误隔离和重复名称

单个 Skill 失败不会让整个 Agent 启动失败。扫描错误记录在：

```python
registry.errors
```

`/skills` 会显示 Catalog 和错误信息。

处理策略：

- 损坏 YAML：跳过；
- 未闭合 frontmatter：跳过；
- 重复 name：保留按目录排序扫描到的第一个，后续记录错误；
- 没有 SKILL.md：忽略目录；
- Skill 目录解析后逃出 skills 根目录：拒绝。

这属于“局部失败、整体可用”的设计。

---

# 与其他模块的关系

## 13. Skill 与 Tool Loop

Skill 并不是启动时直接执行的一段 Python 代码，而是一份提供给模型的工作指令。

模型加载 Skill 后，仍需通过普通工具完成操作：

```text
load_skill
  → read_file
  → glob
  → bash
  → write_file / edit_file
```

因此 Skill 复用了已有 Tool Loop，没有引入第二套执行引擎。

## 14. Skill 与权限系统

Skill 内容不能绕过权限：

```text
Skill 要求删除文件
  ↓
模型产生 bash / edit_file 调用
  ↓
PreToolUse permission_hook
  ↓
允许、询问或拒绝
```

Skill 是低权限的指令性知识，System Prompt、Hook 和 PermissionPolicy 仍然是更高层的约束。

## 15. Skill 与 Context Compact

Catalog 常驻 System Prompt，但完整 Skill 通过 tool_result 进入消息历史。

因此它会自然参与现有压缩流程：

```text
Skill 正文较小 → 保留在 messages
Skill 正文较大 → 大结果落盘并保留预览
历史较旧 → micro compact / snip compact
上下文超限 → LLM 摘要
```

两级加载解决“不要提前加载什么”，Context Compact 解决“加载以后何时压缩”。

## 16. Skill 与 Memory 的区别

| | Skill | Memory |
|---|---|---|
| 内容 | 可复用工作流和规范 | 用户偏好、反馈、项目事实 |
| 来源 | 开发者维护的 SKILL.md | 显式 remember 或自动提取 |
| 选择方式 | Catalog + 模型调用 load_skill | 关键词相关性检索 |
| 生命周期 | 工作区级 | 数据目录级、跨 Session |
| 是否可执行 | 指导模型调用工具 | 提供上下文事实 |

Skill 告诉 Agent“应该怎么做”，Memory 告诉 Agent“用户和项目是什么样”。

---

# 工程取舍与面试追问

## 17. 为什么不把所有 Skill 全文放进 System Prompt

全文常驻会增加固定 token 成本，还会把无关规范带入当前任务。Catalog 只提供触发信息，完整内容按需付费，更符合渐进式披露原则。

## 18. 为什么每次都重扫

个人 Agent 的 Skill 数量较少，目录扫描成本低。热重扫换来了开发体验：修改 Skill 后立即生效。

如果 Skill 达到几百个，我会：

1. 缓存目录 mtime；
2. 使用文件系统 watcher；
3. 只在变更时重建注册表；
4. 根据 query 选择一部分 Catalog 注入。

## 19. 当前不足

面试时应主动说明：

1. 仅支持工作区 `skills/`，没有用户级、插件、MCP 和内置来源；
2. 只解析 name/description，没有 `allowed-tools`、`paths`、`model`、`hooks`；
3. 只支持 inline 加载，没有 forked Skill 或独立上下文；
4. Catalog 是字符预算，不是 token 预算；
5. Skill 正文没有版本和依赖管理；
6. 热重扫没有缓存，大规模目录会增加 I/O。

## 20. 常见面试追问

### Q1：模型怎么知道什么时候加载 Skill？

System Prompt 中一直存在名称和 description。description 必须同时说明 Skill 做什么以及什么场景应该使用，模型据此决定是否调用 `load_skill`。

### Q2：如何证明是按需加载，而不是正文已经在 Prompt 中？

测试在 Skill 正文放一个唯一 marker。第一次模型请求的 System Prompt 只能看到名称和描述；调用 `load_skill` 后，下一轮 tool_result 才出现 marker。

### Q3：如何防止路径遍历？

加载阶段不拼接用户路径，只做注册表精确查找。扫描阶段还会对 `resolve()` 后的目录执行 `is_relative_to(skills_root)` 检查。

### Q4：如果两个目录声明同一个 name 怎么办？

按目录名排序扫描，保留第一个，后续重复项记录诊断并跳过。这样结果是确定性的，不会因文件系统遍历顺序随机覆盖。

### Q5：Skill 能不能自动获得额外权限？

不能。Skill 只是模型指令。它产生的文件或 Shell 操作仍然必须通过 PreToolUse 权限 Hook。

### Q6：为什么把完整 Skill 放在 tool_result，而不是重新拼 System Prompt？

tool_result 与模型的工具调用形成清晰因果关系，而且只影响当前消息历史。System Prompt 保持稳定，有利于 Prompt Cache，也避免每次加载都重建全局指令。

### Q7：如何支持 Skill 引用其他文件？

load_skill 返回 Skill 目录。SKILL.md 可以明确告诉模型何时通过 read_file 加载 `references/xxx.md`，或运行 `scripts/xxx.py`。这些访问继续走普通工具和权限系统。

---

# 面试口述版本

## 21. 1 分钟版本

> 我在 ZCLI 里实现了参考 Claude Code 的两级 Skill 加载。工作区下每个 skills 子目录有一个 SKILL.md，启动和每轮 Prompt 组装时只扫描 name 和 description，形成最多 8KB 的 Catalog。模型根据描述判断相关后调用 load_skill，完整正文才作为 tool_result 进入消息历史。
>
> 加载阶段只按注册表名称查找，不直接拼用户路径，所以可以避免路径遍历。扫描还处理 YAML 错误、重名、目录逃逸和 UTF-8 BOM，单个坏 Skill 不影响其他 Skill。Catalog 和 load 都支持热重扫，因此运行时新增 Skill 不需要重启。
>
> Skill 只提供工作指令，后续操作仍走现有 Tool Loop、Hook 和权限系统；完整正文也会参与上下文压缩。当前边界是只支持工作区 inline Skill，还没有用户级、多来源和 forked Skill。

## 22. 2 分钟版本

> Skill Loading 解决的是知识和工作流不能全部常驻 Prompt 的问题。如果把代码审查、API 设计、数据库规范全文都放进 System Prompt，每次请求都会重复消耗 token，而且无关内容会干扰模型。
>
> 所以我做了两级加载。第一级是 Catalog，SkillRegistry 扫描 workspace/skills 下的 SKILL.md，用 yaml.safe_load 解析 name 和 description，只把元数据放进 System Prompt，并限制为 8KB。第二级是 load_skill 工具，模型认为某个 Skill 相关时才调用，注册表返回完整正文和 Skill 目录，下一轮模型再按说明调用 read_file、bash 或 edit_file。
>
> 安全上，我不允许 load_skill 接收任意路径，而是做 name 到 Skill 的精确映射；扫描时还检查 resolve 后的目录必须位于 skills 根目录。坏 YAML、重复名称或非法目录只会产生诊断，不会拖垮整个 Agent。
>
> 它和其他模块是组合关系：权限 Hook 仍然控制 Skill 指导的工具调用，Context Compact 管理加载后的正文，Memory 保存用户和项目事实。测试通过唯一 marker 验证正文在首次 System Prompt 中不存在，只有 load_skill 的 tool_result 才出现。
>
> 当前还没有多来源、allowed-tools、条件 paths 和 forked Skill。下一步会增加来源优先级、mtime 缓存，以及基于 query 的 Catalog 选择。
