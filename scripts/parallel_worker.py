from __future__ import annotations

import argparse
from pathlib import Path


FINDINGS_MODULE = '''from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


REVIEW_CATEGORIES = frozenset({"correctness", "security", "performance", "quality"})
REVIEW_SEVERITIES = frozenset({"suggestion", "warning", "critical"})


def _normalize(value: str) -> str:
    return re.sub(r"\\s+", " ", value).strip()


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    path: str
    line: int
    category: str
    severity: str
    message: str
    rule_id: str

    def __post_init__(self) -> None:
        if not self.path.strip():
            raise ValueError("finding path cannot be empty")
        if self.line < 1:
            raise ValueError("finding line must be positive")
        if self.category not in REVIEW_CATEGORIES:
            raise ValueError(f"unknown review category: {self.category}")
        if self.severity not in REVIEW_SEVERITIES:
            raise ValueError(f"unknown review severity: {self.severity}")
        if not self.rule_id.strip():
            raise ValueError("rule_id cannot be empty")

    @property
    def finding_id(self) -> str:
        payload = ":".join(
            (
                self.path.replace("\\\\", "/"),
                str(self.line),
                self.category,
                self.severity,
                self.rule_id,
                _normalize(self.message),
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, str | int]:
        return {
            "finding_id": self.finding_id,
            "path": self.path,
            "line": self.line,
            "category": self.category,
            "severity": self.severity,
            "rule_id": self.rule_id,
            "message": self.message,
        }
'''


FINDINGS_TEST = '''from __future__ import annotations

import unittest

from codeproof.review_findings import ReviewFinding


class ReviewFindingTest(unittest.TestCase):
    def test_finding_id_is_stable_for_normalized_message(self) -> None:
        first = ReviewFinding(
            path="app/review.py",
            line=12,
            category="security",
            severity="critical",
            message="Hardcoded  credential",
            rule_id="security.hardcoded-secret",
        )
        second = ReviewFinding(
            path="app/review.py",
            line=12,
            category="security",
            severity="critical",
            message="Hardcoded credential",
            rule_id="security.hardcoded-secret",
        )
        self.assertEqual(first.finding_id, second.finding_id)
        self.assertEqual(len(first.finding_id), 16)

    def test_finding_id_changes_with_location(self) -> None:
        common = dict(
            category="quality",
            severity="warning",
            message="Debug output remains",
            rule_id="quality.debug-print",
        )
        first = ReviewFinding(path="a.py", line=3, **common)
        second = ReviewFinding(path="a.py", line=4, **common)
        self.assertNotEqual(first.finding_id, second.finding_id)

    def test_invalid_severity_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ReviewFinding(
                path="a.py",
                line=1,
                category="quality",
                severity="blocker",
                message="bad input",
                rule_id="quality.demo",
            )


if __name__ == "__main__":
    unittest.main()
'''


REVIEW_WORKFLOW = '''# 代码评审工作流

评审入口使用固定风险档位，不输出自由发挥的评分：

- `approved`：没有发现阻断问题，可以合并。
- `with_comments`：只有建议或一般警告，可以合并但应跟进。
- `request_changes`：至少存在一条 critical 发现，阻止合并。

所有发现使用稳定 `finding_id`，同一份 diff 重复运行时应得到相同顺序和相同编号。
评审结果先写盘，再生成一条 Markdown 汇总评论，避免把四份重复意见直接推给人。
'''


DATASET_README = '''# Review 数据集

每个 case 同时包含待评审 diff、已知 bug 清单和是否为干净对照的标记。评测器只根据
`known_bugs` 与评审器实际输出计算召回率和误报，不使用人工口头判断。
'''


def write_findings_contract(workspace: Path) -> None:
    module = workspace / "codeproof" / "review_findings.py"
    test = workspace / "tests" / "test_review_findings.py"
    module.parent.mkdir(parents=True, exist_ok=True)
    test.parent.mkdir(parents=True, exist_ok=True)
    module.write_text(FINDINGS_MODULE, encoding="utf-8")
    test.write_text(FINDINGS_TEST, encoding="utf-8")


def write_review_docs(workspace: Path) -> None:
    workflow = workspace / "docs" / "review-workflow.md"
    dataset = workspace / "review_dataset" / "README.md"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    dataset.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(REVIEW_WORKFLOW, encoding="utf-8")
    dataset.write_text(DATASET_README, encoding="utf-8")


def apply_task(workspace: Path, task: str) -> None:
    if task == "findings-contract":
        write_findings_contract(workspace)
    elif task == "review-docs":
        write_review_docs(workspace)
    else:
        raise ValueError(f"unknown parallel task: {task}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply one scoped parallel task")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--task", required=True)
    args = parser.parse_args(argv)
    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError(f"workspace does not exist: {workspace}")
    apply_task(workspace, args.task)
    print(f"parallel task completed: {args.task}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
