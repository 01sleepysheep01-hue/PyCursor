"""Replay a deterministic four-tool task and write an auditable trace.

This script uses a scripted model so the architecture and tools can be verified
without an API key. The actual tools execute against a temporary copy of the
demo workspace.
"""

from __future__ import annotations

import json
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pycursor.agent import AgentRunner  # noqa: E402
from pycursor.config import Settings  # noqa: E402
from pycursor.llm import ChatReply  # noqa: E402


class ScriptedClient:
    def __init__(self, replies: list[ChatReply]) -> None:
        self.replies = replies
        self.index = 0

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        timeout: int = 120,
    ) -> ChatReply:
        reply = self.replies[self.index]
        self.index += 1
        return reply


def call(name: str, arguments: dict[str, Any], number: int) -> ChatReply:
    tool_call = {
        "id": f"demo-{number}",
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments, ensure_ascii=False),
        },
    }
    return ChatReply(
        content="",
        tool_calls=[tool_call],
        raw_message={
            "role": "assistant",
            "content": None,
            "tool_calls": [tool_call],
        },
        usage={},
    )


def final(content: str) -> ChatReply:
    return ChatReply(
        content=content,
        tool_calls=[],
        raw_message={"role": "assistant", "content": content},
        usage={},
    )


def main() -> int:
    run_name = f"replay-{uuid.uuid4().hex[:8]}"
    run_dir = ROOT / ".demo-run" / run_name
    run_dir.mkdir(parents=True)
    try:
        for name in ("stats.py", "test_stats.py"):
            shutil.copy2(ROOT / "examples" / "workspace" / name, run_dir / name)

        executable = sys.executable
        test_command = f'"{executable}" -m unittest -v'
        client = ScriptedClient(
            [
                call("bash", {"command": test_command, "timeout": 20}, 1),
                call("read", {"path": "stats.py"}, 2),
                call(
                    "edit",
                    {
                        "path": "stats.py",
                        "old": "    if not nums:\n        return 0",
                        "new": (
                            "    if not nums:\n"
                            '        raise ValueError("mean() requires at least one value")'
                        ),
                    },
                    3,
                ),
                call("bash", {"command": test_command, "timeout": 20}, 4),
                final(
                    "已复现空列表测试失败，并只修改 mean 的空输入分支。"
                    "最终 5 个测试全部通过。"
                ),
            ]
        )
        settings = Settings(
            api_key="scripted-demo",
            workspace=str(run_dir),
            max_steps=6,
        )
        events: list[dict[str, Any]] = []

        def emit(kind: str, payload: dict[str, Any]) -> None:
            event = {"time": time.strftime("%H:%M:%S"), "type": kind, **payload}
            events.append(event)
            summary = ""
            if kind == "tool.started":
                summary = f" {payload.get('name')} {payload.get('arguments')}"
            elif kind in {"task.completed", "task.failed", "task.cancelled"}:
                summary = f" {payload.get('content') or payload.get('error')}"
            print(f"[{event['time']}] {kind}{summary}", flush=True)

        result = AgentRunner(settings, client=client).run(
            "mean 对空列表处理有问题，先复现，再最小修改并验证。",
            task_id=run_name,
            cancel_event=threading.Event(),
            emit=emit,
        )
        if result.failed or result.cancelled:
            print(result.content, file=sys.stderr)
            return 1

        lines = [
            "# PyCursor 真实工具 trace",
            "",
            "由 `scripts/replay_demo.py` 生成。模型回复是脚本化的，但 read、edit、bash "
            "和测试输出均为真实执行结果。",
            "",
        ]
        for event in events:
            kind = event["type"]
            if kind == "tool.started":
                lines.extend(
                    [
                        f"## {event['time']} · {event['name']} · 开始",
                        "",
                        "```json",
                        json.dumps(event.get("arguments"), ensure_ascii=False, indent=2),
                        "```",
                        "",
                    ]
                )
            elif kind == "tool.completed":
                lines.extend(
                    [
                        f"## {event['time']} · {event['name']} · 完成",
                        "",
                        "```text",
                        str(event.get("content", ""))[:12_000],
                        "```",
                        "",
                    ]
                )
                diff = (event.get("metadata") or {}).get("diff")
                if diff:
                    lines.extend(["```diff", diff, "```", ""])
            elif kind == "tool.failed":
                lines.extend(
                    [
                        f"## {event['time']} · {event['name']} · 失败",
                        "",
                        "```text",
                        str(event.get("error", "")),
                        "```",
                        "",
                    ]
                )
            elif kind in {"task.completed", "task.failed", "task.cancelled"}:
                lines.extend(
                    [
                        f"## {event['time']} · {kind}",
                        "",
                        str(event.get("content") or event.get("error") or ""),
                        "",
                    ]
                )

        trace_path = ROOT / "docs" / "trace.md"
        trace_path.parent.mkdir(exist_ok=True)
        trace_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"Trace written to {trace_path}")
        return 0
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

