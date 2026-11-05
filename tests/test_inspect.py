from __future__ import annotations

import json
import os
import shutil
import unittest
import uuid
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from app.inspect import main
from pycursor.skill_report import build_skill_report, select_skill
from pycursor.skills import load_skills


class SkillReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parent.parent
        cls.test_root = cls.root / ".test-tmp"
        cls.test_root.mkdir(exist_ok=True)

    def setUp(self) -> None:
        self.workspace = self.test_root / f"inspect-{uuid.uuid4().hex}"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.workspace, ignore_errors=True)

    def test_report_meets_assignment_thresholds(self) -> None:
        registry = load_skills(self.root)
        report = build_skill_report(registry)

        self.assertGreaterEqual(len(report["skills"]), 3)
        forms = {skill["form"] for skill in report["skills"]}
        self.assertEqual(forms, {"prompt", "prompt+script", "prompt+mcp"})
        self.assertGreaterEqual(report["disclosure_ratio"], 5)
        self.assertGreaterEqual(len(report["trials"]), 6)
        self.assertTrue(any(trial["expected"] is None for trial in report["trials"]))
        self.assertEqual(report["false_positive"], 0)
        self.assertTrue(all(trial["ok"] for trial in report["trials"]))

    def test_selector_returns_none_for_chat(self) -> None:
        registry = load_skills(self.root)
        self.assertIsNone(select_skill("今天晚饭吃什么", registry))

    def test_cli_writes_json(self) -> None:
        output = self.workspace / "skill_report.json"
        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = main(
                ["skills", "--root", str(self.root), "--out", str(output)]
            )

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertIn("skills", payload)
        self.assertIn("trials", payload)
        self.assertIn(str(output), stdout.getvalue())

    def test_cli_respects_disabled_switch(self) -> None:
        output = self.workspace / "disabled.json"
        with patch.dict(os.environ, {"ENABLE_SKILLS": "0"}):
            exit_code = main(
                ["skills", "--root", str(self.root), "--out", str(output)]
            )

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["skills"], [])
        self.assertEqual(payload["catalog_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
