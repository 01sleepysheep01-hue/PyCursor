from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run_git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect a reviewable Git diff")
    parser.add_argument("--base", default="HEAD", help="Git revision to compare")
    parser.add_argument("--root", default=".", help="Repository directory")
    parser.add_argument(
        "--max-chars",
        type=int,
        default=30_000,
        help="Maximum number of output characters",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser().resolve()
    status = run_git(["status", "--short"], cwd=root)
    if status.returncode != 0:
        print(status.stderr.strip() or "git status failed", file=sys.stderr)
        return status.returncode

    stat = run_git(["diff", "--stat", args.base], cwd=root)
    diff = run_git(
        ["diff", "--no-ext-diff", "--unified=3", args.base],
        cwd=root,
    )
    if stat.returncode != 0 or diff.returncode != 0:
        error = stat.stderr.strip() or diff.stderr.strip()
        print(error or f"Unable to resolve base revision: {args.base}", file=sys.stderr)
        return 2

    parts = [
        "## Git status",
        status.stdout.rstrip() or "(clean index and worktree)",
        "",
        f"## Diff stat against {args.base}",
        stat.stdout.rstrip() or "(no tracked changes)",
        "",
        f"## Diff against {args.base}",
        diff.stdout.rstrip() or "(no tracked changes)",
    ]
    output = "\n".join(parts).rstrip() + "\n"
    limit = max(1_000, args.max_chars)
    if len(output) > limit:
        output = (
            output[:limit]
            + "\n\n[... diff output truncated; narrow the path or inspect "
            "remaining files separately ...]\n"
        )
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
