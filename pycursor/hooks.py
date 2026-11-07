from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .tools import ToolError


SENSITIVE_SUFFIXES = {".pem", ".key"}
CODE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".py",
    ".rs",
    ".ts",
    ".tsx",
}
SEGMENT_PATTERN = re.compile(r"(?:&&|\|\||[;\n])")
ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*m")
FAILURE_HEADER_PATTERN = re.compile(r"^(?:FAIL|ERROR):\s+.+$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class PostToolResult:
    summary: str
    command: str
    exit_code: int


def hooks_enabled() -> bool:
    value = os.environ.get("ENABLE_HOOKS", "1").strip().lower()
    return value not in {"0", "false", "no", "off", "disabled"}


def _tool_path(arguments: dict[str, Any], workspace: Path) -> Path | None:
    value = arguments.get("path")
    if not isinstance(value, str) or not value.strip():
        return None
    raw = Path(value)
    if raw.is_absolute():
        return raw.resolve(strict=False)
    return (workspace / raw).resolve(strict=False)


def _sensitive_file_name(path: Path) -> bool:
    name = path.name.casefold()
    if name == ".env.example":
        return False
    if name == ".env" or name.startswith(".env."):
        return True
    return path.suffix.casefold() in SENSITIVE_SUFFIXES


def _command_segments(command: str) -> list[str]:
    return [segment.strip() for segment in SEGMENT_PATTERN.split(command)]


def _short_flags(tokens: list[str]) -> set[str]:
    flags: set[str] = set()
    for token in tokens:
        if token.startswith("-") and not token.startswith("--"):
            flags.update(token[1:].casefold())
    return flags


def _reject_rm_recursive_force(segment: str) -> None:
    match = re.match(
        r"^(?:sudo\s+)?(?:command\s+)?rm(?:\.exe)?\s+(.+)$",
        segment,
        flags=re.IGNORECASE,
    )
    if not match:
        return
    tokens = match.group(1).split()
    short_flags = _short_flags(tokens)
    recursive = "r" in short_flags or any(
        token.casefold() == "--recursive" for token in tokens
    )
    force = "f" in short_flags or any(
        token.casefold() == "--force" for token in tokens
    )
    if recursive and force:
        raise ToolError(
            "PreToolUse Hook 拒绝：rm -rf / --recursive --force 会不可恢复地删除文件。"
            "请改用 git restore <path> 恢复已跟踪文件；临时文件可用 Python "
            "tempfile 管理，或先将目标移入回收站并核对精确路径。"
        )


def _reject_dangerous_git(segment: str) -> None:
    git_prefix = r"^(?:sudo\s+)?git(?:\.exe)?(?:\s+-C\s+\S+)?\s+"
    push = re.match(git_prefix + r"push\b(.*)$", segment, flags=re.IGNORECASE)
    if push:
        tokens = push.group(1).split()
        forced = (
            "f" in _short_flags(tokens)
            or any(
                token.casefold() in {"--force", "--force-with-lease", "--force-if-includes"}
                for token in tokens
            )
        )
        if forced:
            raise ToolError(
                "PreToolUse Hook 拒绝：强制推送可能覆盖远端提交。"
                "先运行 git fetch 与 git pull --rebase，解决差异后普通 git push；"
                "确需 force-with-lease 时，先核对远端 SHA 并由用户明确确认。"
            )

    reset = re.match(git_prefix + r"reset\b(.*)$", segment, flags=re.IGNORECASE)
    if reset:
        tokens = reset.group(1).split()
        if any(token.casefold() == "--hard" for token in tokens):
            raise ToolError(
                "PreToolUse Hook 拒绝：git reset --hard 会丢弃工作区改动。"
                "只撤销暂存请用 git restore --staged <path>；撤销已有提交请用 "
                "git revert <commit>；需要保留改动时先用 git stash。"
            )


def _check_bash_command(arguments: dict[str, Any]) -> None:
    command = arguments.get("command")
    if not isinstance(command, str):
        return
    for segment in _command_segments(command):
        _reject_rm_recursive_force(segment)
        _reject_dangerous_git(segment)


def _extract_test_summary(output: str, exit_code: int) -> str:
    clean = ANSI_PATTERN.sub("", output).strip()
    lines = [line.rstrip() for line in clean.splitlines() if line.strip()]
    status_lines = [
        line.strip()
        for line in lines
        if re.match(r"^(?:Ran\s+\d+\s+tests?|OK(?:\s|$)|FAILED\s*\()", line.strip())
    ]
    failures = FAILURE_HEADER_PATTERN.findall(clean)[:3]

    details: list[str] = []
    for index, line in enumerate(lines):
        if not re.match(r"^(?:FAIL|ERROR):", line.strip()):
            continue
        window = [candidate.strip() for candidate in lines[index + 1 : index + 12]]
        detail = next((item for item in window if "Error:" in item), None)
        if detail is None:
            detail = next(
                (item for item in window if "assert" in item.casefold()),
                None,
            )
        if detail:
            details.append(detail)

    summary: list[str] = []
    if status_lines:
        summary.extend(status_lines[-2:])
    else:
        summary.append(f"测试命令退出码：{exit_code}")
    for index, failure in enumerate(failures):
        summary.append(f"- {failure}")
        if index < len(details):
            summary.append(f"  {details[index]}")
    if not failures and exit_code != 0 and lines:
        summary.extend(f"- {line}" for line in lines[:3])
    return "\n".join(summary).strip()[:2_000]


def after_tool(
    name: str,
    arguments: dict[str, Any],
    workspace: Path,
    *,
    timeout: int = 45,
) -> PostToolResult | None:
    if not hooks_enabled() or name not in {"write", "edit"}:
        return None
    target = _tool_path(arguments, workspace)
    if target is None or target.suffix.casefold() not in CODE_SUFFIXES:
        return None

    command = [sys.executable, "-m", "unittest", "discover"]
    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=max(1, timeout),
            check=False,
        )
        combined = "\n".join(
            part for part in (completed.stdout, completed.stderr) if part.strip()
        )
        details = _extract_test_summary(combined, completed.returncode)
        exit_code = completed.returncode
    except subprocess.TimeoutExpired:
        details = f"自动测试超时（{timeout}s），已终止测试命令。"
        exit_code = -1
    except OSError as exc:
        details = f"无法启动自动测试：{type(exc).__name__}: {exc}"
        exit_code = -1

    summary = (
        f"[PostToolUse 自动测试] 修改 {target.name} 后执行 "
        f"`python -m unittest discover`：\n{details}"
    )
    return PostToolResult(
        summary=summary[:2_200],
        command=" ".join(command),
        exit_code=exit_code,
    )


def before_tool(
    name: str,
    arguments: dict[str, Any],
    workspace: Path,
) -> None:
    if not hooks_enabled():
        return
    if name == "bash":
        _check_bash_command(arguments)
        return
    if name not in {"write", "edit"}:
        return
    target = _tool_path(arguments, workspace)
    if target is None or not _sensitive_file_name(target):
        return

    if target.name.casefold() == ".env" or target.name.casefold().startswith(".env."):
        alternative = (
            "变量名和占位符可写入 .env.example；真实值只放在系统环境变量或 "
            "%USERPROFILE%\\.pycursor\\config.json。"
        )
    else:
        alternative = (
            "密钥文件不得由智能体写入；请通过受控密钥管理或本地环境配置提供。"
        )
    raise ToolError(
        f"PreToolUse Hook 拒绝：{name} 不得修改受保护文件 "
        f"{target.name}。密钥不入库，使用环境变量。{alternative}"
    )
