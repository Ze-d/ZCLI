# 常用命令

## 开发

```bash
# 运行 Agent（交互模式）
zcli
zcli --workspace /path/to/project
zcli --session my-session
zcli --new --session fresh-start

# 列出会话
zcli --list-sessions

# 通过 python -m 运行
python -m zcli
```

## 测试

```bash
# 运行全部测试
pytest

# 详细输出
pytest -v

# 按模块筛选
pytest tests/test_agent.py -v
pytest tests/test_tools.py -v

# 单测 + 覆盖率
pip install pytest-cov
pytest --cov=zcli --cov-report=term-missing
```

## 代码质量

```bash
# Ruff 检查（如已安装）
pip install ruff
ruff check zcli/

# 类型检查（如已安装 mypy）
pip install mypy
mypy zcli/
```

## 包管理

```bash
# 重新安装（代码修改后）
pip install -e .

# 查看已安装版本
pip show zcli-agent
```
