import json
import sys
from pathlib import Path
from types import SimpleNamespace

from zcli.agent import Agent
from zcli.config import Settings
from zcli.mcp import MCPManager, load_mcp_config, normalize_mcp_name


SERVER = r'''
import json
import sys

for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if "id" not in message:
        continue
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "fixture", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [
            {"name": "echo.text", "description": "Echo input", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}, "annotations": {"readOnlyHint": True}},
            {"name": "deploy", "description": "Deploy", "inputSchema": {"type": "object", "properties": {}}, "annotations": {"destructiveHint": True}},
        ]}
    elif method == "tools/call":
        args = message["params"].get("arguments", {})
        result = {"content": [{"type": "text", "text": "echo:" + args.get("text", "deployed")}], "isError": False}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "missing"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
'''


def write_fixture(workspace: Path) -> None:
    server = workspace / "mcp_fixture.py"
    server.write_text(SERVER, encoding="utf-8")
    (workspace / ".mcp.json").write_text(json.dumps({
        "mcpServers": {
            "test.docs": {"command": sys.executable, "args": [str(server)]}
        }
    }), encoding="utf-8")


def test_config_and_name_normalization(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    workspace = tmp_path / "workspace"
    (workspace / ".zcli").mkdir(parents=True)
    (workspace / ".mcp.json").write_text('{"mcpServers":{"docs":{"command":"old"}}}', encoding="utf-8")
    (workspace / ".zcli" / "mcp.json").write_text('{"mcpServers":{"docs":{"command":"new","args":["x"]}}}', encoding="utf-8")

    configs, errors = load_mcp_config(workspace)

    assert not errors
    assert configs["docs"].command == "new"
    assert normalize_mcp_name("docs.search/v1") == "docs_search_v1"


def test_config_reports_normalized_collisions(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".mcp.json").write_text(json.dumps({"mcpServers": {
        "a.b": {"command": "one"},
        "a/b": {"command": "two"},
    }}), encoding="utf-8")

    configs, errors = load_mcp_config(workspace)

    assert list(configs) == ["a.b"]
    assert any("collides" in error for error in errors)


def test_cwd_escape_and_missing_environment_variable_fail_closed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.delenv("ZCLI_MISSING_MCP_TOKEN", raising=False)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".mcp.json").write_text(json.dumps({"mcpServers": {
        "escape": {"command": sys.executable, "args": ["x.py"], "cwd": ".."},
        "secret": {"command": sys.executable, "args": ["x.py"], "env": {"TOKEN": "${ZCLI_MISSING_MCP_TOKEN}"}},
    }}), encoding="utf-8")
    manager = MCPManager(workspace)

    assert "cwd escapes workspace" in manager.connect("escape")
    assert "environment variable ZCLI_MISSING_MCP_TOKEN is not set" in manager.connect("secret")


def test_real_stdio_discovery_call_annotations_and_close(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_fixture(workspace)
    manager = MCPManager(workspace)

    result = manager.connect("test.docs")

    assert "Discovered 2 tools" in result
    assert "mcp__test_docs__echo_text" in manager.tools
    definitions = {item["name"]: item for item in manager.definitions()}
    assert "(read-only)" in definitions["mcp__test_docs__echo_text"]["description"]
    assert manager.tools["mcp__test_docs__deploy"].destructive
    assert manager.call("mcp__test_docs__echo_text", {"text": "hello"}) == "echo:hello"
    manager.close()
    assert not manager.clients


class Block:
    def __init__(self, **values):
        self.values = values

    def model_dump(self, exclude_none=True):
        return self.values


class DynamicMessages:
    def __init__(self):
        self.tool_names = []
        self.calls = 0

    def create(self, **kwargs):
        if "tools" not in kwargs:
            return SimpleNamespace(content=[Block(type="text", text="[]")], stop_reason="end_turn")
        self.calls += 1
        self.tool_names.append({tool["name"] for tool in kwargs["tools"]})
        if self.calls == 1:
            return SimpleNamespace(content=[Block(type="tool_use", id="connect", name="connect_mcp", input={"name": "test.docs"})], stop_reason="tool_use")
        if self.calls == 2:
            return SimpleNamespace(content=[Block(type="tool_use", id="echo", name="mcp__test_docs__echo_text", input={"text": "agent"})], stop_reason="tool_use")
        return SimpleNamespace(content=[Block(type="text", text="完成")], stop_reason="end_turn")


def test_agent_rebuilds_dynamic_tool_pool_after_connect(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_fixture(workspace)
    messages = DynamicMessages()
    agent = Agent(
        Settings(workspace, tmp_path / "data", "fake", None),
        client=SimpleNamespace(messages=messages),
        interactive=False,
    )
    agent.tools.policy.confirm_action = lambda _: None
    session = agent.sessions.create("mcp")

    try:
        assert agent.run_turn(session, "连接并调用 MCP", emit=lambda _: None) == "完成"
        assert "mcp__test_docs__echo_text" not in messages.tool_names[0]
        assert "mcp__test_docs__echo_text" in messages.tool_names[1]
        assert "echo:agent" in str(session.messages)
    finally:
        agent.close()


def test_mcp_connect_and_destructive_calls_require_approval(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_fixture(workspace)
    manager = MCPManager(workspace)
    from zcli.memory import MemoryStore
    from zcli.tools import ToolRegistry

    tools = ToolRegistry(workspace, MemoryStore(tmp_path / "data"), interactive=False, mcp=manager)
    assert tools.execute("connect_mcp", {"name": "test.docs"}).startswith("Permission denied")
    assert "Connected" in tools.execute("connect_mcp", {"name": "test.docs"}, permission_checked=True)
    assert tools.execute("mcp__test_docs__deploy", {}).startswith("Permission denied")
    manager.close()
