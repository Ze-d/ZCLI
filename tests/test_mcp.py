import json
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


class StreamableHTTPFixture(BaseHTTPRequestHandler):
    session_id = "zcli-test-session"
    requests = []
    deleted = False
    expire_next_call = False

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        message = json.loads(body)
        type(self).requests.append((message, dict(self.headers)))
        method = message.get("method")
        if method != "initialize":
            if self.headers.get("Mcp-Session-Id") != self.session_id:
                self.send_error(400, "missing session")
                return
            if self.headers.get("MCP-Protocol-Version") != "2025-06-18":
                self.send_error(400, "missing protocol version")
                return
        if method == "notifications/initialized":
            self.send_response(202)
            self.end_headers()
            return
        if method == "initialize":
            result = {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "http-fixture", "version": "1"},
            }
            self._json(message["id"], result, session=True)
            return
        if method == "tools/list":
            self._json(message["id"], {"tools": [{
                "name": "search.items",
                "description": "Search Zotero items",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                "annotations": {"readOnlyHint": True},
            }]})
            return
        if method == "tools/call":
            if type(self).expire_next_call:
                type(self).expire_next_call = False
                self.send_error(404, "expired")
                return
            response = {
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {
                    "content": [{"type": "text", "text": "found:" + message["params"]["arguments"]["query"]}],
                    "isError": False,
                },
            }
            notification = {"jsonrpc": "2.0", "method": "notifications/progress", "params": {}}
            payload = (
                "event: message\n"
                f"data: {json.dumps(notification)}\n\n"
                "event: message\n"
                f"data: {json.dumps(response)}\n\n"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_error(404)

    def do_DELETE(self):
        type(self).deleted = True
        self.send_response(204)
        self.end_headers()

    def _json(self, request_id, result, session=False):
        payload = json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        if session:
            self.send_header("Mcp-Session-Id", self.session_id)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        return


@contextmanager
def http_mcp_server():
    StreamableHTTPFixture.requests = []
    StreamableHTTPFixture.deleted = False
    StreamableHTTPFixture.expire_next_call = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), StreamableHTTPFixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/mcp"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


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


def test_streamable_http_connect_json_discovery_sse_call_and_delete(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("ZCLI_HTTP_TOKEN", "secret-test-token")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with http_mcp_server() as url:
        (workspace / ".mcp.json").write_text(json.dumps({"mcpServers": {
            "zotero": {
                "transport": "streamable_http",
                "url": url,
                "headers": {"Authorization": "Bearer ${ZCLI_HTTP_TOKEN}"},
                "timeout": 5,
            }
        }}), encoding="utf-8")
        manager = MCPManager(workspace)

        result = manager.connect("zotero")

        assert "Discovered 1 tools" in result
        assert "mcp__zotero__search_items" in manager.tools
        assert manager.call("mcp__zotero__search_items", {"query": "agents"}) == "found:agents"
        assert StreamableHTTPFixture.requests[0][1]["Authorization"] == "Bearer secret-test-token"
        assert StreamableHTTPFixture.requests[0][1]["Accept"] == "application/json, text/event-stream"
        assert StreamableHTTPFixture.requests[1][1]["Mcp-Session-Id"] == "zcli-test-session"
        assert StreamableHTTPFixture.requests[1][1]["Mcp-Protocol-Version"] == "2025-06-18"
        manager.close()
        assert StreamableHTTPFixture.deleted


def test_streamable_http_config_validation(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".mcp.json").write_text(json.dumps({"mcpServers": {
        "missing-url": {"transport": "streamable_http"},
        "userinfo": {"transport": "streamable_http", "url": "http://user:pass@localhost/mcp"},
        "unknown": {"transport": "websocket", "url": "ws://localhost/mcp"},
        "reserved": {"transport": "streamable_http", "url": "http://localhost/mcp", "headers": {"Mcp-Session-Id": "fake"}},
    }}), encoding="utf-8")

    configs, errors = load_mcp_config(workspace)

    assert not configs
    assert len(errors) == 4


def test_streamable_http_reinitializes_once_after_session_404(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with http_mcp_server() as url:
        (workspace / ".mcp.json").write_text(json.dumps({"mcpServers": {
            "remote": {"transport": "streamable_http", "url": url}
        }}), encoding="utf-8")
        manager = MCPManager(workspace)
        assert "Connected" in manager.connect("remote")
        StreamableHTTPFixture.expire_next_call = True

        result = manager.call("mcp__remote__search_items", {"query": "retry"})

        assert result == "found:retry"
        initialize_calls = [
            message for message, _ in StreamableHTTPFixture.requests
            if message.get("method") == "initialize"
        ]
        assert len(initialize_calls) == 2
        manager.close()


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
