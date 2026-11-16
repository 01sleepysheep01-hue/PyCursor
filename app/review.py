from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codeproof.review_findings import ReviewFinding


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True, slots=True)
class AddedLine:
    path: str
    line: int
    text: str


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    findings: tuple[ReviewFinding, ...]
    decision: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "findings": [finding.to_dict() for finding in self.findings],
            "specialists": _specialist_counts(self.findings),
        }


def _specialist_counts(findings: tuple[ReviewFinding, ...]) -> dict[str, int]:
    counts = {
        "correctness": 0,
        "security": 0,
        "performance": 0,
        "quality": 0,
    }
    for finding in findings:
        counts[finding.category] += 1
    return counts


def parse_added_lines(diff_text: str) -> list[AddedLine]:
    lines: list[AddedLine] = []
    path = ""
    next_line = 0
    in_hunk = False
    for raw_line in diff_text.splitlines():
        if raw_line.startswith("+++ b/"):
            path = raw_line[6:]
            in_hunk = False
            continue
        if raw_line.startswith("@@"):
            match = re.search(r"\+(\d+)(?:,\d+)?", raw_line)
            if not match:
                continue
            next_line = int(match.group(1))
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            lines.append(AddedLine(path, next_line, raw_line[1:]))
            next_line += 1
        elif raw_line.startswith("-") or raw_line.startswith("\\"):
            continue
        else:
            next_line += 1
    return lines


def _add(
    findings: dict[tuple[str, int, str], ReviewFinding],
    line: AddedLine,
    *,
    category: str,
    severity: str,
    rule_id: str,
    message: str,
) -> None:
    finding = ReviewFinding(
        path=line.path,
        line=line.line,
        category=category,
        severity=severity,
        message=message,
        rule_id=rule_id,
    )
    findings[(finding.path, finding.line, finding.rule_id)] = finding


def review_diff_text(diff_text: str) -> ReviewOutcome:
    lines = parse_added_lines(diff_text)
    findings: dict[tuple[str, int, str], ReviewFinding] = {}

    for line in lines:
        text = line.text
        stripped = text.strip()
        if re.search(
            r"(?i)\b(password|secret|api[_-]?key|token)\b\s*=\s*['\"][^'\"]{6,}['\"]",
            text,
        ):
            _add(
                findings,
                line,
                category="security",
                severity="critical",
                rule_id="security.hardcoded-credential",
                message="新增了明文凭据，可能随源码泄露。",
            )
        if re.search(r"\b(?:eval|exec)\s*\(", text):
            _add(
                findings,
                line,
                category="security",
                severity="critical",
                rule_id="security.dynamic-code-execution",
                message="动态执行输入字符串，存在任意代码执行风险。",
            )
        if re.search(
            r"\.execute\s*\(\s*(?:f['\"]|['\"].*\+\s*|[A-Za-z_][A-Za-z0-9_]*\s*\+)",
            text,
        ):
            _add(
                findings,
                line,
                category="security",
                severity="critical",
                rule_id="security.sql-injection",
                message="SQL 由输入拼接而成，应改用参数化查询。",
            )
        if re.search(r"\bshell\s*=\s*True\b", text):
            _add(
                findings,
                line,
                category="security",
                severity="critical",
                rule_id="security.shell-injection",
                message="向 shell 传递未约束命令字符串，可能执行注入命令。",
            )
        if re.match(r"^print\s*\(", stripped):
            _add(
                findings,
                line,
                category="quality",
                severity="suggestion",
                rule_id="quality.debug-output",
                message="生产路径仍保留 print 调试输出，应改用结构化日志。",
            )
        if re.search(r"request\.(?:args|json)\s*\[", text):
            _add(
                findings,
                line,
                category="correctness",
                severity="warning",
                rule_id="correctness.direct-request-index",
                message="直接索引请求参数会在字段缺失时抛异常，应先校验或使用 get。",
            )

    by_path: dict[str, list[AddedLine]] = {}
    for line in lines:
        by_path.setdefault(line.path, []).append(line)
    for path_lines in by_path.values():
        pass_lines = [line.line for line in path_lines if line.text.strip() == "pass"]
        for index, line in enumerate(path_lines):
            if not re.search(r"except(?:\s+[^:]+)?\s*:", line.text.strip()):
                pass
            elif any(0 < candidate - line.line <= 3 for candidate in pass_lines):
                _add(
                    findings,
                    line,
                    category="quality",
                    severity="warning",
                    rule_id="quality.swallowed-exception",
                    message="异常被静默吞掉，失败会变得不可观测。",
                )
            if not re.match(r"^(?:async\s+)?for\b", line.text.strip()):
                continue
            for nested in path_lines[index + 1 : index + 4]:
                if nested.line <= line.line:
                    continue
                if re.search(
                    r"\.(?:query|filter|find)\s*\(|\.objects\.get\s*\(",
                    nested.text,
                ):
                    _add(
                        findings,
                        nested,
                        category="performance",
                        severity="warning",
                        rule_id="performance.n-plus-one-query",
                        message="循环内执行查询，数据量增大后会形成 N+1 查询。",
                    )
                    break

    severity_order = {"critical": 0, "warning": 1, "suggestion": 2}
    ordered = tuple(
        sorted(
            findings.values(),
            key=lambda finding: (
                severity_order[finding.severity],
                finding.path,
                finding.line,
                finding.rule_id,
            ),
        )
    )
    if any(finding.severity == "critical" for finding in ordered):
        decision = "request_changes"
    elif ordered:
        decision = "with_comments"
    else:
        decision = "approved"
    return ReviewOutcome(ordered, decision)


def load_dataset(dataset_root: str | Path) -> list[dict[str, Any]]:
    path = Path(dataset_root).expanduser().resolve() / "cases.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("review dataset must contain a non-empty cases list")
    return cases


def evaluate_dataset(dataset_root: str | Path) -> dict[str, Any]:
    cases = load_dataset(dataset_root)
    bug_results: list[dict[str, Any]] = []
    case_results: list[dict[str, Any]] = []
    false_positives: list[dict[str, Any]] = []
    all_findings: list[ReviewFinding] = []

    for case in cases:
        outcome = review_diff_text(str(case["diff"]))
        findings = list(outcome.findings)
        all_findings.extend(findings)
        matched_indexes: set[int] = set()
        known_bugs = case.get("known_bugs") or []
        for bug in known_bugs:
            match_index = next(
                (
                    index
                    for index, finding in enumerate(findings)
                    if index not in matched_indexes
                    and finding.rule_id == bug["rule_id"]
                    and finding.path == bug["path"]
                    and finding.line == int(bug["line"])
                ),
                None,
            )
            hit = match_index is not None
            if match_index is not None:
                matched_indexes.add(match_index)
            bug_results.append(
                {
                    "case_id": case["id"],
                    "bug_id": bug["bug_id"],
                    "description": bug["description"],
                    "expected_rule": bug["rule_id"],
                    "path": bug["path"],
                    "line": int(bug["line"]),
                    "hit": hit,
                    "matched_finding_id": (
                        findings[match_index].finding_id
                        if match_index is not None
                        else None
                    ),
                }
            )
        case_false_positives = [
            finding
            for index, finding in enumerate(findings)
            if index not in matched_indexes
        ]
        false_positives.extend(
            {"case_id": case["id"], **finding.to_dict()}
            for finding in case_false_positives
        )
        case_results.append(
            {
                "case_id": case["id"],
                "title": case["title"],
                "clean_control": bool(case.get("clean_control", False)),
                "decision": outcome.decision,
                "finding_count": len(findings),
                "known_bug_count": len(known_bugs),
                "hit_count": sum(
                    result["hit"]
                    for result in bug_results
                    if result["case_id"] == case["id"]
                ),
            }
        )

    known_bug_count = len(bug_results)
    hit_count = sum(result["hit"] for result in bug_results)
    recall = hit_count / known_bug_count if known_bug_count else 1.0
    false_positive_count = len(false_positives)
    summary_comment = build_summary_comment(
        bug_results,
        case_results,
        hit_count=hit_count,
        known_bug_count=known_bug_count,
        recall=recall,
        false_positive_count=false_positive_count,
    )
    return {
        "schema_version": 1,
        "execution_mode": "deterministic_static_review",
        "description": (
            "所有命中、误报与召回率均由本地规则和固定数据集实际运行生成；"
            "不调用外部 API，也不读取 API Key。"
        ),
        "dataset_cases": len(cases),
        "buggy_cases": sum(not case.get("clean_control", False) for case in cases),
        "clean_cases": sum(bool(case.get("clean_control", False)) for case in cases),
        "known_bug_count": known_bug_count,
        "hit_count": hit_count,
        "recall": round(recall, 4),
        "false_positive_count": false_positive_count,
        "thresholds": {"min_recall": 0.6, "max_false_positives": 3},
        "pass": recall >= 0.6 and false_positive_count <= 3,
        "bugs": bug_results,
        "cases": case_results,
        "false_positives": false_positives,
        "specialist_findings": _specialist_counts(tuple(all_findings)),
        "summary_comment": summary_comment,
    }


def build_summary_comment(
    bugs: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    *,
    hit_count: int,
    known_bug_count: int,
    recall: float,
    false_positive_count: int,
) -> str:
    if any(case["decision"] == "request_changes" for case in cases):
        decision = "request_changes"
    elif any(case["finding_count"] > 0 for case in cases):
        decision = "with_comments"
    else:
        decision = "approved"
    lines = [
        "## CodeProof review",
        "",
        f"判定：`{decision}`",
        f"数据集：{len(cases)} 个 PR，{known_bug_count} 条已知 bug。",
        f"召回：{hit_count}/{known_bug_count}（{recall:.0%}）。",
        f"误报：{false_positive_count} 条。",
        "",
        "逐条结果：",
    ]
    for bug in bugs:
        marker = "命中" if bug["hit"] else "漏报"
        lines.append(
            f"- `{bug['case_id']}/{bug['bug_id']}`：{marker}，"
            f"{bug['path']}:{bug['line']}，{bug['description']}"
        )
    return "\n".join(lines) + "\n"


def build_single_review_comment(outcome: ReviewOutcome) -> str:
    lines = [
        "## CodeProof review",
        "",
        f"判定：`{outcome.decision}`",
        f"发现：{len(outcome.findings)} 条。",
    ]
    for finding in outcome.findings:
        lines.append(
            f"- `{finding.severity}` {finding.path}:{finding.line}："
            f"{finding.message} (`{finding.rule_id}`)"
        )
    return "\n".join(lines) + "\n"


def _write_outputs(
    report: dict[str, Any],
    output_path: str,
    comment_path: str,
) -> tuple[Path, Path]:
    output = Path(output_path).expanduser().resolve()
    comment = Path(comment_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    comment.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    comment.write_text(str(report["summary_comment"]), encoding="utf-8")
    return output, comment


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Review a known-bug dataset and calculate recall and false positives"
    )
    parser.add_argument("--dataset", default="review_dataset")
    parser.add_argument("--out", default="review_report.json")
    parser.add_argument("--comment-out", default="review_comment.md")
    parser.add_argument(
        "--diff-file",
        help="Review one unified diff instead of evaluating the dataset",
    )
    args = parser.parse_args(argv)

    if args.diff_file:
        diff = Path(args.diff_file).expanduser().read_text(encoding="utf-8")
        outcome = review_diff_text(diff)
        comment = build_single_review_comment(outcome)
        report = {**outcome.to_dict(), "summary_comment": comment}
        output, comment_path = _write_outputs(report, args.out, args.comment_out)
        print(f"Wrote {output}")
        print(f"Wrote {comment_path}")
        return 0

    report = evaluate_dataset(args.dataset)
    output, comment_path = _write_outputs(report, args.out, args.comment_out)
    print(f"Wrote {output}")
    print(f"Wrote {comment_path}")
    print(
        f"Recall: {report['hit_count']}/{report['known_bug_count']} | "
        f"False positives: {report['false_positive_count']} | Pass: {report['pass']}"
    )
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
