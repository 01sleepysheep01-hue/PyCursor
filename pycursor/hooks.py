from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .tools import ToolError


SENSITIVE_SUFFIXES = {".pem", ".key"}
SEGMENT_PATTERN = re.compile(r"(?:&&|\|\||[;\n])")


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
