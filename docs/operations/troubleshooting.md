# 故障排查

## 启动问题

| 症状 | 原因 | 解决 |
|------|------|------|
| `zcli: command not found` | 未安装 | `pip install -e .` |
| `ModuleNotFoundError: anthropic` | 依赖缺失 | `pip install -e .` |
| `ImportError: zcli` | 可编辑安装失效 | 重新 `pip install -e .` |

## API 问题

| 症状 | 原因 | 解决 |
|------|------|------|
| `AuthenticationError` | API key 未设置或错误 | 检查 `ANTHROPIC_API_KEY` 环境变量或 `.env` |
| `NotFoundError` 或 404 | `MODEL_ID` 无效 | 检查模型名拼写 |
| 连接超时 | 网络或 `ANTHROPIC_BASE_URL` 不对 | 确认 endpoint 可达 |
| DeepSeek 返回格式异常 | DeepSeek 的 Anthropic 兼容层差异 | 尝试换模型或厂商 |

## Token 问题

| 症状 | 原因 | 解决 |
|------|------|------|
| 回复截断 | `max_tokens=8000` 不够 | 调高 `max_tokens`（需改代码） |
| 上下文溢出 | 会话太长 | 调低 `ZCLI_CONTEXT_LIMIT` 或手动 `/new` |

## 调试

```bash
# 开启 Anthropic SDK 日志
export ANTHROPIC_LOG=debug
zcli

# 查看会话文件
cat .zcli/sessions/default.json

# 查看记忆
cat .zcli/memory/MEMORY.md
```
