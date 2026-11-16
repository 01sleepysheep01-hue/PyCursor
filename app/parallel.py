from __future__ import annotations

import argparse
import json
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True, slots=True)
class ParallelTask:
    id: str
    title: str
    branch_label: str
    worker_name: str
    scope: tuple[str, ...]


DEFAULT_TASKS = (
    ParallelTask(
        id="findings-contract",
        title="添加稳定的评审发现数据契约",
        branch_label="findings-contract",
        worker_name="findings-contract",
        scope=("codeproof/review_findings.py", "tests/test_review_findings.py"),
    ),
    ParallelTask(
        id="review-docs",
        title="补充代码评审工作流与数据集说明",
        branch_label="review-docs",
        worker_name="review-docs",
        scope=("docs/review-workflow.md", "review_dataset/README.md"),
    ),
)


@dataclass(frozen=True, slots=True)
class CommandResult:
    command: str
    returncode: int
    duration_ms: int
    output: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0


def _run(command: list[str], cwd: Path, timeout: int) -> CommandResult:
    started = time.perf_counter()
    process = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )
    duration_ms = round((time.perf_counter() - started) * 1000)
    output = (process.stdout or "") + (process.stderr or "")
    display = list(command)
    if display and display[0] == sys.executable:
        display[0] = "python"
    return CommandResult(
        command=" ".join(display),
        returncode=process.returncode,
        duration_ms=duration_ms,
        output=output,
    )


def _git(cwd: Path, *args: str, timeout: int = 120) -> CommandResult:
    return _run(["git", *args], cwd, timeout)


def _git_output(cwd: Path, *args: str, timeout: int = 120) -> str:
    result = _git(cwd, *args, timeout=timeout)
    if not result.passed:
        raise RuntimeError(
            f"git {' '.join(args)} failed:\n{result.output[-2000:]}"
        )
    return result.output.strip()


def _changed_files(worktree: Path) -> list[str]:
    output = _git_output(worktree, "status", "--porcelain", "--untracked-files=all")
    files: list[str] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append(path.strip('"'))
    return sorted(files)


def _task_report(
    task: ParallelTask,
    branch: str,
    worktree: Path,
    started_at: str,
    finished_at: str,
    task_result: CommandResult,
    test_result: CommandResult,
    changed_files: list[str],
    commit: str,
) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "branch": branch,
        "worktree": worktree.name,
        "scope": list(task.scope),
        "started_at": started_at,
        "finished_at": finished_at,
        "task_duration_ms": task_result.duration_ms,
        "test_duration_ms": test_result.duration_ms,
        "task_exit_code": task_result.returncode,
        "test_exit_code": test_result.returncode,
        "tests_passed": test_result.passed,
        "changed_files": changed_files,
        "commit": commit,
        "output_tail": (task_result.output + test_result.output)[-2000:],
    }


def _execute_task(
    task: ParallelTask,
    branch: str,
    worktree: Path,
    worker_script: Path,
    timeout: int,
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    task_result = _run(
        [
            sys.executable,
            str(worker_script),
            "--workspace",
            str(worktree),
            "--task",
            task.worker_name,
        ],
        worktree,
        timeout,
    )
    if not task_result.passed:
        raise RuntimeError(
            f"parallel task {task.id} failed:\n{task_result.output[-2000:]}"
        )

    test_result = _run(
        [sys.executable, "scripts/check.py"],
        worktree,
        timeout,
    )
    if not test_result.passed:
        raise RuntimeError(
            f"parallel worktree {task.id} tests failed:\n{test_result.output[-2000:]}"
        )

    changed_files = _changed_files(worktree)
    expected = set(task.scope)
    if set(changed_files) != expected:
        raise RuntimeError(
            f"parallel task {task.id} escaped scope: {changed_files}; expected {sorted(expected)}"
        )

    _git_output(worktree, "add", "--", *changed_files)
    _git_output(
        worktree,
        "commit",
        "--no-verify",
        "-m",
        f"feat(parallel): {task.title}",
    )
    commit = _git_output(worktree, "rev-parse", "HEAD")
    finished_at = datetime.now(timezone.utc).isoformat()
    return _task_report(
        task,
        branch,
        worktree,
        started_at,
        finished_at,
        task_result,
        test_result,
        changed_files,
        commit,
    )


def _merge_branches(
    project_root: Path,
    branches: list[str],
    timeout: int,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    conflict_files: list[str] = []
    for branch in branches:
        result = _git(
            project_root,
            "merge",
            "--no-ff",
            "--no-edit",
            branch,
            timeout=timeout,
        )
        conflicts = _git_output(
            project_root,
            "diff",
            "--name-only",
            "--diff-filter=U",
        ).splitlines()
        conflicts = [path for path in conflicts if path.strip()]
        records.append(
            {
                "branch": branch,
                "merged": result.passed,
                "exit_code": result.returncode,
                "conflict_files": conflicts,
                "output_tail": result.output[-1200:],
            }
        )
        if not result.passed:
            conflict_files.extend(conflicts)
            _git(project_root, "merge", "--abort")
            raise RuntimeError(
                "parallel merge conflict in files: "
                + (", ".join(conflict_files) or "(unknown)")
            )

    return {
        "merged": True,
        "merge_strategy": "two sequential --no-ff merges",
        "conflict_files": conflict_files,
        "conflict_reason": (
            "两个任务只修改互不相交的约定文件；Git 未报告冲突。"
            if not conflict_files
            else "任务修改了同一文件或契约。"
        ),
        "branches": records,
    }


def _remove_worktree(project_root: Path, worktree: Path) -> None:
    result = _git(project_root, "worktree", "remove", "--force", str(worktree))
    if result.passed:
        return
    if worktree.exists():
        shutil.rmtree(worktree, ignore_errors=True)
    _git(project_root, "worktree", "prune")


def build_parallel_report(
    project_root: str | Path = PROJECT_ROOT,
    *,
    timeout: int = 300,
    keep_worktrees: bool = False,
    worktree_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    worker_script = root / "scripts" / "parallel_worker.py"
    if not worker_script.is_file():
        raise FileNotFoundError(worker_script)

    base_branch = _git_output(root, "branch", "--show-current")
    if not base_branch:
        raise RuntimeError("parallel orchestration requires a named Git branch")
    base_commit = _git_output(root, "rev-parse", "HEAD")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(2)
    if worktree_root:
        temp_root = Path(worktree_root).expanduser().resolve()
        temp_root.mkdir(parents=True, exist_ok=True)
    else:
        temp_root = Path(
            tempfile.mkdtemp(prefix=".codeproof-parallel-", dir=root.parent)
        )
    worktrees: list[Path] = []
    branches: list[str] = []
    worker_reports: list[dict[str, Any]] = []
    orchestration_started = time.perf_counter()

    try:
        for task in DEFAULT_TASKS:
            branch = f"parallel/{task.branch_label}-{run_id}"
            worktree = temp_root / task.branch_label
            result = _git(
                root,
                "worktree",
                "add",
                "-b",
                branch,
                str(worktree),
                base_commit,
                timeout=timeout,
            )
            if not result.passed:
                raise RuntimeError(result.output[-2000:])
            branches.append(branch)
            worktrees.append(worktree)

        with ThreadPoolExecutor(max_workers=len(DEFAULT_TASKS)) as pool:
            futures = {
                pool.submit(
                    _execute_task,
                    task,
                    branches[index],
                    worktrees[index],
                    worker_script,
                    timeout,
                ): task
                for index, task in enumerate(DEFAULT_TASKS)
            }
            for future in as_completed(futures):
                worker_reports.append(future.result())

        worker_reports.sort(key=lambda item: item["id"])
        merge = _merge_branches(root, branches, timeout)
        final_tests = _run(
            [sys.executable, "scripts/check.py"],
            root,
            timeout,
        )
        if not final_tests.passed:
            raise RuntimeError(
                "merged repository tests failed:\n" + final_tests.output[-2000:]
            )
    finally:
        if not keep_worktrees:
            for worktree in worktrees:
                _remove_worktree(root, worktree)
            shutil.rmtree(temp_root, ignore_errors=True)

    wall_time_ms = round((time.perf_counter() - orchestration_started) * 1000)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution_mode": "deterministic_scoped_workers",
        "base_branch": base_branch,
        "base_commit": base_commit,
        "run_id": run_id,
        "concurrency": {
            "worker_count": len(worker_reports),
            "parallel": True,
            "wall_time_ms": wall_time_ms,
            "sum_task_duration_ms": sum(
                item["task_duration_ms"] for item in worker_reports
            ),
        },
        "workers": worker_reports,
        "merge": merge,
        "final_tests": {
            "command": final_tests.command,
            "passed": final_tests.passed,
            "exit_code": final_tests.returncode,
            "duration_ms": final_tests.duration_ms,
            "output_tail": final_tests.output[-2000:],
        },
        "pass": (
            len(worker_reports) == 2
            and all(item["tests_passed"] for item in worker_reports)
            and merge["merged"]
            and final_tests.passed
        ),
    }


def _write_report(report: dict[str, Any], output_path: str) -> Path:
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run two scoped tasks in isolated Git worktrees and merge them"
    )
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    parser.add_argument("--out", default="parallel_report.json")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument(
        "--keep-worktrees",
        action="store_true",
        help="Keep temporary worktrees for manual inspection",
    )
    parser.add_argument(
        "--worktree-root",
        help="Optional parent directory for the two worktrees",
    )
    args = parser.parse_args(argv)

    report = build_parallel_report(
        args.root,
        timeout=args.timeout,
        keep_worktrees=args.keep_worktrees,
        worktree_root=args.worktree_root,
    )
    output = _write_report(report, args.out)
    print(f"Wrote {output}")
    for worker in report["workers"]:
        print(f"{worker['branch']}: {worker['task_duration_ms']} ms")
    print(f"Merge conflicts: {len(report['merge']['conflict_files'])}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
