from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from app.readiness import CommandResult, build_readiness_report, main


class ReadinessReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parent.parent
        cls.test_root = cls.root / ".test-tmp"
        cls.test_root.mkdir(exist_ok=True)

    def setUp(self) -> None:
        self.output_dir = self.test_root / f"readiness-{uuid.uuid4().hex}"
        self.output_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.output_dir, ignore_errors=True)

    @staticmethod
    def _successful_runner(
        command: list[str] | tuple[str, ...],
        _cwd: Path,
        _timeout: int,
    ) -> CommandResult:
        return CommandResult(
            command=" ".join(command),
            returncode=0,
            duration_ms=25,
            output_tail="OK",
        )

    def test_report_has_nine_pillars_and_reaches_l3(self) -> None:
        report = build_readiness_report(
            self.root,
            runner=self._successful_runner,
        )

        self.assertEqual(len(report["pillars"]), 9)
        self.assertEqual(report["level"], "L3")
        self.assertTrue(report["level_pass"])
        self.assertTrue(report["one_command_check"]["passed"])
        self.assertEqual(len(report["top_gaps"]), 3)

    def test_cli_writes_program_generated_json(self) -> None:
        output = self.output_dir / "readiness_report.json"
        payload = {
            "schema_version": 1,
            "level": "L3",
            "level_pass": True,
            "overall_score": 80.0,
        }
        with patch("app.readiness.build_readiness_report", return_value=payload):
            exit_code = main(
                [
                    "--root",
                    str(self.root),
                    "--out",
                    str(output),
                    "--timeout",
                    "120",
                ]
            )

        self.assertEqual(exit_code, 0)
        written = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(written["schema_version"], 1)
        self.assertEqual(written["level"], "L3")


if __name__ == "__main__":
    unittest.main()
