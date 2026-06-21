from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx


MCP_PROTOCOL_VERSION = "2025-06-18"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]")


def normalize_mcp_name(name: str) -> str:
    """Build an Anthropic-compatible tool-name component."""
    return _SAFE_NAME.sub("_", name)


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    transport: str = "stdio"
    command: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    timeout: float = 30.0
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MCPTool:
    server_name: str
    remote_name: str
    name: str
    description: str
    input_schema: dict[str, Any]
    annotations: dict[str, Any]

    @property
    def destructive(self) -> bool:
        return self.annotations.get("destructiveHint") is True

    def definition(self) -> dict[str, Any]:
        hints = []
        if self.annotations.get("readOnlyHint") is True:
            hints.append("read-only")
        if self.destructive:
            hints.append("destructive")
        suffix = f" ({', '.join(hints)})" if hints else ""
        return {
            "name": self.name,
            "description": f"{self.description}{suffix}".strip(),
            "input_schema": self.input_schema or {"type": "object", "properties": {}},
        }


def _expand_env(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        variable = match.group(1)
        if variable not in os.environ:
            raise ValueError(f"environment variable {variable} is not set")
        return os.environ[variable]

    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, value)


def load_mcp_config(workspace: Path) -> tuple[dict[str, MCPServerConfig], list[str]]:
    """Merge user, project, and project-local MCP config (later wins)."""
    paths = (
        Path.home() / ".zcli" / "mcp.json",
        workspace / ".mcp.json",
        workspace / ".zcli" / "mcp.json",
    )
    raw_servers: dict[str, Any] = {}
    errors: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            servers = payload.get("mcpServers", payload)
            if not isinstance(servers, dict):
                raise ValueError("mcpServers must be an object")
            raw_servers.update(servers)
        except Exception as exc:
            errors.append(f"{path}: {type(exc).__name__}: {exc}")

    configs: dict[str, MCPServerConfig] = {}
    normalized: dict[str, str] = {}
    for name, value in raw_servers.items():
        try:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("server name must be a non-empty string")
            if not isinstance(value, dict):
                raise ValueError("server config must be an object")
            transport = str(value.get("transport", "stdio")).strip().lower()
            if transport not in {"stdio", "streamable_http"}:
                raise ValueError(f"unsupported transport: {transport}")
            command = value.get("command")
            url = value.get("url")
            if transport == "stdio" and (not isinstance(command, str) or not command.strip()):
                raise ValueError("stdio command must be a non-empty string")
            if transport == "streamable_http":
                if not isinstance(url, str) or not url.strip():
                    raise ValueError("streamable_http url must be a non-empty string")
                parsed_url = httpx.URL(url)
                if parsed_url.scheme not in {"http", "https"} or not parsed_url.host:
                    raise ValueError("streamable_http url must use http or https")
                if parsed_url.username or parsed_url.password:
                    raise ValueError("credentials must use headers, not URL userinfo")
            args = value.get("args", [])
            env = value.get("env", {})
            headers = value.get("headers", {})
            if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
                raise ValueError("args must be a string array")
            if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
                raise ValueError("env must contain string values")
            if not isinstance(headers, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in headers.items()):
                raise ValueError("headers must contain string values")
            reserved_headers = {
                "accept", "content-type", "content-length", "host",
                "mcp-session-id", "mcp-protocol-version",
            }
            conflict = reserved_headers.intersection(key.lower() for key in headers)
            if conflict:
                raise ValueError(f"headers cannot override MCP transport headers: {', '.join(sorted(conflict))}")
            timeout = float(value.get("timeout", 30))
            if timeout <= 0:
                raise ValueError("timeout must be greater than zero")
            safe = normalize_mcp_name(name)
            if safe in normalized and normalized[safe] != name:
                raise ValueError(f"normalized name collides with {normalized[safe]!r}")
            normalized[safe] = name
            configs[name] = MCPServerConfig(
                name=name,
                transport=transport,
                command=command,
                args=tuple(args),
                env=dict(env),
                cwd=value.get("cwd"),
                timeout=timeout,
                url=url,
                headers=dict(headers),
            )
        except Exception as exc:
            errors.append(f"server {name!r}: {type(exc).__name__}: {exc}")
    return configs, errors


class StdioMCPClient:
    """Small synchronous MCP client implementing initialize/tools list/call."""

    def __init__(self, config: MCPServerConfig, workspace: Path):
        self.config = config
        self.workspace = workspace.resolve()
        self.process: subprocess.Popen[str] | None = None
        self.tools: list[dict[str, Any]] = []
        self._request_id = 0
        self._lock = threading.RLock()
        self._messages: queue.Queue[dict[str, Any] | Exception | None] = queue.Queue()
        self._stderr: list[str] = []

    def connect(self) -> list[dict[str, Any]]:
        if self.process and self.process.poll() is None:
            return self.tools
        env = os.environ.copy()
        env.update({key: _expand_env(value) for key, value in self.config.env.items()})
        cwd = self.workspace
        if self.config.cwd:
            cwd = (self.workspace / self.config.cwd).resolve()
            if not cwd.is_relative_to(self.workspace):
                raise ValueError(f"MCP cwd escapes workspace: {self.config.cwd}")
        self.process = subprocess.Popen(
            [self.config.command or "", *self.config.args],
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        try:
            self._request("initialize", {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "zcli", "version": "0.1.0"},
            })
            self._notify("notifications/initialized", {})
            result = self._request("tools/list", {})
            tools = result.get("tools", [])
            if not isinstance(tools, list):
                raise RuntimeError("tools/list returned a non-list tools field")
            self.tools = tools
            return tools
        except Exception:
            self.close()
            raise

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        return _render_tool_result(result)

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._request_id += 1
            request_id = self._request_id
            self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            while True:
                message = self._read_message()
                if message.get("id") != request_id:
                    continue
                if "error" in message:
                    error = message["error"]
                    raise RuntimeError(f"MCP {method} failed: {error}")
                result = message.get("result", {})
                return result if isinstance(result, dict) else {"value": result}

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _write(self, payload: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin or self.process.poll() is not None:
            raise RuntimeError("MCP server is not running")
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def _read_message(self) -> dict[str, Any]:
        try:
            message = self._messages.get(timeout=self.config.timeout)
        except queue.Empty as exc:
            raise TimeoutError(f"MCP response timed out after {self.config.timeout:g}s") from exc
        if message is None:
            detail = "".join(self._stderr).strip()[:1000]
            raise RuntimeError(f"MCP server disconnected: {detail}")
        if isinstance(message, Exception):
            raise RuntimeError(f"invalid MCP message: {message}") from message
        return message

    def _read_stdout(self) -> None:
        process = self.process
        if not process or not process.stdout:
            self._messages.put(None)
            return
        try:
            for line in process.stdout:
                try:
                    message = json.loads(line)
                    if not isinstance(message, dict):
                        raise ValueError("message must be an object")
                    self._messages.put(message)
                except Exception as exc:
                    self._messages.put(exc)
        finally:
            self._messages.put(None)

    def _read_stderr(self) -> None:
        process = self.process
        if not process or not process.stderr:
            return
        for line in process.stderr:
            self._stderr.append(line)
            if sum(map(len, self._stderr)) > 10_000:
                del self._stderr[:-20]

    def close(self) -> None:
        process, self.process = self.process, None
        if not process:
            return
        if process.stdin:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


class _HTTPSessionExpired(RuntimeError):
    pass


class StreamableHTTPMCPClient:
    """Synchronous MCP Streamable HTTP client supporting JSON and SSE responses."""

    def __init__(self, config: MCPServerConfig, workspace: Path):
        self.config = config
        self.workspace = workspace.resolve()
        self.session_id: str | None = None
        self.protocol_version = MCP_PROTOCOL_VERSION
        self.tools: list[dict[str, Any]] = []
        self._request_id = 0
        self._lock = threading.RLock()
        headers = {key: _expand_env(value) for key, value in config.headers.items()}
        self.client = httpx.Client(headers=headers, timeout=config.timeout, follow_redirects=False)
        self._closed = False

    def connect(self) -> list[dict[str, Any]]:
        with self._lock:
            if self.tools:
                return self.tools
            self._initialize()
            return self.tools

    def _initialize(self) -> None:
        self.session_id = None
        result = self._request_once(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "zcli", "version": "0.1.0"},
            },
            initialization=True,
        )
        negotiated = result.get("protocolVersion")
        if isinstance(negotiated, str) and negotiated:
            self.protocol_version = negotiated
        self._notify("notifications/initialized", {})
        tools_result = self._request_once("tools/list", {})
        tools = tools_result.get("tools", [])
        if not isinstance(tools, list):
            raise RuntimeError("tools/list returned a non-list tools field")
        self.tools = tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        return _render_tool_result(result)

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            try:
                return self._request_once(method, params)
            except _HTTPSessionExpired:
                self.tools = []
                self._initialize()
                return self._request_once(method, params)

    def _request_once(
        self,
        method: str,
        params: dict[str, Any],
        *,
        initialization: bool = False,
    ) -> dict[str, Any]:
        self._request_id += 1
        request_id = self._request_id
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        message = self._post(payload, request_id=request_id, initialization=initialization)
        if "error" in message:
            raise RuntimeError(f"MCP {method} failed: {message['error']}")
        result = message.get("result", {})
        return result if isinstance(result, dict) else {"value": result}

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        response = self.client.post(self.config.url or "", json=payload, headers=self._headers())
        if response.status_code == 404 and self.session_id:
            raise _HTTPSessionExpired("MCP HTTP session expired")
        if response.status_code != 202:
            response.raise_for_status()
            raise RuntimeError(f"MCP notification expected HTTP 202, got {response.status_code}")

    def _post(
        self,
        payload: dict[str, Any],
        *,
        request_id: int,
        initialization: bool,
    ) -> dict[str, Any]:
        with self.client.stream(
            "POST",
            self.config.url or "",
            json=payload,
            headers=self._headers(initialization=initialization),
        ) as response:
            if initialization:
                session_id = response.headers.get("mcp-session-id")
                if session_id:
                    if not all(0x21 <= ord(char) <= 0x7E for char in session_id):
                        raise RuntimeError("MCP server returned an invalid session ID")
                    self.session_id = session_id
            if response.status_code == 404 and self.session_id:
                raise _HTTPSessionExpired("MCP HTTP session expired")
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type == "application/json":
                message = json.loads(response.read())
                if not isinstance(message, dict):
                    raise RuntimeError("MCP HTTP response must be a JSON object")
                if message.get("id") != request_id:
                    raise RuntimeError(f"MCP HTTP response ID mismatch: expected {request_id}")
                return message
            if content_type == "text/event-stream":
                return self._read_sse_response(response, request_id)
            raise RuntimeError(f"unsupported MCP HTTP content type: {content_type or '(missing)'}")

    @staticmethod
    def _read_sse_response(response: httpx.Response, request_id: int) -> dict[str, Any]:
        data_lines: list[str] = []
        for line in response.iter_lines():
            if line == "":
                if not data_lines:
                    continue
                raw = "\n".join(data_lines)
                data_lines.clear()
                message = json.loads(raw)
                if isinstance(message, dict) and message.get("id") == request_id:
                    return message
                continue
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip(" "))
        if data_lines:
            message = json.loads("\n".join(data_lines))
            if isinstance(message, dict) and message.get("id") == request_id:
                return message
        raise RuntimeError("MCP SSE stream ended before the matching response")

    def _headers(self, *, initialization: bool = False) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if not initialization:
            headers["MCP-Protocol-Version"] = self.protocol_version
            if self.session_id:
                headers["Mcp-Session-Id"] = self.session_id
        return headers

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.session_id:
                response = self.client.delete(self.config.url or "", headers=self._headers())
                if response.status_code not in {200, 204, 405}:
                    response.raise_for_status()
        except Exception:
            pass
        finally:
            self.client.close()


def _render_tool_result(result: dict[str, Any]) -> str:
    content = result.get("content", [])
    rendered: list[str] = []
    for item in content if isinstance(content, list) else []:
        if not isinstance(item, dict):
            rendered.append(str(item))
        elif item.get("type") == "text":
            rendered.append(str(item.get("text", "")))
        else:
            rendered.append(json.dumps(item, ensure_ascii=False))
    text = "\n".join(part for part in rendered if part)
    if result.get("isError"):
        return f"MCP error: {text or 'tool call failed'}"
    return text or json.dumps(result, ensure_ascii=False)


class MCPManager:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.clients: dict[str, StdioMCPClient | StreamableHTTPMCPClient] = {}
        self.tools: dict[str, MCPTool] = {}
        self.errors: list[str] = []

    @property
    def configs(self) -> dict[str, MCPServerConfig]:
        configs, self.errors = load_mcp_config(self.workspace)
        return configs

    def connect(self, name: str) -> str:
        if name in self.clients:
            return f"MCP server '{name}' already connected"
        config = self.configs.get(name)
        if not config:
            available = ", ".join(sorted(self.configs)) or "(none)"
            return f"MCP server not found: {name}. Available: {available}"
        client: StdioMCPClient | StreamableHTTPMCPClient
        if config.transport == "streamable_http":
            client = StreamableHTTPMCPClient(config, self.workspace)
        else:
            client = StdioMCPClient(config, self.workspace)
        try:
            remote_tools = client.connect()
            discovered: dict[str, MCPTool] = {}
            for value in remote_tools:
                remote_name = value.get("name")
                if not isinstance(remote_name, str) or not remote_name:
                    raise ValueError("MCP tool has no valid name")
                public_name = f"mcp__{normalize_mcp_name(name)}__{normalize_mcp_name(remote_name)}"
                if public_name in self.tools or public_name in discovered:
                    raise ValueError(f"MCP tool name collision: {public_name}")
                discovered[public_name] = MCPTool(
                    server_name=name,
                    remote_name=remote_name,
                    name=public_name,
                    description=str(value.get("description", "MCP tool")),
                    input_schema=value.get("inputSchema", {"type": "object", "properties": {}}),
                    annotations=value.get("annotations", {}),
                )
            self.clients[name] = client
            self.tools.update(discovered)
            names = ", ".join(discovered) or "(no tools)"
            return f"Connected to MCP server '{name}'. Discovered {len(discovered)} tools: {names}"
        except Exception as exc:
            client.close()
            return f"MCP connection error for '{name}': {type(exc).__name__}: {exc}"

    def call(self, public_name: str, arguments: dict[str, Any]) -> str:
        tool = self.tools.get(public_name)
        if not tool:
            return f"MCP tool not found: {public_name}"
        client = self.clients.get(tool.server_name)
        if not client:
            return f"MCP server is disconnected: {tool.server_name}"
        try:
            return client.call_tool(tool.remote_name, arguments)
        except Exception as exc:
            return f"MCP call error: {type(exc).__name__}: {exc}"

    def definitions(self) -> list[dict[str, Any]]:
        return [self.tools[name].definition() for name in sorted(self.tools)]

    def status(self) -> str:
        configs = self.configs
        lines = ["MCP servers:"]
        for name in sorted(configs):
            state = "connected" if name in self.clients else "available"
            count = sum(tool.server_name == name for tool in self.tools.values())
            suffix = f", {count} tools" if state == "connected" else ""
            lines.append(f"- {name}: {state} ({configs[name].transport}){suffix}")
        if len(lines) == 1:
            lines.append("- (none configured)")
        return "\n".join(lines)

    def close(self) -> None:
        for client in list(self.clients.values()):
            client.close()
        self.clients.clear()
        self.tools.clear()
