from __future__ import annotations

import base64
import shutil
import threading
import time
import unittest
import uuid
from pathlib import Path

from pycursor.tools import ToolContext, ToolError, bash, edit, read, write


class ToolsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parent.parent
        cls.test_root = cls.root / ".test-tmp"
        cls.test_root.mkdir(exist_ok=True)

    def setUp(self) -> None:
        self.workspace = (self.test_root / f"case-{uuid.uuid4().hex}").resolve()
        self.workspace.mkdir()
        self.ctx = ToolContext(
            workspace=self.workspace,
            cancel_event=threading.Event(),
            command_timeout=5,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.workspace, ignore_errors=True)

    def test_read_has_line_numbers_and_pagination(self) -> None:
        (self.workspace / "sample.txt").write_text("a\nb\nc\n", encoding="utf-8")
        observation = read(self.ctx, "sample.txt", offset=2, limit=1)
        self.assertIn("2 | b", observation.text)
        self.assertIn("还有 1 行", observation.text)
        self.assertEqual(observation.metadata["remaining"], 1)

    def test_path_traversal_is_rejected(self) -> None:
        with self.assertRaisesRegex(ToolError, "工作区外"):
            read(self.ctx, "../../secret.txt")

    def test_write_creates_parents_and_reports_line_counts(self) -> None:
        first = write(self.ctx, "src/example.py", "one\ntwo\n")
        self.assertTrue((self.workspace / "src" / "example.py").exists())
        self.assertIn("0 行 → 2 行", first.text)
        second = write(self.ctx, "src/example.py", "three\n")
        self.assertIn("2 行 → 1 行", second.text)

    def test_edit_requires_unique_match(self) -> None:
        path = self.workspace / "stats.py"
        path.write_text("return 0\nreturn 0\n", encoding="utf-8")
        with self.assertRaisesRegex(ToolError, "出现 2 次"):
            edit(self.ctx, "stats.py", "return 0", "raise ValueError")
        path.write_text("if empty:\n    return 0\n", encoding="utf-8")
        observation = edit(
            self.ctx,
            "stats.py",
            "if empty:\n    return 0",
            "if empty:\n    raise ValueError",
        )
        self.assertIn("精确替换 1 处", observation.text)
        self.assertIn("+    raise ValueError", observation.metadata["diff"])

    def test_bash_returns_nonzero_as_observation(self) -> None:
        observation = bash(self.ctx, "python -c \"import sys; print('bad'); sys.exit(3)\"")
        self.assertIn("exit_code: 3", observation.text)
        self.assertIn("bad", observation.metadata["stdout"])

    def test_bash_timeout_terminates_process(self) -> None:
        started = time.monotonic()
        with self.assertRaisesRegex(ToolError, "已终止"):
            bash(
                self.ctx,
                "python -c \"import time; time.sleep(5)\"",
                timeout=1,
            )
        self.assertLess(time.monotonic() - started, 4)

    def test_bash_output_is_capped(self) -> None:
        observation = bash(
            self.ctx,
            "python -c \"print('x' * 50000)\"",
        )
        self.assertLessEqual(len(observation.metadata["stdout"]), 30_000)

    def test_image_is_returned_as_multimodal_block(self) -> None:
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
            "YAAAAAYAAjCB0C8AAAAASUVORK5CYII="
        )
        (self.workspace / "pixel.png").write_bytes(png)
        observation = read(self.ctx, "pixel.png")
        self.assertIsInstance(observation.content, list)
        self.assertEqual(observation.content[1]["type"], "image_url")
        self.assertIn("data:image/png;base64,", observation.content[1]["image_url"]["url"])


if __name__ == "__main__":
    unittest.main()

