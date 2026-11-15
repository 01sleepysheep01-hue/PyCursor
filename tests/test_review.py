from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from app.review import evaluate_dataset, main, parse_added_lines, review_diff_text


class DiffReviewTest(unittest.TestCase):
    def test_parser_tracks_new_file_line_numbers(self) -> None:
        diff = (
            "diff --git a/app/x.py b/app/x.py\n"
            "--- a/app/x.py\n"
            "+++ b/app/x.py\n"
            "@@ -3,2 +3,3 @@\n"
            " context\n"
            "+added one\n"
            "+added two\n"
        )
        lines = parse_added_lines(diff)
        self.assertEqual([(line.path, line.line) for line in lines], [
            ("app/x.py", 4),
            ("app/x.py", 5),
        ])

    def test_critical_finding_requests_changes(self) -> None:
        diff = (
            "diff --git a/app/x.py b/app/x.py\n"
            "--- a/app/x.py\n"
            "+++ b/app/x.py\n"
            "@@ -1,1 +1,2 @@\n"
            " def run(value):\n"
            "+    return eval(value)\n"
        )
        outcome = review_diff_text(diff)
        self.assertEqual(outcome.decision, "request_changes")
        self.assertEqual(outcome.findings[0].rule_id, "security.dynamic-code-execution")

    def test_clean_diff_is_approved(self) -> None:
        diff = (
            "diff --git a/app/x.py b/app/x.py\n"
            "--- a/app/x.py\n"
            "+++ b/app/x.py\n"
            "@@ -1,1 +1,2 @@\n"
            " import ast\n"
            "+value = ast.literal_eval(user_input)\n"
        )
        outcome = review_diff_text(diff)
        self.assertEqual(outcome.decision, "approved")
        self.assertEqual(outcome.findings, ())


class ReviewDatasetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parent.parent
        cls.test_root = cls.root / ".test-tmp"
        cls.test_root.mkdir(exist_ok=True)

    def setUp(self) -> None:
        self.output_dir = self.test_root / f"review-{uuid.uuid4().hex}"
        self.output_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def test_dataset_meets_assignment_thresholds(self) -> None:
        report = evaluate_dataset(self.root / "review_dataset")

        self.assertGreaterEqual(report["known_bug_count"], 8)
        self.assertGreaterEqual(report["recall"], 0.6)
        self.assertLessEqual(report["false_positive_count"], 3)
        self.assertTrue(report["pass"])
        self.assertIn("summary_comment", report)

    def test_cli_writes_report_and_single_comment(self) -> None:
        output = self.output_dir / "review_report.json"
        comment = self.output_dir / "review_comment.md"
        exit_code = main(
            [
                "--dataset",
                str(self.root / "review_dataset"),
                "--out",
                str(output),
                "--comment-out",
                str(comment),
            ]
        )

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(payload["pass"])
        self.assertTrue(comment.read_text(encoding="utf-8").startswith("## CodeProof review"))

    def test_cli_reviews_one_diff_file(self) -> None:
        diff_file = self.output_dir / "change.diff"
        diff_file.write_text(
            "diff --git a/app/x.py b/app/x.py\n"
            "--- a/app/x.py\n"
            "+++ b/app/x.py\n"
            "@@ -1,1 +1,2 @@\n"
            " def run(value):\n"
            "+    return eval(value)\n",
            encoding="utf-8",
        )
        output = self.output_dir / "single.json"
        comment = self.output_dir / "single.md"
        exit_code = main(
            [
                "--diff-file",
                str(diff_file),
                "--out",
                str(output),
                "--comment-out",
                str(comment),
            ]
        )

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["decision"], "request_changes")
        self.assertIn("critical", comment.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
