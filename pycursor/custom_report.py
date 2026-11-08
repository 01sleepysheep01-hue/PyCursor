from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any

from .agents import agents_enabled, load_agent_instructions
from .hooks import after_tool, before_tool, hooks_enabled
from .llm import ChatReply
from .reviewer import ReviewerAgent, reviewer_enabled
from .tools import ToolError


class CustomReportError(RuntimeError):
    """A customization probe did not exercise the expected safety path."""


class _ReviewerProbeClient:
    """Scripted model that proves the reviewer context boundary without an API key."""

    def __init__(self) -> None:
        self.calls = 0
        self.tool_names: list[list[str]] = []
        self.tokens = 0

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        timeout: int = 120,
    ) -> ChatReply:
        self.calls += 1
        self.tool_names.append(
            [tool.get("function", {}).get("name", "") for tool in tools]
        )
        if self.calls == 1:
            self.tokens += 12
            return ChatReply(
                content="",
                tool_calls=[
                    {
                        "id": "custom-report-review-read",
                        "type": "function",
                        "function": {
                            "name": "read",
                            "arguments": json.dumps({"path": "sample.py"}),
                        },
                    }
                ],
                raw_message={"role": "assistant", "content": ""},
                usage={"total_tokens": 12},
            )

        self.tokens += 24
        content = "发现 1 个问题：新增分支缺少空列表测试，建议补充边界用例。"
        return ChatReply(
            content=content,
            tool_calls=[],
            raw_message={"role": "assistant", "content": content},
            usage={"total_tokens": 24},
        )


def _agents_probe(project_root: Path) -> dict[str, Any]:
    bundle = load_agent_instructions(project_root)
    layers: list[str] = []
    total_bytes = 0
    for item in bundle.files:
        layer = "global" if item.scope == "全局" else "project"
        if layer not in layers:
            layers.append(layer)
        total_bytes += item.source.stat().st_size
    return {
        "found": bool(bundle.files),
        "bytes": total_bytes,
        "layers": layers,
        "files": len(bundle.files),
    }


def _denied_probe(project_root: Path, *, enabled: bool) -> list[dict[str, str]]:
    if not enabled:
        return []

    probes = (
        ("write", {"path": ".env", "content": "TOKEN=should-not-exist"}),
        ("bash", {"command": "rm -rf build/"}),
    )
    denied: list[dict[str, str]] = []
    for tool, arguments in probes:
        try:
            before_tool(tool, arguments, project_root)
        except ToolError as exc:
            item = {"tool": tool, "reason": str(exc)}
            target = arguments.get("path") or arguments.get("command")
            if tool == "write":
                item["path"] = str(target)
            else:
                item["command"] = str(target)
            denied.append(item)
        else:
            raise CustomReportError(
                f"PreToolUse 探针没有被拒绝：{tool} {arguments!r}"
            )
    return denied


def _autotest_probe(project_root: Path, *, enabled: bool) -> dict[str, int]:
    if not enabled:
        return {
            "runs": 0,
            "red": 0,
            "green": 0,
            "red_to_green": 0,
            "injected_lines": 0,
        }

    results = []
    probe_root = project_root / ".test-tmp"
    probe_root.mkdir(parents=True, exist_ok=True)
    workspace = probe_root / f"pycursor-report-hook-{uuid.uuid4().hex}"
    workspace.mkdir()
    try:
        (workspace / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
        (workspace / "test_sample.py").write_text(
            "import unittest\n"
            "import sample\n\n"
            "class SampleTest(unittest.TestCase):\n"
            "    def test_value(self):\n"
            "        self.assertEqual(sample.VALUE, 2)\n",
            encoding="utf-8",
        )

        red_result = after_tool(
            "write",
            {"path": "sample.py", "content": "VALUE = 1\n"},
            workspace,
            timeout=30,
        )
        if red_result is None:
            raise CustomReportError("PostToolUse 红灯探针没有返回测试摘要")
        results.append(red_result)

        # Change the byte length as well as the value so Windows cannot reuse a
        # same-second, same-size .pyc from the deliberately red test run.
        (workspace / "sample.py").write_text("VALUE = 2  # fixed\n", encoding="utf-8")
        green_result = after_tool(
            "edit",
            {"path": "sample.py", "old": "VALUE = 1", "new": "VALUE = 2"},
            workspace,
            timeout=30,
        )
        if green_result is None:
            raise CustomReportError("PostToolUse 绿灯探针没有返回测试摘要")
        results.append(green_result)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    red = sum(result.exit_code != 0 for result in results)
    green = sum(result.exit_code == 0 for result in results)
    red_to_green = int(results[0].exit_code != 0 and results[-1].exit_code == 0)
    return {
        "runs": len(results),
        "red": red,
        "green": green,
        "red_to_green": red_to_green,
        "injected_lines": sum(
            len([line for line in result.summary.splitlines() if line.strip()])
            for result in results
        ),
    }


def _reviewer_probe(project_root: Path, *, enabled: bool) -> dict[str, int | bool]:
    if not enabled:
        return {
            "runs": 0,
            "issues_found": 0,
            "main_context_delta": 0,
            "subagent_tokens": 0,
            "isolated_context": False,
            "failed": False,
        }

    probe_root = project_root / ".test-tmp"
    probe_root.mkdir(parents=True, exist_ok=True)
    workspace = probe_root / f"pycursor-report-reviewer-{uuid.uuid4().hex}"
    workspace.mkdir()
    try:
        (workspace / "sample.py").write_text(
            "def ratio(total, count):\n"
            "    return total / count\n",
            encoding="utf-8",
        )
        client = _ReviewerProbeClient()
        reviewer = ReviewerAgent(
            client=client,
            workspace=workspace,
            cancel_event=threading.Event(),
            command_timeout=10,
            max_steps=2,
        )
        result = reviewer.review()
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    match = re.search(r"发现\s+(\d+)\s+个问题", result.content)
    isolated = bool(client.tool_names) and all(
        set(names) == {"read", "bash"} for names in client.tool_names
    )
    return {
        "runs": 0 if result.failed else 1,
        "issues_found": int(match.group(1)) if match else 0,
        "main_context_delta": len(result.content),
        "subagent_tokens": client.tokens,
        "isolated_context": isolated,
        "failed": result.failed,
    }


def build_custom_report(project_root: Path | str) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"项目根目录不存在：{root}")

    agent_switch = agents_enabled()
    hook_switch = hooks_enabled()
    review_switch = reviewer_enabled()
    return {
        "mode": "deterministic_probe",
        "description": (
            "所有数字均由本地代码路径实际运行生成；reviewer 使用脚本化模型，"
            "不调用外部 API，也不消耗 API Key。"
        ),
        "switches": {
            "ENABLE_AGENTS": agent_switch,
            "ENABLE_HOOKS": hook_switch,
            "ENABLE_REVIEWER": review_switch,
        },
        "agents_md": _agents_probe(root),
        "denied": _denied_probe(root, enabled=hook_switch),
        "autotest": _autotest_probe(root, enabled=hook_switch),
        "reviewer": _reviewer_probe(root, enabled=review_switch),
    }
