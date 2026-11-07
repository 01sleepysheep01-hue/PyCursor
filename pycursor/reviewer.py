from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .llm import ChatReply, LLMError
from .tools import (
    TOOL_SCHEMAS,
    ToolContext,
    ToolError,
    execute_tool,
)


REVIEW_DIFF_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "review_diff",
        "description": (
            "启动独立上下文的 reviewer，只读审查当前 Git diff。"
            "它只返回最终判定和按严重程度排序的发现。"
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
}

REVIEWER_SYSTEM_PROMPT = """你是 PyCursor 的独立代码审查器。

只使用 read 和 bash；bash 只允许执行 git diff 命令。不要修改任何文件。
按以下清单逐项检查：
1. 有没有改到不该改的文件或泄露敏感信息。
2. 有没有新增未声明的依赖。
3. 有没有 `except: pass` 或吞掉异常的写法。
4. 新分支是否缺少测试覆盖。
5. diff 里是否残留 `print(`、`TODO` 或调试代码。

先运行 git diff --stat 和 git diff --unified=3，再读取必要上下文。
只返回最后一条审查结论，不返回工具过程。发现按严重程度排序，
每项写明文件位置、问题和影响；没有发现时也要说明剩余风险。
"""

REVIEWER_TOOL_SCHEMAS = [
    schema
    for schema in TOOL_SCHEMAS
    if schema.get("function", {}).get("name") in {"read", "bash"}
]
SAFE_GIT_DIFF_PATTERN = re.compile(r"^git(?:\.exe)?\s+diff(?:\s+.*)?$", re.IGNORECASE)
SHELL_CONTROL_PATTERN = re.compile(r"(?:&&|\|\||[;|<>]|\r|\n)")


class ReviewerClient(Protocol):
    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        timeout: int = 120,
    ) -> ChatReply: ...


@dataclass(frozen=True, slots=True)
class ReviewerResult:
    content: str
    steps: int
    failed: bool = False


def reviewer_enabled() -> bool:
    value = os.environ.get("ENABLE_REVIEWER", "1").strip().lower()
    return value not in {"0", "false", "no", "off", "disabled"}


def _is_allowed_review_command(command: str) -> bool:
    normalized = command.strip()
    if not normalized or SHELL_CONTROL_PATTERN.search(normalized):
        return False
    if any(
        token in normalized
        for token in ("$(", "`", "--output", "--ext-diff", "--no-index")
    ):
        return False
    return SAFE_GIT_DIFF_PATTERN.fullmatch(normalized) is not None


class ReviewerAgent:
    def __init__(
        self,
        *,
        client: ReviewerClient,
        workspace: Path,
        cancel_event: threading.Event,
        command_timeout: int,
        max_steps: int = 6,
    ) -> None:
        self.client = client
        self.workspace = workspace.resolve()
        self.cancel_event = cancel_event
        self.command_timeout = command_timeout
        self.max_steps = max(2, max_steps)

    def _execute(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "bash":
            command = arguments.get("command")
            if not isinstance(command, str) or not _is_allowed_review_command(command):
                raise ToolError("Reviewer 的 bash 只允许执行单条 git diff 命令。")
        elif name != "read":
            raise ToolError(f"Reviewer 不允许使用工具：{name}")
        ctx = ToolContext(
            workspace=self.workspace,
            cancel_event=self.cancel_event,
            command_timeout=self.command_timeout,
        )
        return execute_tool(name, arguments, ctx)

    def review(self) -> ReviewerResult:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": REVIEWER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "审查当前工作区未提交的 Git diff。先看 diff，再只给最终结论。"
                ),
            },
        ]

        try:
            for step in range(1, self.max_steps + 1):
                if self.cancel_event.is_set():
                    return ReviewerResult("Reviewer 已取消。", step, failed=True)
                reply = self.client.complete(
                    messages,
                    REVIEWER_TOOL_SCHEMAS,
                    timeout=120,
                )
                if not reply.tool_calls:
                    content = reply.content.strip()
                    if not content:
                        content = "Reviewer 未给出审查结论。"
                    return ReviewerResult(content=content, steps=step)

                messages.append(
                    {
                        "role": "assistant",
                        "content": reply.content or None,
                        "tool_calls": reply.tool_calls,
                    }
                )
                for call in reply.tool_calls:
                    if self.cancel_event.is_set():
                        return ReviewerResult("Reviewer 已取消。", step, failed=True)
                    call_id = str(call.get("id", ""))
                    function = call.get("function") or {}
                    name = str(function.get("name", ""))
                    raw_arguments = function.get("arguments", "{}")
                    try:
                        arguments = (
                            json.loads(raw_arguments)
                            if isinstance(raw_arguments, str)
                            else dict(raw_arguments)
                        )
                        observation = self._execute(name, arguments)
                        content: str | list[dict[str, Any]] = observation.content
                    except (ToolError, json.JSONDecodeError, TypeError, ValueError) as exc:
                        content = f"Reviewer 工具错误：{exc}"
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": content,
                        }
                    )
        except LLMError as exc:
            return ReviewerResult(f"Reviewer 模型调用失败：{exc}", 0, failed=True)

        return ReviewerResult(
            f"Reviewer 达到 {self.max_steps} 步上限，未形成最终结论。",
            self.max_steps,
            failed=True,
        )
