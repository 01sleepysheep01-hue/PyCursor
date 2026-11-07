from __future__ import annotations

import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from pycursor.hooks import after_tool, before_tool, hooks_enabled
from pycursor.tools import ToolError


class PreToolUseHookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parent.parent
        cls.test_root = cls.root / ".test-tmp"
        cls.test_root.mkdir(exist_ok=True)

    def setUp(self) -> None:
        self.workspace = self.test_root / f"hooks-{uuid.uuid4().hex}"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.workspace, ignore_errors=True)

    def test_blocks_env_writes_with_safe_alternative(self) -> None:
        for name in (".env", ".env.local", "config/.env.production"):
            with self.subTest(name=name), self.assertRaises(ToolError) as caught:
                before_tool(
                    "write",
                    {"path": name, "content": "secret"},
                    self.workspace,
                )
            message = str(caught.exception)
            self.assertIn("PreToolUse Hook 拒绝", message)
            self.assertIn(".env.example", message)
            self.assertIn("环境变量", message)

    def test_blocks_private_key_files_case_insensitively(self) -> None:
        for name in ("server.pem", "TLS.KEY", "certs/private.PeM"):
            with self.subTest(name=name), self.assertRaises(ToolError):
                before_tool(
                    "edit",
                    {"path": name, "old_text": "a", "new_text": "b"},
                    self.workspace,
                )

    def test_allows_env_example_and_normal_files(self) -> None:
        before_tool(
            "write",
            {"path": ".env.example", "content": "API_KEY=placeholder"},
            self.workspace,
        )
        before_tool(
            "write",
            {"path": "src/config.py", "content": "VALUE = 1"},
            self.workspace,
        )

    def test_disabled_switch_allows_write(self) -> None:
        with patch.dict(os.environ, {"ENABLE_HOOKS": "0"}):
            self.assertFalse(hooks_enabled())
            before_tool(
                "write",
                {"path": ".env", "content": "local only"},
                self.workspace,
            )

    def test_blocks_recursive_force_delete(self) -> None:
        commands = (
            "rm -rf build",
            "rm -fr build",
            "rm -r -f build",
            "rm --recursive --force build",
            "cd project && sudo rm -Rf build",
        )
        for command in commands:
            with self.subTest(command=command), self.assertRaises(ToolError) as caught:
                before_tool("bash", {"command": command}, self.workspace)
            self.assertIn("git restore", str(caught.exception))

    def test_blocks_dangerous_git_commands_with_alternatives(self) -> None:
        commands = (
            "git push --force",
            "git push -f origin main",
            "git push --force-with-lease",
            "git reset --hard HEAD~1",
        )
        for command in commands:
            with self.subTest(command=command), self.assertRaises(ToolError):
                before_tool("bash", {"command": command}, self.workspace)

    def test_allows_non_destructive_commands(self) -> None:
        commands = (
            "rm build/output.txt",
            "git push origin main",
            "git reset --soft HEAD~1",
            "git status --short",
            'echo "rm -rf is documentation text"',
        )
        for command in commands:
            with self.subTest(command=command):
                before_tool("bash", {"command": command}, self.workspace)

    def test_other_tools_are_not_intercepted(self) -> None:
        before_tool("read", {"path": ".env"}, self.workspace)

    def test_post_tool_summarizes_failing_test_without_traceback(self) -> None:
        target = self.workspace / "test_sample.py"
        target.write_text(
            "import unittest\n"
            "class SampleTest(unittest.TestCase):\n"
            "    def test_value(self):\n"
            "        self.assertEqual(1, 2)\n",
            encoding="utf-8",
        )
        result = after_tool(
            "edit",
            {"path": "test_sample.py", "old": "1", "new": "2"},
            self.workspace,
            timeout=20,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("test_value", result.summary)
        self.assertIn("1 != 2", result.summary)
        self.assertNotIn("Traceback (most recent call last)", result.summary)

    def test_post_tool_summarizes_passing_test(self) -> None:
        target = self.workspace / "test_sample.py"
        target.write_text(
            "import unittest\n"
            "class SampleTest(unittest.TestCase):\n"
            "    def test_value(self):\n"
            "        self.assertEqual(1, 1)\n",
            encoding="utf-8",
        )
        result = after_tool(
            "write",
            {"path": "test_sample.py", "content": target.read_text(encoding="utf-8")},
            self.workspace,
            timeout=20,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Ran 1 test", result.summary)
        self.assertIn("OK", result.summary)

    def test_post_tool_ignores_non_code_and_disabled_hook(self) -> None:
        self.assertIsNone(
            after_tool(
                "write",
                {"path": "README.md", "content": "docs"},
                self.workspace,
            )
        )
        with patch.dict(os.environ, {"ENABLE_HOOKS": "0"}):
            self.assertIsNone(
                after_tool(
                    "write",
                    {"path": "main.py", "content": "VALUE = 1\n"},
                    self.workspace,
                )
            )


if __name__ == "__main__":
    unittest.main()
