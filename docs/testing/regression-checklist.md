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
- [ ] 上下文压缩触发（>8 条消息 + 超限）
- [ ] 记忆自动抽取
- [ ] 错误不崩溃

## 安全

- [ ] `rm -rf /` 被拒绝
- [ ] `../../etc/passwd` 路径逃逸被拒绝
- [ ] 工作区内正常文件操作通过

## 测试

- [ ] `pytest` 10/10 通过
