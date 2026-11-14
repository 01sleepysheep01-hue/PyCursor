from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOTS = ("app", "pycursor", "scripts", "tests", "mcp_servers")
EXCLUDED_DIRS = {
    ".git",
    ".build-tmp",
    ".build-venv",
    ".cache",
    ".test-tmp",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "dist-windows",
}
TEXT_SUFFIXES = {
    ".cmd",
    ".ini",
    ".iss",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yml",
    ".yaml",
}
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(
        r"(?:DEEPSEEK_API_KEY|PYCURSOR_API_KEY)[ \t]*=[ \t]*"
        r"(?!$|your|example|replace|<)[A-Za-z0-9_-]{16,}",
        re.IGNORECASE | re.MULTILINE,
    ),
)


def iter_project_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        files.append(path)
    return files


def check_source_hygiene() -> list[str]:
    problems: list[str] = []
    for root_name in SOURCE_ROOTS:
        source_root = ROOT / root_name
        if not source_root.exists():
            problems.append(f"missing source directory: {root_name}")
            continue
        for path in sorted(source_root.rglob("*.py")):
            relative = path.relative_to(ROOT)
            try:
                text = path.read_text(encoding="utf-8")
                compile(text, str(relative), "exec")
            except (OSError, UnicodeError, SyntaxError) as exc:
                problems.append(f"{relative}: {exc}")
                continue
            for line_number, line in enumerate(text.splitlines(), 1):
                if line.endswith((" ", "\t")):
                    problems.append(f"{relative}:{line_number}: trailing whitespace")
                if "\t" in line:
                    problems.append(f"{relative}:{line_number}: tab character")
    return problems


def check_sensitive_files() -> list[str]:
    problems: list[str] = []
    for path in iter_project_files():
        name = path.name
        if name.startswith(".env") and name != ".env.example":
            problems.append(f"sensitive environment file: {path.relative_to(ROOT)}")
    return problems


def check_secret_patterns() -> list[str]:
    problems: list[str] = []
    for path in iter_project_files():
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {
            ".gitignore",
            ".env.example",
        }:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                problems.append(f"possible embedded secret: {path.relative_to(ROOT)}")
                break
    return problems


def run_tests() -> int:
    started = time.perf_counter()
    process = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed = time.perf_counter() - started
    print(f"unittest: {'PASS' if process.returncode == 0 else 'FAIL'} ({elapsed:.2f}s)")
    return process.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run PyCursor's required local checks")
    parser.add_argument(
        "--static-only",
        action="store_true",
        help="Skip unit tests and run syntax, hygiene, and secret checks only",
    )
    args = parser.parse_args(argv)

    started = time.perf_counter()
    checks = (
        ("source hygiene", check_source_hygiene()),
        ("sensitive files", check_sensitive_files()),
        ("embedded secrets", check_secret_patterns()),
    )
    failed = False
    for name, problems in checks:
        if problems:
            failed = True
            print(f"{name}: FAIL")
            for problem in problems:
                print(f"  - {problem}")
        else:
            print(f"{name}: PASS")

    if not args.static_only and run_tests() != 0:
        failed = True

    elapsed = time.perf_counter() - started
    if failed:
        print(f"check: FAILED ({elapsed:.2f}s)")
        return 1
    print(f"check: PASSED ({elapsed:.2f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
