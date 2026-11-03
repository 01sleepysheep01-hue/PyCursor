from __future__ import annotations

import base64
import ctypes
import difflib
import json
import os
import signal
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_TEXT_BYTES = 1_000_000
MAX_OUTPUT_CHARS = 30_000
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_IMAGE_BYTES = 12_000_000


class ToolError(Exception):
    """A readable tool failure that can be returned to the model."""


@dataclass(slots=True)
class ToolObservation:
    text: str
    content: str | list[dict[str, Any]]
    metadata: dict[str, Any]


@dataclass(slots=True)
class ToolContext:
    workspace: Path
    cancel_event: threading.Event
    command_timeout: int = 45

    def safe_path(self, value: str) -> Path:
        raw = Path(value)
        candidate = (self.workspace / raw).resolve() if not raw.is_absolute() else raw.resolve()
        try:
            candidate.relative_to(self.workspace)
        except ValueError as exc:
            raise ToolError(
                f"拒绝访问工作区外路径：{value}。工作区是 {self.workspace}"
            ) from exc
        return candidate


def _display_relative(path: Path, workspace: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


def _line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def read(ctx: ToolContext, path: str, offset: int = 1, limit: int = 200) -> ToolObservation:
    """Read a workspace file, paginating text and returning images as multimodal blocks."""
    target = ctx.safe_path(path)
    if not target.exists():
        raise ToolError(f"文件不存在：{path}；工作区：{ctx.workspace}")
    if not target.is_file():
        raise ToolError(f"不是文件：{path}")
    if target.stat().st_size > MAX_TEXT_BYTES and target.suffix.lower() not in IMAGE_SUFFIXES:
        raise ToolError(
            f"文件过大：{target.stat().st_size} bytes。请用 bash 的 head/tail 或指定更窄的读取范围。"
        )

    if target.suffix.lower() in IMAGE_SUFFIXES:
        if target.stat().st_size > MAX_IMAGE_BYTES:
            raise ToolError(
                f"图片过大：{target.stat().st_size} bytes；上限是 {MAX_IMAGE_BYTES} bytes。"
            )
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }[target.suffix.lower()]
        encoded = base64.b64encode(target.read_bytes()).decode("ascii")
        rel = _display_relative(target, ctx.workspace)
        text = f"图片：{rel}（{mime}，已作为多模态内容返回）"
        return ToolObservation(
            text=text,
            content=[
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
            ],
            metadata={"path": rel, "kind": "image", "mime": mime},
        )

    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ToolError(f"{path} 不是 UTF-8 文本；请用 bash 查看二进制内容。") from exc
    start = max(1, int(offset))
    count = max(1, min(int(limit), 1000))
    selected = lines[start - 1 : start - 1 + count]
    remaining = max(0, len(lines) - (start - 1 + len(selected)))
    shown = "\n".join(
        f"{line_no:>6} | {line}"
        for line_no, line in enumerate(selected, start=start)
    )
    if not shown:
        shown = f"{path} 从第 {start} 行起没有内容"
    if remaining:
        shown += f"\n... 还有 {remaining} 行；下一次从 offset={start + len(selected)} 继续"
    rel = _display_relative(target, ctx.workspace)
    return ToolObservation(
        text=shown,
        content=shown,
        metadata={
            "path": rel,
            "kind": "text",
            "lines": len(lines),
            "offset": start,
            "returned": len(selected),
            "remaining": remaining,
        },
    )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def write(ctx: ToolContext, path: str, content: str) -> ToolObservation:
    """Create or replace a UTF-8 file atomically, creating parent directories."""
    target = ctx.safe_path(path)
    if target.exists() and not target.is_file():
        raise ToolError(f"目标不是文件：{path}")
    old = ""
    existed = target.exists()
    if existed:
        try:
            old = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolError(f"拒绝覆盖非 UTF-8 文件：{path}") from exc
    _atomic_write(target, content)
    old_lines = _line_count(old)
    new_lines = _line_count(content)
    rel = _display_relative(target, ctx.workspace)
    action = "更新" if existed else "创建"
    text = f"{action} {rel}：{old_lines} 行 → {new_lines} 行"
    diff = "\n".join(
        difflib.unified_diff(
            old.splitlines(),
            content.splitlines(),
            fromfile=f"a/{rel}" if existed else "/dev/null",
            tofile=f"b/{rel}",
            lineterm="",
        )
    )
    return ToolObservation(
        text=text,
        content=text,
        metadata={
            "path": rel,
            "kind": "write",
            "old_lines": old_lines,
            "new_lines": new_lines,
            "diff": diff[:MAX_OUTPUT_CHARS],
        },
    )


def edit(ctx: ToolContext, path: str, old: str, new: str) -> ToolObservation:
    """Replace one exact, unique string and fail rather than guess."""
    target = ctx.safe_path(path)
    if not target.exists() or not target.is_file():
        raise ToolError(f"文件不存在：{path}")
    try:
        current = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ToolError(f"只能编辑 UTF-8 文本：{path}") from exc
    if old == "":
        raise ToolError("old 不能为空；创建文件请用 write，追加内容请提供带锚点的 old。")
    occurrences = current.count(old)
    if occurrences != 1:
        if occurrences == 0:
            raise ToolError(
                f"edit 失败：old 在 {path} 中没有出现。请先 read 并补充上下文，再重试。"
            )
        raise ToolError(
            f"edit 失败：old 在 {path} 中出现 {occurrences} 次，无法唯一替换。"
            "请扩大匹配上下文，确保 old 唯一。"
        )
    updated = current.replace(old, new, 1)
    _atomic_write(target, updated)
    rel = _display_relative(target, ctx.workspace)
    diff = "\n".join(
        difflib.unified_diff(
            current.splitlines(),
            updated.splitlines(),
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
            lineterm="",
        )
    )
    return ToolObservation(
        text=f"已更新 {rel}，精确替换 1 处。",
        content=f"已更新 {rel}，精确替换 1 处。",
        metadata={
            "path": rel,
            "kind": "edit",
            "diff": diff[:MAX_OUTPUT_CHARS],
            "old": old,
            "new": new,
        },
    )


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            process.wait(timeout=1)
            return
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    job = getattr(process, "_pycursor_job", None)
    if os.name == "nt" and job:
        try:
            ctypes.windll.kernel32.TerminateJobObject(job, 1)
            process.wait(timeout=1)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=2,
                check=False,
            )
        else:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _assign_windows_job(process: subprocess.Popen[str]) -> None:
    if os.name != "nt":
        return
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimits),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x00002000
    ok = kernel32.SetInformationJobObject(
        job,
        9,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
    )
    process_handle = kernel32.OpenProcess(0x0100 | 0x0400, False, process.pid)
    if ok and process_handle:
        ok = kernel32.AssignProcessToJobObject(job, process_handle)
        kernel32.CloseHandle(process_handle)
    if ok:
        setattr(process, "_pycursor_job", job)
    else:
        kernel32.CloseHandle(job)


def _close_process_streams(process: subprocess.Popen[str]) -> None:
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass


def _close_windows_job(process: subprocess.Popen[str]) -> None:
    job = getattr(process, "_pycursor_job", None)
    if os.name == "nt" and job:
        try:
            ctypes.windll.kernel32.CloseHandle(job)
        except OSError:
            pass
        setattr(process, "_pycursor_job", None)


def _drain_stream(stream: Any, sink: list[str]) -> None:
    total = 0
    try:
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break
            if total < MAX_OUTPUT_CHARS:
                available = MAX_OUTPUT_CHARS - total
                sink.append(chunk[:available])
                total += min(len(chunk), available)
    except (OSError, ValueError):
        pass


def bash(ctx: ToolContext, command: str, timeout: int = 30) -> ToolObservation:
    """Run a shell command in the workspace with timeout, cancellation and output caps."""
    if not command.strip():
        raise ToolError("command 不能为空")
    effective_timeout = max(1, min(int(timeout), ctx.command_timeout))
    popen_kwargs: dict[str, Any] = {
        "cwd": ctx.workspace,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "shell": True,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    process = subprocess.Popen(command, **popen_kwargs)
    _assign_windows_job(process)
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    stdout_thread = threading.Thread(
        target=_drain_stream,
        args=(process.stdout, stdout_chunks),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_drain_stream,
        args=(process.stderr, stderr_chunks),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    deadline = __import__("time").monotonic() + effective_timeout
    while process.poll() is None:
        if ctx.cancel_event.is_set():
            _terminate_process(process)
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
            _close_process_streams(process)
            _close_windows_job(process)
            raise ToolError("命令被用户中断")
        if __import__("time").monotonic() >= deadline:
            _terminate_process(process)
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
            _close_process_streams(process)
            _close_windows_job(process)
            raise ToolError(f"命令超过 {effective_timeout} 秒，已终止")
        ctx.cancel_event.wait(0.1)

    stdout_thread.join(timeout=2)
    stderr_thread.join(timeout=2)
    _close_process_streams(process)
    _close_windows_job(process)
    stdout = "".join(stdout_chunks)
    stderr = "".join(stderr_chunks)
    exit_code = int(process.returncode)
    stdout = stdout[:MAX_OUTPUT_CHARS]
    stderr = stderr[:MAX_OUTPUT_CHARS]
    observation = {
        "command": command,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "timed_out": False,
    }
    text = (
        f"$ {command}\n"
        f"exit_code: {exit_code}\n"
        f"--- stdout ---\n{stdout or '(empty)'}\n"
        f"--- stderr ---\n{stderr or '(empty)'}"
    )
    return ToolObservation(
        text=text,
        content=json.dumps(observation, ensure_ascii=False),
        metadata={"kind": "bash", **observation},
    )


TOOL_FUNCTIONS = {
    "read": read,
    "write": write,
    "edit": edit,
    "bash": bash,
}


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": (
                "读取工作区内文件的文本并返回行号。文本过大时用 offset/limit 分页；"
                "读取 png/jpg/gif/webp 时返回多模态图片块。修改前必须先读。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对工作区的文件路径"},
                    "offset": {"type": "integer", "minimum": 1, "default": 1},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write",
            "description": (
                "创建或完整替换一个 UTF-8 文件。会自动创建父目录并使用原子写入。"
                "修改已有文件中的一小段时优先用 edit。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit",
            "description": (
                "在文件中精确替换一个唯一的 old 字符串。old 必须出现且只能出现一次；"
                "出现零次或多次都会报错。先用 read 获得足够上下文。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old": {"type": "string", "description": "要替换的唯一原文"},
                    "new": {"type": "string", "description": "替换后的内容"},
                },
                "required": ["path", "old", "new"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": (
                "在工作区运行 shell 命令，用于搜索、Git、安装依赖和运行测试。"
                "返回 stdout、stderr 与 exit_code；非零退出码也是正常观察。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 300,
                        "default": 30,
                    },
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
]


def execute_tool(
    name: str,
    arguments: dict[str, Any],
    ctx: ToolContext,
) -> ToolObservation:
    function = TOOL_FUNCTIONS.get(name)
    if function is None:
        raise ToolError(f"未知工具：{name}。允许的工具：{', '.join(TOOL_FUNCTIONS)}")
    try:
        return function(ctx, **arguments)
    except TypeError as exc:
        raise ToolError(f"{name} 参数错误：{exc}") from exc

