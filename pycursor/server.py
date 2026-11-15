from __future__ import annotations

import argparse
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import __version__
from .agent import AgentResult, AgentRunner
from .config import Settings
from .events import EventBus, serialize_sse
from .mcp import MCPManager
from .sessions import SessionStore
from .tools import ToolContext, ToolError, execute_tool


@dataclass(slots=True)
class TaskState:
    id: str
    prompt: str
    session_id: str
    bus: EventBus = field(default_factory=EventBus)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    status: str = "queued"
    result: AgentResult | None = None


class TaskManager:
    def __init__(
        self,
        settings: Settings,
        *,
        mcp: MCPManager,
        sessions: SessionStore | None = None,
    ) -> None:
        self.settings = settings
        self.mcp = mcp
        self.sessions = sessions or SessionStore()
        self.tasks: dict[str, TaskState] = {}
        self._tasks_lock = threading.Lock()

    def submit(self, prompt: str, session_id: str | None = None) -> TaskState:
        cleaned = prompt.strip()
        if not cleaned:
            raise ValueError("任务内容不能为空")
        self.settings.validate()
        sid = session_id or self.sessions.new_id()
        task = TaskState(
            id=uuid.uuid4().hex[:12],
            prompt=cleaned,
            session_id=sid,
            status="queued",
        )
        with self._tasks_lock:
            self.tasks[task.id] = task
        task.thread = threading.Thread(
            target=self._run_task,
            args=(task,),
            name=f"task-{task.id}",
            daemon=True,
        )
        task.thread.start()
        return task

    def _run_task(self, task: TaskState) -> None:
        task.status = "running"
        try:
            task.bus.emit(
                "task.queued",
                task_id=task.id,
                session_id=task.session_id,
            )
            runner = AgentRunner(self.settings, mcp=self.mcp)
            result = runner.run(
                task.prompt,
                task_id=task.id,
                cancel_event=task.cancel_event,
                emit=lambda kind, data: task.bus.emit(kind, **data),
                history=self.sessions.recent_messages(task.session_id),
            )
            task.result = result
            task.status = (
                "cancelled"
                if result.cancelled
                else "failed"
                if result.failed
                else "completed"
            )
            self.sessions.append_exchange(
                task.session_id,
                user=task.prompt,
                assistant=result.content,
                task_id=task.id,
                trace_summary=result.trace,
            )
        except Exception as exc:
            task.status = "failed"
            task.bus.emit(
                "task.failed",
                task_id=task.id,
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            task.bus.close()

    def cancel(self, task_id: str) -> bool:
        with self._tasks_lock:
            task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        task.cancel_event.set()
        return True

    def get(self, task_id: str) -> TaskState:
        with self._tasks_lock:
            task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        return task

    def public_task(self, task_id: str) -> dict[str, Any]:
        task = self.get(task_id)
        return {
            "id": task.id,
            "status": task.status,
            "prompt": task.prompt,
            "session_id": task.session_id,
            "result": task.result.content if task.result else None,
            "event_count": task.bus.length,
        }


class Application:
    def __init__(
        self,
        settings: Settings,
        *,
        start_mcp: bool = True,
        sessions: SessionStore | None = None,
    ) -> None:
        self.settings = settings
        self.logs: list[str] = []
        self._log_lock = threading.Lock()
        self.mcp = MCPManager(Path(settings.mcp_config), log=self.log)
        if start_mcp and settings.auto_start_mcp:
            self.mcp.start_enabled()
        self.tasks = TaskManager(settings, mcp=self.mcp, sessions=sessions)

    def log(self, message: str) -> None:
        with self._log_lock:
            self.logs.append(message)
            self.logs[:] = self.logs[-300:]

    def update_settings(self, payload: dict[str, Any]) -> None:
        allowed = {
            "api_key",
            "base_url",
            "model",
            "workspace",
            "max_steps",
            "command_timeout",
            "context_char_limit",
            "mcp_config",
            "auto_start_mcp",
            "temperature",
        }
        for key, value in payload.items():
            if key not in allowed:
                continue
            if key == "api_key" and value == "••••••••":
                continue
            setattr(self.settings, key, value)
        self.settings.max_steps = max(1, min(int(self.settings.max_steps), 40))
        self.settings.command_timeout = max(1, min(int(self.settings.command_timeout), 300))
        self.settings.context_char_limit = max(8_000, int(self.settings.context_char_limit))
        self.settings.temperature = max(0.0, min(float(self.settings.temperature), 2.0))
        workspace = Path(str(self.settings.workspace)).expanduser().resolve()
        if not workspace.is_dir():
            raise ValueError(f"工作区不存在或不是目录：{workspace}")
        self.settings.workspace = str(workspace)
        self.settings.mcp_config = str(
            Path(str(self.settings.mcp_config)).expanduser().resolve()
        )
        self.settings.save()
        self.tasks.settings = self.settings

    def list_files(self, relative: str = "") -> dict[str, Any]:
        root = Path(self.settings.workspace)
        target = (root / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ToolError("拒绝访问工作区外路径") from exc
        if not target.is_dir():
            raise ToolError(f"目录不存在：{relative}")
        entries: list[dict[str, Any]] = []
        for path in sorted(target.rglob("*")):
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            if any(part in {".git", "__pycache__", ".venv", "node_modules"} for part in rel.parts):
                continue
            if len(entries) >= 800:
                break
            try:
                size = path.stat().st_size if path.is_file() else None
            except OSError:
                size = None
            entries.append(
                {
                    "path": rel.as_posix(),
                    "name": path.name,
                    "kind": "dir" if path.is_dir() else "file",
                    "size": size,
                    "depth": len(rel.parts) - 1,
                }
            )
        return {"root": str(root), "entries": entries}


class PyCursorHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], app: Application) -> None:
        self.app = app
        super().__init__(address, APIHandler)


class APIHandler(BaseHTTPRequestHandler):
    server: PyCursorHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        self.server.app.log(f"{self.address_string()} {format % args}")

    def _json_body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b"{}"
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("请求体必须是 UTF-8 JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("JSON 请求体必须是对象")
        return parsed

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _send_error_json(self, error: Exception, status: int = 400) -> None:
        self._send_json(
            {"error": str(error), "type": type(error).__name__},
            status=status,
        )

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/health":
                self._send_json(
                    {
                        "ok": True,
                        "version": __version__,
                        "model": self.server.app.settings.model,
                        "workspace": self.server.app.settings.workspace,
                    }
                )
                return
            if path == "/api/config":
                self._send_json(self.server.app.settings.public_dict())
                return
            if path == "/api/mcp/status":
                self._send_json(self.server.app.mcp.status())
                return
            if path == "/api/logs":
                self._send_json({"logs": self.server.app.logs[-200:]})
                return
            if path == "/api/files":
                relative = parse_qs(parsed.query).get("path", [""])[0]
                self._send_json(self.server.app.list_files(relative))
                return
            if path.startswith("/api/sessions/"):
                session_id = path.rsplit("/", 1)[-1]
                self._send_json(self.server.app.tasks.sessions.load(session_id))
                return
            if path.startswith("/api/tasks/"):
                suffix = path[len("/api/tasks/") :]
                if suffix.endswith("/events"):
                    task_id = suffix[: -len("/events")].strip("/")
                    self._stream_events(task_id)
                    return
                self._send_json(self.server.app.tasks.public_task(suffix.strip("/")))
                return
            self._send_error_json("接口不存在", HTTPStatus.NOT_FOUND)
        except KeyError:
            self._send_error_json("任务不存在", HTTPStatus.NOT_FOUND)
        except (ToolError, ValueError) as exc:
            self._send_error_json(exc, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._send_error_json(exc, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/tasks":
                body = self._json_body()
                task = self.server.app.tasks.submit(
                    str(body.get("prompt", "")),
                    body.get("session_id"),
                )
                self._send_json(
                    {
                        "task_id": task.id,
                        "session_id": task.session_id,
                        "events_url": f"/api/tasks/{task.id}/events",
                    },
                    HTTPStatus.ACCEPTED,
                )
                return
            if path.startswith("/api/tasks/") and path.endswith("/cancel"):
                task_id = path[len("/api/tasks/") : -len("/cancel")].strip("/")
                self.server.app.tasks.cancel(task_id)
                self._send_json({"ok": True, "task_id": task_id})
                return
            if path == "/api/config":
                body = self._json_body()
                self.server.app.update_settings(body)
                self._send_json(self.server.app.settings.public_dict())
                return
            if path == "/api/mcp/reload":
                self.server.app.mcp.start_enabled()
                self._send_json(self.server.app.mcp.status())
                return
            self._send_error_json("接口不存在", HTTPStatus.NOT_FOUND)
        except KeyError:
            self._send_error_json("任务不存在", HTTPStatus.NOT_FOUND)
        except (ToolError, ValueError) as exc:
            self._send_error_json(exc, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._send_error_json(exc, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _stream_events(self, task_id: str) -> None:
        task = self.server.app.tasks.get(task_id)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.close_connection = True
        try:
            last_event_id = self.headers.get("Last-Event-ID")
            after_seq = int(last_event_id) if last_event_id else 0
        except ValueError:
            after_seq = 0
        try:
            while True:
                events = task.bus.wait_many(after_seq, timeout=10)
                if not events and not task.bus.closed:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    continue
                for event in events:
                    self.wfile.write(serialize_sse(event))
                    self.wfile.flush()
                    after_seq = event.seq
                if task.bus.closed:
                    break
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass


def start_server(
    settings: Settings,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    start_mcp: bool = True,
    sessions: SessionStore | None = None,
) -> tuple[PyCursorHTTPServer, Application]:
    app = Application(settings, start_mcp=start_mcp, sessions=sessions)
    server = PyCursorHTTPServer((host, port), app)
    thread = threading.Thread(
        target=server.serve_forever,
        name="pycursor-http",
        daemon=True,
    )
    thread.start()
    return server, app


def cli() -> None:
    parser = argparse.ArgumentParser(description="PyCursor backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--workspace")
    parser.add_argument("--no-mcp", action="store_true")
    args = parser.parse_args()
    settings = Settings.load()
    if args.workspace:
        settings.workspace = str(Path(args.workspace).expanduser().resolve())
    server, app = start_server(
        settings,
        host=args.host,
        port=args.port,
        start_mcp=not args.no_mcp,
    )
    host, port = server.server_address
    print(f"PyCursor backend: http://{host}:{port}")
    print(f"Workspace: {settings.workspace}")
    print(f"MCP: {json.dumps(app.mcp.status(), ensure_ascii=False)}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        app.mcp.stop_all()


if __name__ == "__main__":
    cli()

