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


MCP_PROTOCOL_VERSION = "2024-11-05"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]")


def normalize_mcp_name(name: str) -> str:
    """Build an Anthropic-compatible tool-name component."""
    return _SAFE_NAME.sub("_", name)


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    timeout: float = 30.0


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
    match = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", value)
    if not match:
        return value
    variable = match.group(1)
    if variable not in os.environ:
        raise ValueError(f"environment variable {variable} is not set")
    return os.environ[variable]


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
            command = value.get("command")
            if not isinstance(command, str) or not command.strip():
                raise ValueError("command must be a non-empty string")
            args = value.get("args", [])
            env = value.get("env", {})
            if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
                raise ValueError("args must be a string array")
            if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
                raise ValueError("env must contain string values")
            safe = normalize_mcp_name(name)
            if safe in normalized and normalized[safe] != name:
                raise ValueError(f"normalized name collides with {normalized[safe]!r}")
            normalized[safe] = name
            configs[name] = MCPServerConfig(
                name=name,
                command=command,
                args=tuple(args),
                env=dict(env),
                cwd=value.get("cwd"),
                timeout=float(value.get("timeout", 30)),
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
            [self.config.command, *self.config.args],
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


class MCPManager:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.clients: dict[str, StdioMCPClient] = {}
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
            lines.append(f"- {name}: {state}{suffix}")
        if len(lines) == 1:
            lines.append("- (none configured)")
        return "\n".join(lines)

    def close(self) -> None:
        for client in list(self.clients.values()):
            client.close()
        self.clients.clear()
        self.tools.clear()
