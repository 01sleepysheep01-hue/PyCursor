from __future__ import annotations

import json
import queue
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
from http.client import HTTPResponse
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any
from urllib.parse import urlparse

from .config import Settings
from .server import Application, PyCursorHTTPServer, start_server


BG = "#111318"
SIDEBAR = "#171a21"
PANEL = "#1d2028"
PANEL_ALT = "#232732"
BORDER = "#303541"
TEXT = "#eef1f7"
MUTED = "#9aa3b2"
ACCENT = "#70a5ff"
SUCCESS = "#64d69a"
WARNING = "#f2bd63"
ERROR = "#ff6b7a"


class HTTPAPI:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: int = 20,
    ) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                message = json.loads(raw).get("error", raw)
            except json.JSONDecodeError:
                message = raw
            raise RuntimeError(str(message)) from exc
        if not raw:
            return {}
        return json.loads(raw)


class SSEStream:
    def __init__(self, base_url: str, path: str, target: queue.Queue[dict[str, Any]]) -> None:
        self.base_url = base_url
        self.path = path
        self.target = target
        self.stop_event = threading.Event()
        self.response: HTTPResponse | None = None
        self.thread = threading.Thread(target=self._run, name="pycursor-sse", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.stop_event.set()
        response = self.response
        if response is not None:
            try:
                response.close()
            except OSError:
                pass

    def _run(self) -> None:
        parsed = urlparse(self.base_url)
        import http.client

        connection_class = (
            http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        )
        connection = connection_class(parsed.hostname, parsed.port, timeout=30)
        try:
            connection.request("GET", self.path, headers={"Accept": "text/event-stream"})
            response = connection.getresponse()
            self.response = response
            if response.status != 200:
                raise RuntimeError(f"事件流连接失败：HTTP {response.status}")
            event_type = "message"
            data_lines: list[str] = []
            while not self.stop_event.is_set():
                raw_line = response.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8").rstrip("\r\n")
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].strip())
                elif line == "":
                    if data_lines:
                        try:
                            payload = json.loads("\n".join(data_lines))
                        except json.JSONDecodeError:
                            payload = {"raw": "\n".join(data_lines)}
                        payload.setdefault("type", event_type)
                        self.target.put(payload)
                    event_type = "message"
                    data_lines = []
        except Exception as exc:
            if not self.stop_event.is_set():
                self.target.put({"type": "stream.error", "error": str(exc)})
        finally:
            connection.close()


class DesktopApp:
    def __init__(
        self,
        settings: Settings,
        server: PyCursorHTTPServer,
        application: Application,
    ) -> None:
        self.settings = settings
        self.server = server
        self.application = application
        host, port = server.server_address
        self.base_url = f"http://{host}:{port}"
        self.api = HTTPAPI(self.base_url)
        self.ui_events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.stream: SSEStream | None = None
        self.active_task_id: str | None = None
        self.session_id: str | None = None
        self.activity_items: dict[str, str] = {}
        self.busy = False

        self.root = tk.Tk()
        self.root.title("PyCursor · 本地编码智能体")
        self.root.geometry("1360x860")
        self.root.minsize(1040, 680)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._configure_style()
        self._build_ui()
        self._load_workspace()
        self._refresh_mcp_status()
        self.root.after(80, self._poll_events)
        self.root.after(250, self.composer.focus_set)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=TEXT, fieldbackground=PANEL)
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Sidebar.TFrame", background=SIDEBAR)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED)
        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground="#07101f",
            padding=(13, 8),
            borderwidth=0,
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.map(
            "Accent.TButton",
            background=[("active", "#91b8ff"), ("disabled", "#46536b")],
            foreground=[("disabled", "#9da6b5")],
        )
        style.configure(
            "Quiet.TButton",
            background=PANEL_ALT,
            foreground=TEXT,
            padding=(10, 7),
            borderwidth=0,
        )
        style.map("Quiet.TButton", background=[("active", "#333846")])
        style.configure(
            "Danger.TButton",
            background="#3a2027",
            foreground=ERROR,
            padding=(10, 7),
            borderwidth=0,
        )
        style.map("Danger.TButton", background=[("active", "#522832")])
        style.configure(
            "Treeview",
            background=PANEL,
            fieldbackground=PANEL,
            foreground=TEXT,
            rowheight=27,
            borderwidth=0,
        )
        style.map("Treeview", background=[("selected", "#2b4165")])
        style.configure(
            "Treeview.Heading",
            background=SIDEBAR,
            foreground=MUTED,
            borderwidth=0,
            padding=(6, 7),
        )
        style.configure(
            "TNotebook",
            background=PANEL,
            borderwidth=0,
            tabmargins=(0, 0, 0, 0),
        )
        style.configure(
            "TNotebook.Tab",
            background=SIDEBAR,
            foreground=MUTED,
            padding=(15, 8),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", PANEL)],
            foreground=[("selected", TEXT)],
        )
        style.configure("TPanedwindow", background=BORDER)

    def _build_ui(self) -> None:
        header = ttk.Frame(self.root, style="Panel.TFrame", padding=(18, 13))
        header.pack(fill="x")
        title = tk.Label(
            header,
            text="PYCURSOR",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI Semibold", 15),
        )
        title.pack(side="left")
        self.workspace_label = tk.Label(
            header,
            text="",
            bg=PANEL,
            fg=MUTED,
            font=("Microsoft YaHei UI", 9),
        )
        self.workspace_label.pack(side="left", padx=(16, 0))
        self.mcp_label = tk.Label(
            header,
            text="MCP 检查中",
            bg=PANEL,
            fg=WARNING,
            font=("Microsoft YaHei UI", 9),
        )
        self.mcp_label.pack(side="right", padx=(10, 0))
        ttk.Button(header, text="设置", style="Quiet.TButton", command=self.open_settings).pack(
            side="right", padx=(8, 0)
        )
        ttk.Button(header, text="新任务", style="Quiet.TButton", command=self.new_task).pack(
            side="right", padx=(8, 0)
        )

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=9, pady=(0, 7))
        left = ttk.Frame(body, style="Panel.TFrame", padding=(10, 10))
        center = ttk.Frame(body, style="Panel.TFrame", padding=(0, 0))
        right = ttk.Frame(body, style="Panel.TFrame", padding=(0, 0))
        body.add(left, weight=0)
        body.add(center, weight=1)
        body.add(right, weight=0)
        body.sashpos(0, 250)
        body.sashpos(1, 970)

        left_header = ttk.Frame(left, style="Panel.TFrame")
        left_header.pack(fill="x", pady=(0, 8))
        ttk.Label(left_header, text="工作区", style="Panel.TLabel").pack(side="left")
        ttk.Button(
            left_header,
            text="刷新",
            style="Quiet.TButton",
            command=self._load_workspace,
        ).pack(side="right")
        self.workspace_tree = ttk.Treeview(left, show="tree", selectmode="browse")
        self.workspace_tree.pack(fill="both", expand=True)
        self.workspace_tree.bind("<Double-1>", self._preview_file)

        center_header = ttk.Frame(center, style="Panel.TFrame", padding=(16, 11))
        center_header.pack(fill="x")
        tk.Label(
            center_header,
            text="对话",
            bg=PANEL,
            fg=TEXT,
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="left")
        self.model_label = tk.Label(
            center_header,
            text=self.settings.model,
            bg=PANEL,
            fg=MUTED,
            font=("Consolas", 9),
        )
        self.model_label.pack(side="right")

        self.conversation = tk.Text(
            center,
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground="#315080",
            wrap="word",
            relief="flat",
            padx=20,
            pady=16,
            spacing1=3,
            spacing3=7,
            font=("Microsoft YaHei UI", 10),
            state="disabled",
        )
        self.conversation.pack(fill="both", expand=True)
        self.conversation.tag_configure(
            "user",
            foreground="#dce8ff",
            background="#25344c",
            lmargin1=26,
            lmargin2=26,
            rmargin=26,
            spacing1=10,
            spacing3=10,
        )
        self.conversation.tag_configure(
            "assistant",
            foreground=TEXT,
            lmargin1=26,
            lmargin2=26,
            rmargin=26,
            spacing1=10,
            spacing3=10,
        )
        self.conversation.tag_configure(
            "meta",
            foreground=MUTED,
            font=("Segoe UI", 8, "bold"),
            spacing1=8,
        )
        self.conversation.tag_configure(
            "error",
            foreground=ERROR,
            lmargin1=26,
            lmargin2=26,
            rmargin=26,
        )

        composer_frame = ttk.Frame(center, style="Panel.TFrame", padding=(16, 12))
        composer_frame.pack(fill="x", side="bottom", before=self.conversation)
        composer_border = tk.Frame(composer_frame, bg=BORDER, padx=1, pady=1)
        composer_border.pack(fill="x")
        self.composer = tk.Text(
            composer_border,
            height=3,
            bg=PANEL_ALT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            wrap="word",
            padx=12,
            pady=9,
            font=("Microsoft YaHei UI", 10),
        )
        self.composer.pack(fill="x")
        self.composer.bind("<Control-Return>", self._send_from_shortcut)
        controls = ttk.Frame(composer_frame, style="Panel.TFrame")
        controls.pack(fill="x", pady=(8, 0))
        self.stop_button = ttk.Button(
            controls,
            text="停止",
            style="Danger.TButton",
            command=self.stop_task,
            state="disabled",
        )
        self.stop_button.pack(side="right", padx=(8, 0))
        self.send_button = ttk.Button(
            controls,
            text="发送",
            style="Accent.TButton",
            command=self.send_task,
        )
        self.send_button.pack(side="right")
        ttk.Label(
            controls,
            text="Ctrl+Enter 发送 · 工具过程可见",
            style="PanelMuted.TLabel",
            font=("Microsoft YaHei UI", 8),
        ).pack(side="left", fill="x", expand=True)

        notebook = ttk.Notebook(right)
        notebook.pack(fill="both", expand=True)
        activity_tab = ttk.Frame(notebook, style="Panel.TFrame", padding=(8, 8))
        diff_tab = ttk.Frame(notebook, style="Panel.TFrame", padding=(8, 8))
        trace_tab = ttk.Frame(notebook, style="Panel.TFrame", padding=(8, 8))
        notebook.add(activity_tab, text="活动")
        notebook.add(diff_tab, text="变更")
        notebook.add(trace_tab, text="Trace")

        self.activity = ttk.Treeview(
            activity_tab,
            columns=("step", "tool", "status"),
            show="headings",
            selectmode="browse",
        )
        self.activity.heading("step", text="步")
        self.activity.heading("tool", text="工具")
        self.activity.heading("status", text="状态")
        self.activity.column("step", width=38, anchor="center", stretch=False)
        self.activity.column("tool", width=155, stretch=True)
        self.activity.column("status", width=72, anchor="center", stretch=False)
        self.activity.pack(fill="both", expand=True)
        self.activity.tag_configure("running", foreground=WARNING)
        self.activity.tag_configure("ok", foreground=SUCCESS)
        self.activity.tag_configure("fail", foreground=ERROR)

        self.diff_text = self._make_readonly_text(diff_tab, "Consolas", 9)
        self.diff_text.tag_configure("add", foreground=SUCCESS)
        self.diff_text.tag_configure("remove", foreground=ERROR)
        self.diff_text.tag_configure("hunk", foreground=ACCENT)

        self.trace_text = self._make_readonly_text(trace_tab, "Consolas", 9)
        self.trace_text.tag_configure("tool", foreground=ACCENT)
        self.trace_text.tag_configure("error", foreground=ERROR)
        self.trace_text.tag_configure("muted", foreground=MUTED)

        footer = tk.Frame(self.root, bg=SIDEBAR, height=28)
        footer.pack(fill="x", side="bottom", before=body)
        self.status_label = tk.Label(
            footer,
            text="就绪",
            bg=SIDEBAR,
            fg=MUTED,
            font=("Microsoft YaHei UI", 8),
        )
        self.status_label.pack(side="left", padx=12, pady=4)
        self.backend_label = tk.Label(
            footer,
            text=self.base_url,
            bg=SIDEBAR,
            fg="#697487",
            font=("Consolas", 8),
        )
        self.backend_label.pack(side="right", padx=12, pady=4)

    def _make_readonly_text(self, parent: tk.Widget, font: str, size: int) -> tk.Text:
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.pack(fill="both", expand=True)
        text = tk.Text(
            frame,
            bg="#12151b",
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground="#315080",
            wrap="none",
            relief="flat",
            padx=10,
            pady=10,
            font=(font, size),
            state="disabled",
        )
        y_scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        x_scroll = ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
        text.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return text

    def _append_text(
        self,
        widget: tk.Text,
        text: str,
        *tags: str,
    ) -> None:
        widget.configure(state="normal")
        widget.insert("end", text, tags)
        widget.see("end")
        widget.configure(state="disabled")

    def _conversation_message(self, label: str, content: str, kind: str) -> None:
        self._append_text(self.conversation, f"{label}\n", "meta")
        self._append_text(self.conversation, f"{content.strip()}\n\n", kind)

    def _load_workspace(self) -> None:
        try:
            data = self.api.request("GET", "/api/files")
        except Exception as exc:
            self._set_status(f"工作区读取失败：{exc}", ERROR)
            return
        for item in self.workspace_tree.get_children():
            self.workspace_tree.delete(item)
        self.workspace_label.configure(text=data["root"])
        for entry in data.get("entries", []):
            prefix = "DIR  " if entry["kind"] == "dir" else "     "
            indent = "  " * int(entry.get("depth", 0))
            iid = entry["path"]
            self.workspace_tree.insert(
                "",
                "end",
                iid=iid,
                text=f"{indent}{prefix}{entry['name']}",
            )

    def _preview_file(self, _event: tk.Event[Any] | None = None) -> None:
        selection = self.workspace_tree.selection()
        if not selection:
            return
        rel = selection[0]
        path = Path(self.settings.workspace) / rel
        if not path.is_file():
            return
        if path.stat().st_size > 1_000_000:
            messagebox.showinfo("预览", "文件超过 1 MB，请让智能体通过 bash 分页查看。")
            return
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            messagebox.showinfo("预览", "这是二进制或非 UTF-8 文件。")
            return
        preview = tk.Toplevel(self.root)
        preview.title(rel)
        preview.geometry("920x650")
        preview.configure(bg=PANEL)
        body = tk.Text(
            preview,
            bg="#12151b",
            fg=TEXT,
            relief="flat",
            padx=14,
            pady=12,
            wrap="none",
            font=("Consolas", 10),
        )
        body.pack(fill="both", expand=True)
        body.insert("1.0", text)
        body.configure(state="disabled")

    def _send_from_shortcut(self, _event: tk.Event[Any]) -> str:
        self.send_task()
        return "break"

    def send_task(self) -> None:
        if self.busy:
            return
        prompt = self.composer.get("1.0", "end").strip()
        if not prompt:
            return
        self.composer.delete("1.0", "end")
        self._conversation_message("你", prompt, "user")
        self.busy = True
        self.send_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._set_status("正在连接模型…", WARNING)
        payload: dict[str, Any] = {"prompt": prompt}
        if self.session_id:
            payload["session_id"] = self.session_id
        try:
            response = self.api.request("POST", "/api/tasks", payload)
        except Exception as exc:
            self.busy = False
            self.send_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            self._conversation_message("错误", str(exc), "error")
            self._set_status(str(exc), ERROR)
            return
        self.session_id = response["session_id"]
        self.active_task_id = response["task_id"]
        self.trace_text.configure(state="normal")
        self.trace_text.delete("1.0", "end")
        self.trace_text.configure(state="disabled")
        self.stream = SSEStream(
            self.base_url,
            response["events_url"],
            self.ui_events,
        )
        self.stream.start()
        self._append_text(
            self.trace_text,
            f"task {self.active_task_id} · session {self.session_id}\n",
            "muted",
        )

    def stop_task(self) -> None:
        if not self.active_task_id:
            return
        try:
            self.api.request("POST", f"/api/tasks/{self.active_task_id}/cancel", {})
            self._set_status("正在中断…", WARNING)
        except Exception as exc:
            self._set_status(str(exc), ERROR)
        self.stop_button.configure(state="disabled")

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.ui_events.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_events)

    def _handle_event(self, event: dict[str, Any]) -> None:
        kind = str(event.get("type", "message"))
        step = event.get("step", "")
        if kind == "task.started":
            self._set_status(f"任务 {event.get('task_id', '')} 运行中", WARNING)
            self._append_text(
                self.trace_text,
                f"[{time.strftime('%H:%M:%S')}] task.started model={event.get('model')}\n",
                "muted",
            )
        elif kind == "model.started":
            self._set_status(f"模型决策中 · 第 {step} 步", WARNING)
            self._append_text(
                self.trace_text,
                f"[step {step}] model.started\n",
                "muted",
            )
        elif kind == "model.completed":
            usage = event.get("usage") or {}
            usage_text = (
                f" tokens={usage.get('total_tokens')}" if usage.get("total_tokens") else ""
            )
            self._append_text(
                self.trace_text,
                f"[step {step}] model.completed{usage_text}\n",
                "muted",
            )
        elif kind == "assistant.thought":
            self._set_status("正在执行下一步…", WARNING)
            self._append_text(
                self.trace_text,
                f"[step {step}] assistant: {event.get('content', '')}\n",
                "muted",
            )
        elif kind == "tool.started":
            name = str(event.get("name", "tool"))
            call_id = str(event.get("call_id") or f"{step}-{name}-{time.time()}")
            item = self.activity.insert(
                "",
                "end",
                values=(step, name, "运行中"),
                tags=("running",),
            )
            self.activity_items[call_id] = item
            arguments = json.dumps(event.get("arguments", {}), ensure_ascii=False)
            self._append_text(
                self.trace_text,
                f"[step {step}] {name} {arguments}\n",
                "tool",
            )
            self._set_status(f"{name} 运行中", WARNING)
        elif kind == "tool.completed":
            call_id = str(event.get("call_id", ""))
            item = self.activity_items.get(call_id)
            if item and self.activity.exists(item):
                self.activity.item(item, values=(step, event.get("name"), "完成"), tags=("ok",))
            self._append_text(
                self.trace_text,
                f"[step {step}] {event.get('name')} → ok\n{event.get('content', '')}\n\n",
            )
        elif kind == "tool.failed":
            call_id = str(event.get("call_id", ""))
            item = self.activity_items.get(call_id)
            if item and self.activity.exists(item):
                self.activity.item(item, values=(step, event.get("name"), "失败"), tags=("fail",))
            self._append_text(
                self.trace_text,
                f"[step {step}] {event.get('name')} → error\n{event.get('error', '')}\n\n",
                "error",
            )
        elif kind == "change.diff":
            diff = str(event.get("diff", ""))
            self._append_text(self.diff_text, f"\n### {event.get('path')}\n", "hunk")
            for line in diff.splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    self._append_text(self.diff_text, line + "\n", "add")
                elif line.startswith("-") and not line.startswith("---"):
                    self._append_text(self.diff_text, line + "\n", "remove")
                elif line.startswith("@@"):
                    self._append_text(self.diff_text, line + "\n", "hunk")
                else:
                    self._append_text(self.diff_text, line + "\n")
        elif kind == "context.compacted":
            self._append_text(
                self.trace_text,
                f"context.compacted {event.get('before_chars')} → {event.get('after_chars')} chars\n",
                "muted",
            )
        elif kind == "agent.reminder":
            self._append_text(
                self.trace_text,
                f"agent.reminder: {event.get('message')}\n",
                "error",
            )
        elif kind == "assistant.message":
            self._conversation_message("PyCursor", str(event.get("content", "")), "assistant")
        elif kind in {"task.completed", "task.cancelled", "task.failed"}:
            self._finish_task(kind, event)
        elif kind == "stream.error":
            self._set_status(str(event.get("error")), ERROR)
            self.busy = False
            self.send_button.configure(state="normal")
            self.stop_button.configure(state="disabled")

    def _finish_task(self, kind: str, event: dict[str, Any]) -> None:
        self.busy = False
        self.send_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        if kind == "task.completed":
            elapsed = event.get("elapsed")
            self._set_status(
                f"完成 · {event.get('steps')} 步"
                + (f" · {elapsed} 秒" if elapsed is not None else ""),
                SUCCESS,
            )
        elif kind == "task.cancelled":
            self._conversation_message("已中断", str(event.get("content", "")), "error")
            self._set_status("任务已中断", WARNING)
        else:
            error = str(event.get("error") or event.get("content") or "任务失败")
            self._conversation_message("运行失败", error, "error")
            self._set_status(error.splitlines()[0][:120], ERROR)
        if self.stream:
            self.stream.close()
            self.stream = None
        self.active_task_id = None
        self._load_workspace()

    def new_task(self) -> None:
        if self.busy:
            messagebox.showinfo("PyCursor", "当前任务仍在运行，请先停止。")
            return
        self.session_id = None
        self.conversation.configure(state="normal")
        self.conversation.delete("1.0", "end")
        self.conversation.configure(state="disabled")
        for item in self.activity.get_children():
            self.activity.delete(item)
        self.activity_items.clear()
        self.diff_text.configure(state="normal")
        self.diff_text.delete("1.0", "end")
        self.diff_text.configure(state="disabled")
        self.trace_text.configure(state="normal")
        self.trace_text.delete("1.0", "end")
        self.trace_text.configure(state="disabled")
        self._set_status("新任务", MUTED)
        self.composer.focus_set()

    def _refresh_mcp_status(self) -> None:
        try:
            data = self.api.request("GET", "/api/mcp/status")
        except Exception:
            return
        servers = data.get("servers", {})
        running = sum(1 for item in servers.values() if item.get("running"))
        tools = sum(len(item.get("tools", [])) for item in servers.values())
        if running:
            self.mcp_label.configure(
                text=f"MCP {running} server · {tools} tools",
                fg=SUCCESS,
            )
        elif data.get("errors"):
            self.mcp_label.configure(text="MCP 启动失败", fg=ERROR)
        else:
            self.mcp_label.configure(text="MCP 未连接", fg=MUTED)

    def open_settings(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("设置")
        dialog.configure(bg=PANEL)
        dialog.geometry("760x560")
        dialog.transient(self.root)
        dialog.grab_set()

        frame = tk.Frame(dialog, bg=PANEL, padx=22, pady=18)
        frame.pack(fill="both", expand=True)
        fields: dict[str, tk.Entry] = {}

        def add_field(row: int, label: str, key: str, value: str, show: str = "") -> None:
            tk.Label(
                frame,
                text=label,
                bg=PANEL,
                fg=TEXT,
                font=("Microsoft YaHei UI", 9),
            ).grid(row=row, column=0, sticky="w", pady=7)
            entry = tk.Entry(
                frame,
                bg=PANEL_ALT,
                fg=TEXT,
                insertbackground=TEXT,
                relief="flat",
                show=show,
                font=("Consolas", 9),
            )
            entry.insert(0, value)
            entry.grid(row=row, column=1, sticky="ew", padx=(14, 0), pady=7, ipady=6)
            fields[key] = entry

        frame.columnconfigure(1, weight=1)
        add_field(0, "DeepSeek API Key", "api_key", self.settings.api_key, "•")
        add_field(1, "Base URL", "base_url", self.settings.base_url)
        add_field(2, "模型", "model", self.settings.model)
        add_field(3, "工作区", "workspace", self.settings.workspace)
        add_field(4, "最大步数", "max_steps", str(self.settings.max_steps))
        add_field(5, "命令超时（秒）", "command_timeout", str(self.settings.command_timeout))
        add_field(6, "MCP 配置", "mcp_config", self.settings.mcp_config)

        tk.Label(
            frame,
            text="DeepSeek 可选模型：deepseek-chat、deepseek-v4-flash（以服务商模型列表为准）",
            bg=PANEL,
            fg=MUTED,
            font=("Microsoft YaHei UI", 8),
        ).grid(row=7, column=1, sticky="w", padx=(14, 0), pady=(0, 3))

        choose_button = ttk.Button(
            frame,
            text="选择工作区",
            style="Quiet.TButton",
            command=lambda: self._choose_workspace(fields["workspace"]),
        )
        choose_button.grid(row=8, column=1, sticky="w", padx=(14, 0), pady=(6, 0))

        mcp_var = tk.BooleanVar(value=self.settings.auto_start_mcp)
        tk.Checkbutton(
            frame,
            text="启动时连接 MCP",
            variable=mcp_var,
            bg=PANEL,
            fg=TEXT,
            selectcolor=PANEL_ALT,
            activebackground=PANEL,
            activeforeground=TEXT,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=9, column=1, sticky="w", padx=(14, 0), pady=(10, 0))

        buttons = tk.Frame(frame, bg=PANEL)
        buttons.grid(row=10, column=0, columnspan=2, sticky="e", pady=(22, 0))

        def save() -> None:
            payload: dict[str, Any] = {
                "api_key": fields["api_key"].get().strip(),
                "base_url": fields["base_url"].get().strip(),
                "model": fields["model"].get().strip(),
                "workspace": fields["workspace"].get().strip(),
                "max_steps": fields["max_steps"].get().strip(),
                "command_timeout": fields["command_timeout"].get().strip(),
                "mcp_config": fields["mcp_config"].get().strip(),
                "auto_start_mcp": mcp_var.get(),
            }
            try:
                updated = self.api.request("POST", "/api/config", payload)
                self.settings = Settings.load()
                self.application.settings = self.settings
                self.model_label.configure(text=updated.get("model", self.settings.model))
                self._load_workspace()
                if mcp_var.get():
                    self.api.request("POST", "/api/mcp/reload", {})
                self._refresh_mcp_status()
                dialog.destroy()
            except Exception as exc:
                messagebox.showerror("设置保存失败", str(exc), parent=dialog)

        ttk.Button(buttons, text="取消", style="Quiet.TButton", command=dialog.destroy).pack(
            side="right", padx=(8, 0)
        )
        ttk.Button(buttons, text="保存", style="Accent.TButton", command=save).pack(
            side="right"
        )

    def _choose_workspace(self, entry: tk.Entry) -> None:
        selected = filedialog.askdirectory(
            parent=self.root,
            initialdir=entry.get() or str(Path.home()),
        )
        if selected:
            entry.delete(0, "end")
            entry.insert(0, selected)

    def _set_status(self, text: str, color: str = MUTED) -> None:
        self.status_label.configure(text=text, fg=color)

    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        if self.stream:
            self.stream.close()
        self.server.shutdown()
        self.server.server_close()
        self.application.mcp.stop_all()
        self.root.destroy()


def launch_desktop(settings: Settings) -> None:
    server, application = start_server(settings, host="127.0.0.1", port=0)
    app = DesktopApp(settings, server, application)
    app.run()


def main() -> None:
    launch_desktop(Settings.load())


if __name__ == "__main__":
    main()

