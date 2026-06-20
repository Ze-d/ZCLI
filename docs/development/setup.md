# 环境搭建

## 前置条件

- Python 3.11+
- Git
- 一个 Anthropic-compatible API key（Anthropic / DeepSeek / GLM 等）

## 步骤

```bash
# 1. 克隆仓库
git clone <repo-url>
cd ZCLI

# 2. 创建虚拟环境
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 3. 可编辑安装
pip install -e .

# 4. 可选：安装开发依赖
pip install -e ".[dev]"

# 5. 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的 API key 和模型选择
```

## IDE 配置

推荐 VS Code + Python 扩展。项目已配置 `pyproject.toml` 中的 pytest。

```json
// .vscode/settings.json
{
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": ["tests"]
}
```
