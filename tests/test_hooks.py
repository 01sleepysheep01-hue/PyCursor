from __future__ import annotations

import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from pycursor.hooks import before_tool, hooks_enabled
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

    def test_other_tools_are_not_intercepted(self) -> None:
        before_tool("read", {"path": ".env"}, self.workspace)


if __name__ == "__main__":
    unittest.main()
