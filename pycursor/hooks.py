from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .tools import ToolError


SENSITIVE_SUFFIXES = {".pem", ".key"}


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


def before_tool(
    name: str,
    arguments: dict[str, Any],
    workspace: Path,
) -> None:
    if not hooks_enabled() or name not in {"write", "edit"}:
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
