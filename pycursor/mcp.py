from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .tools import ToolError, ToolObservation


def _sanitize(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value)


@dataclass(slots=True)
class MCPTool:
    public_name: str
    server_name: str
    remote_name: str
    description: str
    input_schema: dict[str, Any]

    def as_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.public_name,
                "description": f"[MCP {self.server_name}] {self.description}",
                "parameters": self.input_schema
                or {"type": "object", "properties": {}, "additionalProperties": True},
            },
        }


class StdioMCPClient:
    """Small MCP client for the JSON-RPC stdio transport."""

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
        log: Any = None,
    ) -> None:
        self.name = name
        self.command = command
        self.args = args
        self.cwd = cwd
        self.env = {**os.environ, **(env or {})}
        self.log = log or (lambda _message: None)
        self.process: subprocess.Popen[str] | None = None
        self._messages: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._pending: dict[int, tuple[threading.Event, list[dict[str, Any]]]] = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._next_id = 1
        self._reader_thread: threading.Thread | None = None

    def start(self) -> None:
        if self.process and self.process.poll() is None:
            return
        self.process = subprocess.Popen(
            [self.command, *self.args],
            cwd=self.cwd,
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._reader_thread = threading.Thread(
            target=self._read_stdout,
            name=f"mcp-{self.name}-stdout",
            daemon=True,
        )
        self._reader_thread.start()
        threading.Thread(
            target=self._read_stderr,
            name=f"mcp-{self.name}-stderr",
            daemon=True,
        ).start()
        try:
            init = self.request(
                "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "PyCursor", "version": "1.0.0"},
                },
                timeout=12,
            )
            if "error" in init:
                raise ToolError(f"MCP initialize 失败：{init['error']}")
            self.notify("notifications/initialized", {})
            self.log(f"[MCP:{self.name}] initialized")
        except BaseException:
            self.stop()
            raise

    def _read_stdout(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                message = json.loads(stripped)
            except json.JSONDecodeError:
                self.log(f"[MCP:{self.name}] stdout 非 JSON，已忽略：{stripped[:200]}")
                continue
            request_id = message.get("id")
            if isinstance(request_id, int):
                with self._pending_lock:
                    pending = self._pending.get(request_id)
                if pending is not None:
                    pending[1].append(message)
                    pending[0].set()
                    continue
            self._messages.put(message)
        self._messages.put(None)

    def _read_stderr(self) -> None:
        process = self.process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            if line.strip():
                self.log(f"[MCP:{self.name}] {line.rstrip()}")

    def _write(self, payload: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            raise ToolError(f"MCP server {self.name} 未启动")
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._write_lock:
            self.process.stdin.write(encoded + "\n")
            self.process.stdin.flush()

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 30,
    ) -> dict[str, Any]:
        with self._pending_lock:
            request_id = self._next_id
            self._next_id += 1
            ready = threading.Event()
            replies: list[dict[str, Any]] = []
            self._pending[request_id] = (ready, replies)
        try:
            self._write(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params or {},
                }
            )
            if not ready.wait(timeout):
                raise ToolError(f"MCP {self.name} 请求超时：{method}")
            return replies[0]
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def stop(self) -> None:
        process = self.process
        self.process = None
        if not process:
            return
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                    process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass


class MCPManager:
    def __init__(self, config_path: Path, log: Any = None) -> None:
        self.config_path = config_path
        self.log = log or (lambda _message: None)
        self.clients: dict[str, StdioMCPClient] = {}
        self.tools: dict[str, MCPTool] = {}
        self.errors: dict[str, str] = {}

    def load_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {"servers": {}}
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"MCP 配置读取失败：{exc}") from exc

    def start_enabled(self) -> None:
        self.stop_all()
        self.errors.clear()
        config = self.load_config()
        servers = config.get("servers", {})
        if not isinstance(servers, dict):
            raise ValueError("mcp.json 的 servers 必须是对象")
        base_dir = self.config_path.parent
        for name, raw in servers.items():
            if not isinstance(raw, dict) or not raw.get("enabled", True):
                continue
            try:
                command = str(raw.get("command", "python"))
                is_bundled_python = command in {
                    "${PYTHON}",
                    "${PYTHON_OR_APP}",
                    "<PYTHON>",
                    "PYTHON",
                }
                if is_bundled_python:
                    command = sys.executable
                args = [str(item) for item in raw.get("args", [])]
                if is_bundled_python and getattr(sys, "frozen", False):
                    args = ["--mcp-demo"]
                cwd = Path(str(raw.get("cwd", ".")))
                if not cwd.is_absolute():
                    cwd = (base_dir / cwd).resolve()
                env = {
                    str(key): str(value)
                    for key, value in (raw.get("env") or {}).items()
                }
                client = StdioMCPClient(
                    name,
                    command,
                    args,
                    cwd=cwd,
                    env=env,
                    log=self.log,
                )
                client.start()
                self.clients[name] = client
                self._discover_tools(name, client)
            except Exception as exc:
                self.errors[name] = str(exc)
                self.log(f"[MCP:{name}] 启动失败：{exc}")

    def _discover_tools(self, server_name: str, client: StdioMCPClient) -> None:
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            params: dict[str, Any] = {}
            if cursor:
                params["cursor"] = cursor
            reply = client.request("tools/list", params, timeout=20)
            if "error" in reply:
                raise ToolError(f"tools/list 失败：{reply['error']}")
            result = reply.get("result") or {}
            for tool in result.get("tools", []):
                remote_name = str(tool.get("name", ""))
                if not remote_name:
                    continue
                public_name = f"mcp__{_sanitize(server_name)}__{_sanitize(remote_name)}"
                self.tools[public_name] = MCPTool(
                    public_name=public_name,
                    server_name=server_name,
                    remote_name=remote_name,
                    description=str(tool.get("description", "")),
                    input_schema=tool.get("inputSchema") or {},
                )
            next_cursor = result.get("nextCursor")
            if not next_cursor:
                break
            if next_cursor in seen_cursors:
                raise ToolError("MCP tools/list 返回了循环 cursor")
            seen_cursors.add(next_cursor)
            cursor = str(next_cursor)
        self.log(f"[MCP:{server_name}] discovered {len(self.tools)} tools")

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.as_openai_schema() for tool in self.tools.values()]

    def call(self, public_name: str, arguments: dict[str, Any]) -> ToolObservation:
        tool = self.tools.get(public_name)
        if tool is None:
            raise ToolError(f"未知 MCP 工具：{public_name}")
        client = self.clients.get(tool.server_name)
        if client is None:
            raise ToolError(f"MCP server 未运行：{tool.server_name}")
        reply = client.request(
            "tools/call",
            {"name": tool.remote_name, "arguments": arguments},
            timeout=90,
        )
        if "error" in reply:
            raise ToolError(f"MCP 工具调用失败：{reply['error']}")
        result = reply.get("result") or {}
        blocks = result.get("content") or []
        text_parts: list[str] = []
        openai_content: list[dict[str, Any]] = []
        for block in blocks:
            if not isinstance(block, dict):
                text_parts.append(str(block))
                continue
            block_type = block.get("type")
            if block_type == "text":
                value = str(block.get("text", ""))
                text_parts.append(value)
                openai_content.append({"type": "text", "text": value})
            elif block_type == "image":
                mime = block.get("mimeType", "image/png")
                data = block.get("data", "")
                text_parts.append(f"[MCP 返回图片 {mime}]")
                openai_content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{data}"},
                    }
                )
            else:
                serialized = json.dumps(block, ensure_ascii=False)
                text_parts.append(serialized)
                openai_content.append({"type": "text", "text": serialized})
        text = "\n".join(text_parts).strip() or "(MCP 工具未返回文本内容)"
        if result.get("isError"):
            raise ToolError(text)
        return ToolObservation(
            text=text,
            content=openai_content or text,
            metadata={
                "kind": "mcp",
                "server": tool.server_name,
                "tool": tool.remote_name,
                "structuredContent": result.get("structuredContent"),
            },
        )

    def stop_all(self) -> None:
        for client in self.clients.values():
            client.stop()
        self.clients.clear()
        self.tools.clear()

    def status(self) -> dict[str, Any]:
        return {
            "servers": {
                name: {
                    "running": (
                        client.process is not None and client.process.poll() is None
                    ),
                    "tools": [
                        tool.public_name
                        for tool in self.tools.values()
                        if tool.server_name == name
                    ],
                }
                for name, client in self.clients.items()
            },
            "errors": dict(self.errors),
        }

