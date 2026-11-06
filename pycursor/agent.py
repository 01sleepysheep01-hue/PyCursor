from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .agents import AgentInstructionBundle, load_agent_instructions
from .config import Settings
from .hooks import before_tool
from .llm import ChatReply, LLMError, OpenAICompatibleClient
from .mcp import MCPManager
from .skills import SkillRegistry, load_skills, skill_catalog_lines
from .tools import (
    TOOL_SCHEMAS,
    ToolContext,
    ToolError,
    ToolObservation,
    execute_tool,
)


SYSTEM_PROMPT = """你是 PyCursor，一名在用户本地工作区工作的编码智能体。

工作规则：
1. 修改文件前先用 read 获取真实内容和行号。不得凭记忆猜测文件内容。
2. 小范围修改用 edit；只有创建文件或确需整体重写时才用 write。
3. 运行测试、搜索、Git 和依赖命令使用 bash。非零退出码是诊断信息，应继续处理。
4. edit 因“出现多次”失败时，不要盲目重试；先 read 扩大上下文，再提交唯一匹配。
5. 完成后必须用测试或命令验证结果。不要声称“已修好”而没有验证。
6. 保护工作区外文件，不读取或写入工作区外路径。
7. 最终答复使用用户所用语言，简明说明改动、验证命令与仍存在的风险。
8. 只有当任务确实完成或明确无法继续时才停止调用工具。
"""


USE_SKILL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "use_skill",
        "description": (
            "按名称加载一个技能的完整操作说明。"
            "仅当当前任务匹配技能目录中的 description 时调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "技能目录中的技能名称，例如 run-tests。",
                }
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
}


class ChatClient(Protocol):
    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        timeout: int = 120,
    ) -> ChatReply: ...


@dataclass(slots=True)
class AgentResult:
    content: str
    trace: list[str]
    cancelled: bool = False
    failed: bool = False


def _message_chars(messages: list[dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total += len(content)
        else:
            total += len(json.dumps(content, ensure_ascii=False))
    return total


class AgentRunner:
    def __init__(
        self,
        settings: Settings,
        *,
        client: ChatClient | None = None,
        mcp: MCPManager | None = None,
        skills: SkillRegistry | None = None,
        agent_instructions: AgentInstructionBundle | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or OpenAICompatibleClient(settings)
        self.mcp = mcp
        self.skills = (
            skills
            if skills is not None
            else load_skills(self.settings.workspace)
        )
        self.agent_instructions = (
            agent_instructions
            if agent_instructions is not None
            else load_agent_instructions(self.settings.workspace)
        )

    def run(
        self,
        prompt: str,
        *,
        task_id: str,
        cancel_event: threading.Event,
        emit: Any,
        history: list[dict[str, str]] | None = None,
    ) -> AgentResult:
        started = time.monotonic()
        trace: list[str] = []
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt()},
            *[
                {"role": item["role"], "content": item["content"]}
                for item in (history or [])
                if item.get("role") in {"user", "assistant"}
            ],
            {"role": "user", "content": prompt},
        ]
        tools = [*TOOL_SCHEMAS]
        if self.skills.skills:
            tools.append(USE_SKILL_SCHEMA)
        if self.mcp:
            tools.extend(self.mcp.schemas())
        repeated: dict[str, int] = {}
        ctx = ToolContext(
            workspace=Path(self.settings.workspace),
            cancel_event=cancel_event,
            command_timeout=self.settings.command_timeout,
        )
        emit("task.started", {"task_id": task_id, "prompt": prompt, "model": self.settings.model})

        try:
            for step in range(1, self.settings.max_steps + 1):
                if cancel_event.is_set():
                    raise InterruptedError
                self._compact_if_needed(messages, emit)
                emit(
                    "model.started",
                    {
                        "task_id": task_id,
                        "step": step,
                        "max_steps": self.settings.max_steps,
                    },
                )
                reply = self.client.complete(messages, tools, timeout=120)
                emit(
                    "model.completed",
                    {
                        "task_id": task_id,
                        "step": step,
                        "usage": reply.usage,
                    },
                )
                trace.append(f"[step {step}] model")
                if not reply.tool_calls:
                    content = reply.content.strip() or "任务结束，但模型没有给出文字说明。"
                    emit(
                        "assistant.message",
                        {"task_id": task_id, "content": content, "step": step},
                    )
                    emit(
                        "task.completed",
                        {
                            "task_id": task_id,
                            "content": content,
                            "steps": step,
                            "elapsed": round(time.monotonic() - started, 2),
                        },
                    )
                    return AgentResult(content=content, trace=trace)

                assistant_message: dict[str, Any] = {
                    "role": "assistant",
                    "content": reply.content or None,
                    "tool_calls": reply.tool_calls,
                }
                messages.append(assistant_message)
                if reply.content.strip():
                    emit(
                        "assistant.thought",
                        {
                            "task_id": task_id,
                            "content": reply.content.strip(),
                            "step": step,
                        },
                    )

                for call in reply.tool_calls:
                    if cancel_event.is_set():
                        raise InterruptedError
                    call_id = str(call.get("id", ""))
                    function = call.get("function") or {}
                    name = str(function.get("name", ""))
                    raw_args = function.get("arguments", "{}")
                    try:
                        arguments = (
                            json.loads(raw_args)
                            if isinstance(raw_args, str)
                            else dict(raw_args)
                        )
                    except (json.JSONDecodeError, TypeError, ValueError):
                        observation_text = (
                            f"工具参数不是合法 JSON：{str(raw_args)[:500]}。"
                            "请重新发起该工具调用。"
                        )
                        emit(
                            "tool.failed",
                            {
                                "task_id": task_id,
                                "step": step,
                                "name": name,
                                "error": observation_text,
                            },
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call_id,
                                "content": observation_text,
                            }
                        )
                        trace.append(f"[step {step}] {name} argument error")
                        continue

                    fingerprint = name + json.dumps(
                        arguments,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    repeated[fingerprint] = repeated.get(fingerprint, 0) + 1
                    reminder = ""
                    if repeated[fingerprint] >= 3:
                        reminder = (
                            "同一个工具参数已经重复提交 3 次。不要继续机械重试；"
                            "先重新读取上下文，改变切分位置或匹配范围，再决定下一步。"
                        )
                        emit(
                            "agent.reminder",
                            {"task_id": task_id, "step": step, "message": reminder},
                        )

                    emit(
                        "tool.started",
                        {
                            "task_id": task_id,
                            "step": step,
                            "name": name,
                            "arguments": arguments,
                            "call_id": call_id,
                        },
                    )
                    try:
                        observation = self._execute(name, arguments, ctx)
                        event_data = {
                            "task_id": task_id,
                            "step": step,
                            "name": name,
                            "content": observation.text,
                            "metadata": observation.metadata,
                            "call_id": call_id,
                        }
                        emit("tool.completed", event_data)
                        if observation.metadata.get("diff"):
                            emit(
                                "change.diff",
                                {
                                    "task_id": task_id,
                                    "step": step,
                                    "path": observation.metadata.get("path"),
                                    "diff": observation.metadata["diff"],
                                },
                            )
                        content: str | list[dict[str, Any]] = observation.content
                        trace.append(
                            f"[step {step}] {name}("
                            + ", ".join(f"{k}={v!r}" for k, v in arguments.items())
                            + ") → ok"
                        )
                    except ToolError as exc:
                        content = str(exc)
                        emit(
                            "tool.failed",
                            {
                                "task_id": task_id,
                                "step": step,
                                "name": name,
                                "error": content,
                                "call_id": call_id,
                            },
                        )
                        trace.append(f"[step {step}] {name} → error: {content}")
                    except Exception as exc:
                        content = f"{name} 内部错误：{type(exc).__name__}: {exc}"
                        emit(
                            "tool.failed",
                            {
                                "task_id": task_id,
                                "step": step,
                                "name": name,
                                "error": content,
                                "call_id": call_id,
                            },
                        )
                        trace.append(f"[step {step}] {name} → internal error")

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": content,
                        }
                    )
                    if reminder:
                        messages.append({"role": "user", "content": reminder})

            content = (
                f"已达到 {self.settings.max_steps} 步上限，任务未确认完成。"
                "请查看 trace，缩小任务范围后继续。"
            )
            emit("task.failed", {"task_id": task_id, "error": content, "steps": self.settings.max_steps})
            return AgentResult(content=content, trace=trace, failed=True)
        except InterruptedError:
            content = "任务已被用户中断。已停止后续工具调用和正在运行的命令。"
            emit("task.cancelled", {"task_id": task_id, "content": content})
            return AgentResult(content=content, trace=trace, cancelled=True)
        except LLMError as exc:
            content = str(exc)
            emit("task.failed", {"task_id": task_id, "error": content})
            return AgentResult(content=content, trace=trace, failed=True)
        except Exception as exc:
            content = f"任务异常：{type(exc).__name__}: {exc}"
            emit("task.failed", {"task_id": task_id, "error": content})
            return AgentResult(content=content, trace=trace, failed=True)

    def _execute(
        self,
        name: str,
        arguments: dict[str, Any],
        ctx: ToolContext,
    ) -> ToolObservation:
        before_tool(name, arguments, ctx.workspace)
        if name == "use_skill":
            return self._use_skill(arguments)
        if name.startswith("mcp__"):
            if self.mcp is None:
                raise ToolError("MCP 管理器未启用")
            return self.mcp.call(name, arguments)
        return execute_tool(name, arguments, ctx)

    def _system_prompt(self) -> str:
        sections = [SYSTEM_PROMPT]
        agent_instructions = self.agent_instructions.render()
        if agent_instructions:
            sections.append(agent_instructions)
        if self.skills.skills:
            catalog = "\n".join(
                f"- {line}" for line in skill_catalog_lines(self.skills)
            )
            sections.append(
                "可用技能目录（这里只有名称与触发说明；匹配任务时调用 "
                "`use_skill` 获取完整正文）：\n"
                f"{catalog}"
            )
        return "\n\n".join(sections)

    def _use_skill(self, arguments: dict[str, Any]) -> ToolObservation:
        if not self.skills.skills:
            raise ToolError("技能系统未启用，或当前项目没有可用技能。")
        name = arguments.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ToolError("use_skill 需要非空的技能名称 name。")
        normalized_name = name.strip()
        try:
            skill = self.skills.get(normalized_name)
        except KeyError as exc:
            available = ", ".join(item.name for item in self.skills.skills)
            raise ToolError(
                f"未知技能：{normalized_name}。可用技能：{available}"
            ) from exc
        body = skill.document.body.strip()
        content = f"# 技能：{skill.name}\n\n{body}"
        return ToolObservation(
            text=content,
            content=content,
            metadata={
                "skill": skill.name,
                "source": str(skill.document.source or skill.directory),
            },
        )

    def _compact_if_needed(
        self,
        messages: list[dict[str, Any]],
        emit: Any,
    ) -> None:
        before = _message_chars(messages)
        if before <= self.settings.context_char_limit:
            return
        target = max(8_000, int(self.settings.context_char_limit * 0.55))
        tool_indexes = [
            index
            for index, message in enumerate(messages)
            if message.get("role") == "tool"
        ]
        candidates = tool_indexes[:-6]
        shortened = 0
        for index in candidates:
            content = messages[index].get("content")
            if isinstance(content, str) and len(content) > 500:
                messages[index]["content"] = (
                    content[:240]
                    + "\n[... 较早的工具输出已压缩；完整内容保留在 trace ...]"
                    + content[-160:]
                )
                shortened += 1
            if _message_chars(messages) <= target:
                break
        emit(
            "context.compacted",
            {
                "before_chars": before,
                "after_chars": _message_chars(messages),
                "tool_outputs_shortened": shortened,
            },
        )

