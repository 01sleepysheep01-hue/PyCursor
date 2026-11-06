from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


MAX_AGENTS_BYTES = 131_072


class AgentInstructionError(ValueError):
    """An AGENTS.md file cannot be loaded safely."""


@dataclass(frozen=True, slots=True)
class AgentInstructionFile:
    source: Path
    scope: str
    content: str


@dataclass(frozen=True, slots=True)
class AgentInstructionBundle:
    files: tuple[AgentInstructionFile, ...] = ()

    def render(self) -> str:
        if not self.files:
            return ""
        sections = [
            "以下 AGENTS.md 按全局到项目、从上层到更具体目录排列；"
            "发生冲突时以后面的规则为准。"
        ]
        for item in self.files:
            sections.append(
                f"## {item.scope} AGENTS.md: {item.source}\n{item.content}"
            )
        return "\n\n".join(sections)


def agents_enabled() -> bool:
    value = os.environ.get("ENABLE_AGENTS", "1").strip().lower()
    return value not in {"0", "false", "no", "off", "disabled"}


def _read_instruction_file(path: Path, scope: str) -> AgentInstructionFile:
    resolved = path.expanduser().resolve()
    try:
        size = resolved.stat().st_size
    except OSError as exc:
        raise AgentInstructionError(f"无法读取 {scope} AGENTS.md：{resolved}") from exc
    if size > MAX_AGENTS_BYTES:
        raise AgentInstructionError(
            f"{scope} AGENTS.md 超过 {MAX_AGENTS_BYTES} bytes：{resolved}"
        )
    try:
        content = resolved.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise AgentInstructionError(
            f"{scope} AGENTS.md 不是可读的 UTF-8 文件：{resolved}"
        ) from exc
    return AgentInstructionFile(
        source=resolved,
        scope=scope,
        content=content,
    )


def _global_paths() -> tuple[Path, ...]:
    home = Path.home()
    codex_home = Path(os.environ.get("CODEX_HOME", home / ".codex"))
    return (codex_home / "AGENTS.md", home / "AGENTS.md")


def _project_paths(project_root: Path) -> tuple[Path, ...]:
    chain: list[Path] = []
    current = project_root.resolve()
    while True:
        chain.append(current / "AGENTS.md")
        if current.parent == current:
            break
        current = current.parent
    chain.reverse()
    return tuple(chain)


def load_agent_instructions(
    project_root: Path | str,
    *,
    global_paths: tuple[Path, ...] | list[Path] | None = None,
) -> AgentInstructionBundle:
    if not agents_enabled():
        return AgentInstructionBundle()

    root = Path(project_root).expanduser().resolve()
    selected: list[tuple[Path, str]] = []
    for path in tuple(global_paths) if global_paths is not None else _global_paths():
        selected.append((path, "全局"))
    for path in _project_paths(root):
        selected.append((path, "项目"))

    files: list[AgentInstructionFile] = []
    seen: set[Path] = set()
    for path, scope in selected:
        resolved = path.expanduser().resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        files.append(_read_instruction_file(resolved, scope))
    return AgentInstructionBundle(files=tuple(files))
