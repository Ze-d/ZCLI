# 环境变量

所有配置通过 `.env` 文件或系统环境变量设置。

## 完整列表

| 变量 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `ANTHROPIC_API_KEY` | 是 | — | API 密钥（Anthropic SDK 自动读取） |
| `MODEL_ID` | 否 | `claude-sonnet-4-6` | 模型标识符 |
| `ANTHROPIC_BASE_URL` | 否 | `https://api.anthropic.com` | API 端点，切换厂商时设置 |
| `ZCLI_WORKSPACE` | 否 | 当前目录 | Agent 默认工作区 |
| `ZCLI_DATA_DIR` | 否 | `<workspace>/.zcli` | 会话和记忆存储目录 |
| `ZCLI_CONTEXT_LIMIT` | 否 | `50000` | 触发上下文压缩的 token 阈值 |
| `FALLBACK_MODEL_ID` | 否 | — | 连续 529 后使用的备用模型 |
| `ZCLI_MAX_TOKENS` | 否 | `8000` | 常规模型输出上限 |
| `ZCLI_ESCALATED_MAX_TOKENS` | 否 | `16000` | 首次输出截断后的重试上限 |
| `ZCLI_MAX_RETRIES` | 否 | `3` | 429/529 最大调用次数 |
| `ZCLI_MAX_RECOVERY_RETRIES` | 否 | `2` | 扩容后仍截断时的续写次数 |

## 配置优先级

1. 系统环境变量（最高）
2. `<workspace>/.zcli/config.env`
3. `~/.zcli/config.env`
4. `<workspace>/.env`
5. 代码默认值（最低）

## 多厂商配置示例

```bash
# Anthropic (默认)
ANTHROPIC_BASE_URL=https://api.anthropic.com
MODEL_ID=claude-sonnet-4-6

# DeepSeek
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
MODEL_ID=deepseek-chat

# MiniMax
ANTHROPIC_BASE_URL=https://api.minimax.chat/anthropic
MODEL_ID=MiniMax-M1

# GLM (智谱)
ANTHROPIC_BASE_URL=https://open.bigmodel.cn/api/paas/v4/anthropic
MODEL_ID=glm-4

# Kimi (月之暗面)
ANTHROPIC_BASE_URL=https://api.moonshot.cn/anthropic
MODEL_ID=kimi-latest
```
