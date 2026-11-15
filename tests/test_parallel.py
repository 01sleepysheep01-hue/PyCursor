from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from app.parallel import DEFAULT_TASKS
from scripts.parallel_worker import apply_task


class ParallelTaskTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parent.parent
        cls.test_root = cls.root / ".test-tmp"
        cls.test_root.mkdir(exist_ok=True)

    def setUp(self) -> None:
        self.workspace = self.test_root / f"parallel-{uuid.uuid4().hex}"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.workspace, ignore_errors=True)

    def test_default_tasks_have_disjoint_scopes(self) -> None:
        self.assertEqual(len(DEFAULT_TASKS), 2)
        first = set(DEFAULT_TASKS[0].scope)
        second = set(DEFAULT_TASKS[1].scope)
        self.assertFalse(first & second)

    def test_findings_contract_worker_writes_expected_files(self) -> None:
        apply_task(self.workspace, "findings-contract")

        self.assertTrue((self.workspace / "pycursor/review_findings.py").is_file())
        self.assertTrue((self.workspace / "tests/test_review_findings.py").is_file())

    def test_review_docs_worker_writes_expected_files(self) -> None:
        apply_task(self.workspace, "review-docs")

        self.assertTrue((self.workspace / "docs/review-workflow.md").is_file())
        self.assertTrue((self.workspace / "review_dataset/README.md").is_file())

    def test_unknown_worker_task_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            apply_task(self.workspace, "unknown")


if __name__ == "__main__":
    unittest.main()
