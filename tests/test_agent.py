from __future__ import annotations

import json
import os
import shutil
import threading
import unittest
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

from pycursor.agent import AgentRunner
from pycursor.config import Settings
from pycursor.llm import ChatReply


class ScriptedClient:
    def __init__(self, replies: list[ChatReply]) -> None:
        self.replies = replies
        self.calls = 0
        self.tool_names: list[list[str]] = []
        self.message_snapshots: list[list[dict[str, Any]]] = []

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        timeout: int = 120,
    ) -> ChatReply:
        self.tool_names.append(
            [tool.get("function", {}).get("name", "") for tool in tools]
        )
        self.message_snapshots.append(
            [dict(message) for message in messages]
        )
        reply = self.replies[self.calls]
        self.calls += 1
        return reply


def tool_reply(name: str, arguments: dict[str, Any], call_id: str = "call-1") -> ChatReply:
    raw = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                },
            }
        ],
    }
    return ChatReply(
        content="",
        tool_calls=raw["tool_calls"],
        raw_message=raw,
        usage={"total_tokens": 20},
    )


def final_reply(content: str) -> ChatReply:
    return ChatReply(
        content=content,
        tool_calls=[],
        raw_message={"role": "assistant", "content": content},
        usage={"total_tokens": 10},
    )


class AgentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parent.parent
        cls.test_root = cls.root / ".test-tmp"
        cls.test_root.mkdir(exist_ok=True)

    def setUp(self) -> None:
        self.workspace = self.test_root / f"case-{uuid.uuid4().hex}"
        self.workspace.mkdir()
        (self.workspace / "stats.py").write_text("value = 1\n", encoding="utf-8")
        self.settings = Settings(
            api_key="test",
            workspace=str(self.workspace),
            max_steps=4,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.workspace, ignore_errors=True)

    def run_agent(self, client: ScriptedClient, cancel: threading.Event | None = None):
        events: list[dict[str, Any]] = []
        runner = AgentRunner(self.settings, client=client)
        result = runner.run(
            "读取 stats.py 后回答",
            task_id="test-task",
            cancel_event=cancel or threading.Event(),
            emit=lambda kind, data: events.append({"type": kind, **data}),
        )
        return result, events

    def test_tool_loop_returns_final_message(self) -> None:
        client = ScriptedClient(
            [
                tool_reply("read", {"path": "stats.py"}),
                final_reply("文件只有一行：value = 1。"),
            ]
        )
        result, events = self.run_agent(client)
        self.assertFalse(result.failed)
        self.assertIn("value = 1", result.content)
        self.assertIn("tool.started", [event["type"] for event in events])
        self.assertIn("tool.completed", [event["type"] for event in events])
        self.assertEqual(events[-1]["type"], "task.completed")

    def test_tool_error_is_returned_to_model(self) -> None:
        client = ScriptedClient(
            [
                tool_reply("read", {"path": "../../blocked"}),
                final_reply("路径被安全边界拦住了。"),
            ]
        )
        result, events = self.run_agent(client)
        self.assertFalse(result.failed)
        failures = [event for event in events if event["type"] == "tool.failed"]
        self.assertEqual(len(failures), 1)
        self.assertIn("工作区外", failures[0]["error"])

    def test_cancel_before_first_step(self) -> None:
        cancel = threading.Event()
        cancel.set()
        client = ScriptedClient([final_reply("should not be called")])
        result, events = self.run_agent(client, cancel)
        self.assertTrue(result.cancelled)
        self.assertEqual(client.calls, 0)
        self.assertEqual(events[-1]["type"], "task.cancelled")

    def test_step_limit_stops_runaway_agent(self) -> None:
        client = ScriptedClient(
            [
                tool_reply("read", {"path": "stats.py"}, f"call-{index}")
                for index in range(4)
            ]
        )
        result, events = self.run_agent(client)
        self.assertTrue(result.failed)
        self.assertIn("步上限", result.content)
        self.assertEqual(events[-1]["type"], "task.failed")

    def test_use_skill_loads_body_only_on_demand(self) -> None:
        skill_dir = self.workspace / "skills" / "run-tests"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: run-tests\n"
            "description: 跑测试。Use this when 用户说测一下。\n"
            "---\n"
            "## 怎么算做完了\n"
            "- 已报告测试结果\n",
            encoding="utf-8",
        )
        client = ScriptedClient(
            [
                tool_reply("use_skill", {"name": "run-tests"}),
                final_reply("技能说明已加载。"),
            ]
        )
        result, events = self.run_agent(client)

        self.assertFalse(result.failed)
        self.assertIn("use_skill", client.tool_names[0])
        system_prompt = client.message_snapshots[0][0]["content"]
        self.assertIn("run-tests:", system_prompt)
        self.assertNotIn("## 怎么算做完了", system_prompt)
        completed = [
            event for event in events if event["type"] == "tool.completed"
        ]
        self.assertEqual(completed[0]["metadata"]["skill"], "run-tests")
        self.assertIn("## 怎么算做完了", completed[0]["content"])

    def test_use_skill_unknown_name_returns_readable_error(self) -> None:
        skill_dir = self.workspace / "skills" / "run-tests"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: run-tests\n"
            "description: 跑测试。Use this when 用户说测一下。\n"
            "---\n"
            "## 怎么算做完了\n"
            "- 已报告测试结果\n",
            encoding="utf-8",
        )
        client = ScriptedClient(
            [
                tool_reply("use_skill", {"name": "../secrets"}),
                final_reply("未找到技能。"),
            ]
        )
        result, events = self.run_agent(client)

        self.assertFalse(result.failed)
        failures = [event for event in events if event["type"] == "tool.failed"]
        self.assertEqual(len(failures), 1)
        self.assertIn("未知技能", failures[0]["error"])
        self.assertIn("run-tests", failures[0]["error"])

    def test_disabled_skills_do_not_register_use_skill(self) -> None:
        skill_dir = self.workspace / "skills" / "run-tests"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: run-tests\n"
            "description: 跑测试。Use this when 用户说测一下。\n"
            "---\n"
            "## 怎么算做完了\n"
            "- 已报告测试结果\n",
            encoding="utf-8",
        )
        client = ScriptedClient([final_reply("旧版工具集。")])
        with patch.dict(
            os.environ,
            {"ENABLE_SKILLS": "0", "ENABLE_REVIEWER": "0"},
        ):
            result, _ = self.run_agent(client)

        self.assertFalse(result.failed)
        self.assertEqual(
            client.tool_names[0],
            ["read", "write", "edit", "bash"],
        )
        self.assertNotIn("可用技能目录", client.message_snapshots[0][0]["content"])

    def test_project_agents_file_is_injected(self) -> None:
        (self.workspace / "AGENTS.md").write_text(
            "# 项目地图\n只允许使用标准库。\n",
            encoding="utf-8",
        )
        client = ScriptedClient([final_reply("已读取规则。")])
        result, _ = self.run_agent(client)

        self.assertFalse(result.failed)
        system_prompt = client.message_snapshots[0][0]["content"]
        self.assertIn("## 项目 AGENTS.md", system_prompt)
        self.assertIn("只允许使用标准库", system_prompt)

    def test_pretool_hook_blocks_env_write(self) -> None:
        client = ScriptedClient(
            [
                tool_reply(
                    "write",
                    {"path": ".env", "content": "DEEPSEEK_API_KEY=secret"},
                ),
                final_reply("密钥文件写入被拦截。"),
            ]
        )
        result, events = self.run_agent(client)

        self.assertFalse(result.failed)
        self.assertFalse((self.workspace / ".env").exists())
        failures = [event for event in events if event["type"] == "tool.failed"]
        self.assertEqual(len(failures), 1)
        self.assertIn("PreToolUse Hook 拒绝", failures[0]["error"])
        self.assertIn(".env.example", failures[0]["error"])

    def test_disabled_hooks_allow_env_write(self) -> None:
        client = ScriptedClient(
            [
                tool_reply(
                    "write",
                    {"path": ".env", "content": "ONLY_FOR_TEST=1\n"},
                ),
                final_reply("写入完成。"),
            ]
        )
        with patch.dict(os.environ, {"ENABLE_HOOKS": "0"}):
            result, _ = self.run_agent(client)

        self.assertFalse(result.failed)
        self.assertEqual(
            (self.workspace / ".env").read_text(encoding="utf-8"),
            "ONLY_FOR_TEST=1\n",
        )

    def test_pretool_hook_blocks_destructive_bash_command(self) -> None:
        client = ScriptedClient(
            [
                tool_reply("bash", {"command": "rm -rf build"}),
                final_reply("危险命令已拦截。"),
            ]
        )
        result, events = self.run_agent(client)

        self.assertFalse(result.failed)
        failures = [event for event in events if event["type"] == "tool.failed"]
        self.assertEqual(len(failures), 1)
        self.assertIn("PreToolUse Hook 拒绝", failures[0]["error"])
        self.assertIn("git restore", failures[0]["error"])

    def test_post_tool_test_summary_is_injected(self) -> None:
        client = ScriptedClient(
            [
                tool_reply(
                    "write",
                    {"path": "stats.py", "content": "value = 2\n"},
                ),
                final_reply("代码已修改，并读取了测试摘要。"),
            ]
        )
        result, events = self.run_agent(client)

        self.assertFalse(result.failed)
        self.assertIn("hook.post_tool", [event["type"] for event in events])
        follow_up_messages = client.message_snapshots[1]
        self.assertEqual(follow_up_messages[-1]["role"], "user")
        self.assertIn(
            "[PostToolUse 自动测试]",
            follow_up_messages[-1]["content"],
        )
        self.assertIn("Ran 0 tests", follow_up_messages[-1]["content"])

    def test_review_diff_returns_only_final_reviewer_message(self) -> None:
        client = ScriptedClient(
            [
                tool_reply("review_diff", {}),
                tool_reply("bash", {"command": "git diff --stat"}, "review-bash"),
                final_reply("审查结论：无阻断问题。"),
                final_reply("reviewer 已返回最终判定。"),
            ]
        )
        result, events = self.run_agent(client)

        self.assertFalse(result.failed)
        self.assertIn("review_diff", client.tool_names[0])
        self.assertEqual(client.tool_names[1], ["read", "bash"])
        self.assertNotIn(
            "bash",
            [event["name"] for event in events if event["type"] == "tool.started"],
        )
        completed = [
            event for event in events if event["type"] == "tool.completed"
        ]
        self.assertEqual(completed[0]["name"], "review_diff")
        self.assertEqual(completed[0]["content"], "审查结论：无阻断问题。")
        self.assertTrue(completed[0]["metadata"]["isolated_context"])

    def test_disabled_reviewer_is_not_registered(self) -> None:
        client = ScriptedClient([final_reply("reviewer 已关闭。")])
        with patch.dict(os.environ, {"ENABLE_REVIEWER": "0"}):
            result, _ = self.run_agent(client)

        self.assertFalse(result.failed)
        self.assertNotIn("review_diff", client.tool_names[0])


if __name__ == "__main__":
    unittest.main()

