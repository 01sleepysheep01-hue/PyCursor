from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pycursor import __version__


@dataclass(frozen=True, slots=True)
class CommandResult:
    command: str
    returncode: int
    duration_ms: int
    output_tail: str
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return self.returncode == 0 and not self.timed_out


CommandRunner = Callable[[Sequence[str], Path, int], CommandResult]


PILLARS = (
    ("style", "样式与校验"),
    ("build", "构建系统"),
    ("tests", "测试"),
    ("docs", "文档"),
    ("environment", "开发环境"),
    ("observability", "可观测性"),
    ("security", "安全"),
    ("task_discovery", "任务发现"),
    ("product", "产品与实验"),
)


LEVELS = (
    ("L1", "能跑"),
    ("L2", "写下来了"),
    ("L3", "标准化"),
    ("L4", "优化过"),
    ("L5", "不用管"),
)


def _tail(text: str, limit: int = 4000) -> str:
    return text[-limit:] if len(text) > limit else text


def run_command(
    command: Sequence[str],
    cwd: Path,
    timeout_seconds: int,
) -> CommandResult:
    started = time.perf_counter()
    display_command = list(command)
    if display_command and display_command[0] == sys.executable:
        display_command[0] = "python"
    command_text = " ".join(display_command)
    try:
        process = subprocess.run(
            list(command),
            cwd=cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_seconds,
        )
        duration_ms = round((time.perf_counter() - started) * 1000)
        output = (process.stdout or "") + (process.stderr or "")
        return CommandResult(
            command=command_text,
            returncode=process.returncode,
            duration_ms=duration_ms,
            output_tail=_tail(output),
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = round((time.perf_counter() - started) * 1000)
        output = (exc.stdout or "") + (exc.stderr or "")
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return CommandResult(
            command=command_text,
            returncode=124,
            duration_ms=duration_ms,
            output_tail=_tail(str(output)),
            timed_out=True,
        )
    except OSError as exc:
        duration_ms = round((time.perf_counter() - started) * 1000)
        return CommandResult(
            command=command_text,
            returncode=127,
            duration_ms=duration_ms,
            output_tail=str(exc),
        )


def _read(root: Path, relative: str) -> str:
    path = root / relative
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _check(
    pillar: str,
    check_id: str,
    title: str,
    passed: bool,
    evidence: str,
    *,
    level: str,
    weight: int = 1,
) -> dict[str, Any]:
    return {
        "pillar": pillar,
        "id": check_id,
        "title": title,
        "passed": passed,
        "evidence": evidence,
        "level": level,
        "weight": weight,
    }


def _build_checks(
    root: Path,
    check_command: CommandResult,
    import_command: CommandResult,
) -> list[dict[str, Any]]:
    ci = _read(root, ".github/workflows/ci.yml")
    pre_commit = _read(root, ".githooks/pre-commit")
    ignore = _read(root, ".gitignore")
    agents = _read(root, "AGENTS.md")
    readme = _read(root, "README.md")
    pyproject = _read(root, "pyproject.toml")
    tools_source = _read(root, "pycursor/tools.py").lower()
    server_source = _read(root, "pycursor/server.py").lower()

    return [
        _check(
            "style",
            "syntax",
            "所有 Python 源文件可编译",
            check_command.passed,
            check_command.command,
            level="L1",
        ),
        _check(
            "style",
            "hygiene",
            "统一检查覆盖尾随空白和 Tab",
            "trailing whitespace" in _read(root, "scripts/check.py"),
            "scripts/check.py",
            level="L3",
        ),
        _check(
            "style",
            "static_entry",
            "存在独立静态检查入口",
            (root / "scripts/check.py").is_file(),
            "scripts/check.py",
            level="L2",
        ),
        _check(
            "build",
            "imports",
            "应用与后端包可导入",
            import_command.passed,
            import_command.command,
            level="L1",
        ),
        _check(
            "build",
            "packaging",
            "声明 Python 版本与构建后端",
            "build-system" in pyproject and "requires-python" in pyproject,
            "pyproject.toml",
            level="L2",
        ),
        _check(
            "build",
            "entry_points",
            "提供桌面端与后端命令入口",
            "pycursor =" in pyproject and "pycursor-server =" in pyproject,
            "pyproject.toml",
            level="L3",
        ),
        _check(
            "tests",
            "suite_exists",
            "存在自动测试目录",
            (root / "tests").is_dir(),
            "tests/",
            level="L1",
        ),
        _check(
            "tests",
            "one_command",
            "一条命令运行测试与静态检查",
            check_command.passed,
            check_command.command,
            level="L3",
            weight=2,
        ),
        _check(
            "tests",
            "ci_enforcement",
            "CI 强制执行同一检查入口",
            "scripts/check.py" in ci,
            ".github/workflows/ci.yml",
            level="L3",
            weight=2,
        ),
        _check(
            "docs",
            "readme",
            "README 说明安装、启动与测试",
            all(token in readme for token in ("从源码启动", "测试", "打包")),
            "README.md",
            level="L1",
        ),
        _check(
            "docs",
            "agents",
            "AGENTS.md 写清构建与测试命令",
            "scripts/check.py" in agents,
            "AGENTS.md",
            level="L2",
        ),
        _check(
            "docs",
            "readiness_docs",
            "存在独立体检文档",
            (root / "docs/readiness.md").is_file(),
            "docs/readiness.md",
            level="L2",
        ),
        _check(
            "environment",
            "env_example",
            "提供不含真实值的 .env.example",
            (root / ".env.example").is_file(),
            ".env.example",
            level="L2",
        ),
        _check(
            "environment",
            "reproducible_command",
            "环境可从项目源码复现",
            import_command.passed and "从源码启动" in readme,
            "README.md + import check",
            level="L2",
        ),
        _check(
            "environment",
            "dependency_boundary",
            "运行时依赖边界明确",
            "dependencies = []" in pyproject,
            "pyproject.toml",
            level="L3",
        ),
        _check(
            "observability",
            "event_bus",
            "工具与任务事件进入统一事件总线",
            (root / "pycursor/events.py").is_file(),
            "pycursor/events.py",
            level="L2",
        ),
        _check(
            "observability",
            "trace_docs",
            "存在可核对的 Trace 文档",
            (root / "docs/trace.md").is_file(),
            "docs/trace.md",
            level="L3",
        ),
        _check(
            "observability",
            "bounded_output",
            "命令输出有截断和超时记录",
            "max_output_chars" in tools_source and "timeout" in tools_source,
            "pycursor/tools.py",
            level="L3",
        ),
        _check(
            "security",
            "env_ignored",
            ".env 与本地配置被 Git 忽略",
            ".env" in ignore and ".pycursor/" in ignore,
            ".gitignore",
            level="L3",
            weight=2,
        ),
        _check(
            "security",
            "pre_commit",
            "提交前阻止敏感文件与 API Key",
            "likely API key" in pre_commit and ".env" in pre_commit,
            ".githooks/pre-commit",
            level="L3",
            weight=2,
        ),
        _check(
            "security",
            "secret_scan",
            "统一检查扫描环境文件与疑似密钥",
            check_command.passed,
            "scripts/check.py",
            level="L3",
            weight=2,
        ),
        _check(
            "task_discovery",
            "agents_guidance",
            "仓库入口规则可被 agent 读取",
            (root / "AGENTS.md").is_file(),
            "AGENTS.md",
            level="L2",
        ),
        _check(
            "task_discovery",
            "skills_catalog",
            "至少有一个可迁移技能目录",
            any((root / "skills").glob("*/SKILL.md")),
            "skills/",
            level="L2",
        ),
        _check(
            "task_discovery",
            "background_recovery",
            "后台任务具备恢复状态",
            "resume" in server_source,
            "pycursor/server.py",
            level="L4",
        ),
        _check(
            "task_discovery",
            "worktree_orchestration",
            "存在 worktree 并行编排入口",
            any(root.glob("**/parallel*.py")),
            "parallel orchestrator",
            level="L4",
        ),
        _check(
            "product",
            "demo",
            "提供可运行的演示素材",
            (root / "demo.mp4").is_file() and (root / "docs/demo.md").is_file(),
            "demo.mp4 + docs/demo.md",
            level="L2",
        ),
        _check(
            "product",
            "reports",
            "旧增量报告可由程序复现",
            (root / "app/inspect.py").is_file()
            and (root / "skill_report.json").is_file()
            and (root / "custom_report.json").is_file(),
            "app/inspect.py + JSON reports",
            level="L3",
        ),
        _check(
            "product",
            "review_metrics",
            "具备已知 bug PR 的召回率与误报评测",
            (root / "review_report.json").is_file(),
            "review_report.json",
            level="L5",
        ),
        _check(
            "product",
            "unattended_merge",
            "具备无人值守审批与合并闸",
            (root / "app/review.py").is_file()
            and "request_changes" in _read(root, "app/review.py"),
            "app/review.py",
            level="L5",
        ),
    ]


def _level_status(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for level, name in LEVELS:
        level_checks = [check for check in checks if check["level"] == level]
        total = sum(check["weight"] for check in level_checks)
        passed = sum(
            check["weight"] for check in level_checks if check["passed"]
        )
        ratio = passed / total if total else 0.0
        result.append(
            {
                "level": level,
                "name": name,
                "passed_weight": passed,
                "total_weight": total,
                "ratio": round(ratio, 4),
                "unlocked": ratio >= 0.8,
            }
        )
    return result


def _current_level(levels: list[dict[str, Any]]) -> str:
    current = "未达到 L1"
    for level in levels:
        if not level["unlocked"]:
            break
        current = level["level"]
    return current


def _top_gaps(
    checks: list[dict[str, Any]],
    limit: int = 3,
) -> list[dict[str, Any]]:
    failed = [check for check in checks if not check["passed"]]
    failed.sort(key=lambda check: (check["level"], check["pillar"], check["id"]))
    return [
        {
            "pillar": check["pillar"],
            "title": check["title"],
            "needed_for": check["level"],
            "evidence": check["evidence"],
        }
        for check in failed[:limit]
    ]


def _pillar_scores(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pillars: list[dict[str, Any]] = []
    for pillar_id, pillar_name in PILLARS:
        pillar_checks = [check for check in checks if check["pillar"] == pillar_id]
        total = sum(check["weight"] for check in pillar_checks)
        passed = sum(
            check["weight"] for check in pillar_checks if check["passed"]
        )
        score = round(100 * passed / total, 1) if total else 0.0
        pillars.append(
            {
                "id": pillar_id,
                "name": pillar_name,
                "score": score,
                "passed_weight": passed,
                "total_weight": total,
                "checks": pillar_checks,
            }
        )
    return pillars


def build_readiness_report(
    root: str | Path = ".",
    *,
    timeout_seconds: int = 300,
    runner: CommandRunner = run_command,
) -> dict[str, Any]:
    project_root = Path(root).expanduser().resolve()
    check_command = runner(
        [sys.executable, "scripts/check.py"],
        project_root,
        timeout_seconds,
    )
    import_command = runner(
        [sys.executable, "-c", "import app, pycursor"],
        project_root,
        min(timeout_seconds, 60),
    )
    checks = _build_checks(project_root, check_command, import_command)
    levels = _level_status(checks)
    current_level = _current_level(levels)
    pillars = _pillar_scores(checks)
    total_weight = sum(check["weight"] for check in checks)
    passed_weight = sum(check["weight"] for check in checks if check["passed"])
    overall_score = round(100 * passed_weight / total_weight, 1)
    level_pass = (
        current_level.startswith("L")
        and int(current_level[1:]) >= 3
    )

    return {
        "schema_version": 1,
        "project": "CodeProof (PyCursor)",
        "version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "level": current_level,
        "level_pass": level_pass,
        "threshold": "L3",
        "overall_score": overall_score,
        "pillars": pillars,
        "levels": levels,
        "top_gaps": _top_gaps(checks),
        "one_command_check": {
            "command": check_command.command,
            "passed": check_command.passed,
            "exit_code": check_command.returncode,
            "duration_ms": check_command.duration_ms,
            "timed_out": check_command.timed_out,
            "output_tail": check_command.output_tail,
        },
        "import_check": {
            "command": import_command.command,
            "passed": import_command.passed,
            "exit_code": import_command.returncode,
            "duration_ms": import_command.duration_ms,
            "timed_out": import_command.timed_out,
            "output_tail": import_command.output_tail,
        },
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
        description="Score the repository against the nine agent-readiness pillars"
    )
    parser.add_argument("--root", default=".", help="Project root directory")
    parser.add_argument(
        "--out",
        default="readiness_report.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Maximum seconds for the unified check",
    )
    args = parser.parse_args(argv)

    report = build_readiness_report(args.root, timeout_seconds=args.timeout)
    output = _write_report(report, args.out)
    print(f"Wrote {output}")
    print(f"Level: {report['level']} | Score: {report['overall_score']}")
    return 0 if report["level_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
