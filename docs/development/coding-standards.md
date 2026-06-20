# 编码规范

## 风格

- 遵循 [PEP 8](https://peps.python.org/pep-0008/)
- 使用 `from __future__ import annotations` 延迟注解求值
- 类型注解用于公开接口（函数签名、类属性）
- 字符串拼接优先使用 f-string

## 命名约定

| 类型 | 约定 | 示例 |
|------|------|------|
| 模块 | `snake_case` | `memory.py`, `cli.py` |
| 类 | `PascalCase` | `Agent`, `ToolRegistry`, `MemoryStore` |
| 函数/方法 | `snake_case` | `run_turn()`, `_compact_if_needed()` |
| 私有方法 | `_underscore` | `_extract_memories()`, `_estimate_size()` |
| 常量 | `UPPER_SNAKE` | `_RESET`, `_BRIGHT_CYAN` |
| 变量 | `snake_case` | `term_width`, `turn_start` |

## Docstring

- 公开函数/类需要 docstring
- 使用 `"""简短描述."""` 格式
- 复杂逻辑加行内注释说明"为什么"而非"是什么"

## 项目特定

- 使用 `Path` 而非 `str` 处理文件路径
- dataclass 用 `frozen=True` 实现不可变配置
- 工具函数返回 `str`（成功消息或错误信息）
- 长方法内的 `# ── section ──` 注释分隔逻辑块
