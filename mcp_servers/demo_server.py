"""Minimal MCP stdio server used by PyCursor's end-to-end demo.

stdout is reserved for JSON-RPC. Diagnostics must go to stderr.
"""

from __future__ import annotations

import json
import os
import platform
import sys
from datetime import datetime
from pathlib import Path


TOOLS = {
    "get_system_info": {
        "name": "get_system_info",
        "description": (
            "Return the current Python version, operating system and working directory. "
            "Use this when a task needs proof that an external MCP server was called."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    "project_snapshot": {
        "name": "project_snapshot",
        "description": (
            "Summarize the files at the current project root without reading their contents. "
            "Useful before deciding which file to inspect."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30}
            },
            "additionalProperties": False,
        },
    },
}


def result_text(text: str, *, is_error: bool = False) -> dict:
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def call_tool(name: str, arguments: dict) -> dict:
    if name == "get_system_info":
        return result_text(
            json.dumps(
                {
                    "server": "PyCursor demo MCP",
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "cwd": str(Path.cwd()),
                    "pid": os.getpid(),
                    "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    if name == "project_snapshot":
        limit = max(1, min(int(arguments.get("limit", 30)), 100))
        entries = []
        for path in sorted(Path.cwd().iterdir()):
            if path.name.startswith("."):
                continue
            entries.append(
                {
                    "name": path.name,
                    "type": "dir" if path.is_dir() else "file",
                    "size": path.stat().st_size if path.is_file() else None,
                }
            )
            if len(entries) >= limit:
                break
        return result_text(json.dumps(entries, ensure_ascii=False, indent=2))
    return result_text(f"unknown tool: {name}", is_error=True)


def respond(message: dict) -> dict | None:
    request_id = message.get("id")
    method = message.get("method")
    if request_id is None:
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "pycursor-demo", "version": "1.0.0"},
            },
        }
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": list(TOOLS.values())},
        }
    if method == "tools/call":
        params = message.get("params") or {}
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": call_tool(
                str(params.get("name", "")),
                params.get("arguments") or {},
            ),
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    print("pycursor-demo MCP server ready", file=sys.stderr, flush=True)
    for line in sys.stdin:
        try:
            message = json.loads(line)
            reply = respond(message)
            if reply is not None:
                print(json.dumps(reply, ensure_ascii=False), flush=True)
        except Exception as exc:
            print(f"MCP server error: {exc}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()

