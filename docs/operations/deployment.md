# 部署

## 方式一：本地 pip 安装

```bash
pip install -e .
zcli
```

## 方式二：直接运行

```bash
python -m zcli
```

## 方式三：打包分发

```bash
pip install build
python -m build
# dist/ 下生成 .tar.gz 和 .whl
pip install dist/zcli_agent-0.1.0-py3-none-any.whl
```

## 生产注意事项

- `.env` 中 API key 注意权限（不要提交到 git）
- `.zcli/` 目录包含对话历史，注意隐私
- 如使用 DeepSeek 等第三方 API，确认 `ANTHROPIC_BASE_URL` 正确
- 超长会话建议定期 `/new` 避免上下文膨胀
