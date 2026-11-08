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
from pycursor.custom_report import build_custom_report


ENABLED = {
    "ENABLE_AGENTS": "1",
    "ENABLE_HOOKS": "1",
    "ENABLE_REVIEWER": "1",
}


class CustomReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parent.parent
        cls.test_root = cls.root / ".test-tmp"
        cls.test_root.mkdir(exist_ok=True)

    def setUp(self) -> None:
        self.workspace = self.test_root / f"custom-report-{uuid.uuid4().hex}"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.workspace, ignore_errors=True)

    def test_report_meets_customization_thresholds(self) -> None:
        with patch.dict(os.environ, ENABLED):
            report = build_custom_report(self.root)

        self.assertEqual(report["mode"], "deterministic_probe")
        self.assertTrue(report["agents_md"]["found"])
        self.assertLessEqual(report["agents_md"]["bytes"], 12_000)
        self.assertIn("project", report["agents_md"]["layers"])
        self.assertGreaterEqual(len(report["denied"]), 2)
        self.assertTrue(all(item["reason"] for item in report["denied"]))
        self.assertEqual(report["autotest"]["runs"], 2)
        self.assertEqual(report["autotest"]["red"], 1)
        self.assertEqual(report["autotest"]["green"], 1)
        self.assertGreaterEqual(report["autotest"]["red_to_green"], 1)
        self.assertEqual(report["reviewer"]["runs"], 1)
        self.assertGreaterEqual(report["reviewer"]["issues_found"], 1)
        self.assertLessEqual(report["reviewer"]["main_context_delta"], 500)
        self.assertTrue(report["reviewer"]["isolated_context"])

    def test_cli_writes_custom_report(self) -> None:
        output = self.workspace / "custom_report.json"
        stdout = StringIO()
        with patch.dict(os.environ, ENABLED), redirect_stdout(stdout):
            exit_code = main(
                ["custom", "--root", str(self.root), "--out", str(output)]
            )

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertIn("agents_md", payload)
        self.assertIn("reviewer", payload)
        self.assertIn(str(output), stdout.getvalue())

    def test_disabled_switches_do_not_fabricate_results(self) -> None:
        disabled = {
            "ENABLE_AGENTS": "0",
            "ENABLE_HOOKS": "0",
            "ENABLE_REVIEWER": "0",
        }
        with patch.dict(os.environ, disabled):
            report = build_custom_report(self.root)

        self.assertFalse(report["agents_md"]["found"])
        self.assertEqual(report["agents_md"]["bytes"], 0)
        self.assertEqual(report["denied"], [])
        self.assertEqual(report["autotest"]["runs"], 0)
        self.assertEqual(report["reviewer"]["runs"], 0)


if __name__ == "__main__":
    unittest.main()
