from __future__ import annotations

import json
import shutil
import threading
import unittest
import uuid
from pathlib import Path
from typing import Any

from pycursor.llm import ChatReply
from pycursor.reviewer import ReviewerAgent


class ScriptedReviewerClient:
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
        self.message_snapshots.append([dict(message) for message in messages])
        reply = self.replies[self.calls]
        self.calls += 1
        return reply


def tool_reply(name: str, arguments: dict[str, Any]) -> ChatReply:
    return ChatReply(
        content="",
        tool_calls=[
            {
                "id": "review-call",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments),
                },
            }
        ],
        raw_message={"role": "assistant", "content": ""},
        usage={"total_tokens": 10},
    )


def final_reply(content: str) -> ChatReply:
    return ChatReply(
        content=content,
        tool_calls=[],
        raw_message={"role": "assistant", "content": content},
        usage={"total_tokens": 10},
    )


class ReviewerAgentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parent.parent
        cls.test_root = cls.root / ".test-tmp"
        cls.test_root.mkdir(exist_ok=True)

    def setUp(self) -> None:
        self.workspace = self.test_root / f"reviewer-{uuid.uuid4().hex}"
        self.workspace.mkdir()
        (self.workspace / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.workspace, ignore_errors=True)

    def test_reviewer_has_isolated_read_only_context(self) -> None:
        client = ScriptedReviewerClient(
            [
                tool_reply("bash", {"command": "git diff --stat"}),
                final_reply("无阻断问题。"),
            ]
        )
        reviewer = ReviewerAgent(
            client=client,
            workspace=self.workspace,
            cancel_event=threading.Event(),
            command_timeout=10,
        )
        result = reviewer.review()

        self.assertFalse(result.failed)
        self.assertEqual(result.content, "无阻断问题。")
        self.assertEqual(client.tool_names, [["read", "bash"], ["read", "bash"]])
        system_prompt = client.message_snapshots[0][0]["content"]
        self.assertIn("只使用 read 和 bash", system_prompt)
        self.assertIn("except: pass", system_prompt)
        self.assertIn("缺少测试覆盖", system_prompt)

    def test_reviewer_rejects_non_diff_bash_command(self) -> None:
        client = ScriptedReviewerClient(
            [
                tool_reply("bash", {"command": "rm -rf build"}),
                final_reply("已拒绝危险命令。"),
            ]
        )
        reviewer = ReviewerAgent(
            client=client,
            workspace=self.workspace,
            cancel_event=threading.Event(),
            command_timeout=10,
        )
        result = reviewer.review()

        self.assertFalse(result.failed)
        tool_message = client.message_snapshots[1][-1]
        self.assertEqual(tool_message["role"], "tool")
        self.assertIn("只允许执行单条 git diff", tool_message["content"])

    def test_reviewer_rejects_diff_command_with_output(self) -> None:
        client = ScriptedReviewerClient(
            [
                tool_reply("bash", {"command": "git diff --output=leak.patch"}),
                final_reply("拒绝写文件。"),
            ]
        )
        reviewer = ReviewerAgent(
            client=client,
            workspace=self.workspace,
            cancel_event=threading.Event(),
            command_timeout=10,
        )
        result = reviewer.review()

        self.assertFalse(result.failed)
        tool_message = client.message_snapshots[1][-1]
        self.assertIn("只允许执行单条 git diff", tool_message["content"])


if __name__ == "__main__":
    unittest.main()
