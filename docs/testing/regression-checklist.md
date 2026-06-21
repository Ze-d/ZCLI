# 回归检查清单

发布前逐项验证：

## 核心功能

- [ ] `zcli` 启动显示 banner
- [ ] `zcli --help` 正常
- [ ] `zcli --list-sessions` 正常
- [ ] `zcli --new --session test` 创建新会话
- [ ] `/exit` `/quit` 退出
- [ ] `/memory` 显示记忆
- [ ] `/sessions` 列出会话

## Agent 功能

- [ ] 单轮对话正常
- [ ] 多轮 tool loop 正常（bash/read_file/write_file）
- [ ] 超大工具结果写入 `.zcli/tool-results/`，消息仅保留路径和预览
- [ ] 超过 50 条消息时裁剪中间历史且工具调用保持配对
- [ ] 旧工具结果被压缩，最近 3 个保持完整
- [ ] 超过 `ZCLI_CONTEXT_LIMIT` 后生成 `[Compacted]` 摘要并保存 transcript
- [ ] prompt-too-long 后执行 reactive compact 并重试
- [ ] 429/529 自动退避，配置 fallback 时连续 529 可切换模型
- [ ] `max_tokens` 首次截断后提高输出上限，仍截断则续写
- [ ] UserPromptSubmit 可注入上下文
- [ ] PreToolUse 可阻断工具，权限拒绝作为 tool_result 返回
- [ ] PostToolUse 可检查或改写工具输出
- [ ] Stop Hook 最多请求一次续跑，不形成循环
- [ ] 复杂任务先调用 todo_write，Todo 状态随 Session 保存
- [ ] 三个非 Todo 工具调用后注入更新提醒
- [ ] Task Graph 能创建依赖、阻止提前认领并在完成上游后解锁
- [ ] 新 Session 通过 `/tasks` 恢复持久任务
- [ ] `/skills` 只显示名称和描述，不泄漏 SKILL.md 正文
- [ ] 相关任务先调用 load_skill，再遵守完整 Skill 指令
- [ ] 损坏或重名 Skill 产生诊断但不阻止其他 Skill 加载
- [ ] MCP stdio 完成 initialize、tools/list、tools/call，连接后工具池动态刷新
- [ ] Streamable HTTP 支持 JSON/SSE 响应，携带 Session ID 和协商后的协议版本
- [ ] HTTP 关闭发送 DELETE；URL、Header、超时与环境变量配置校验正确
- [ ] MCP 名称规范化无冲突，连接与 destructive 工具均经过审批
- [ ] `/mcp` 展示配置/连接状态，退出时子进程被回收
- [ ] 记忆自动抽取
- [ ] 错误不崩溃

## 安全

- [ ] `rm -rf /` 被拒绝
- [ ] `../../etc/passwd` 路径逃逸被拒绝
- [ ] 工作区内正常文件操作通过

## 测试

- [ ] `pytest` 全部通过
