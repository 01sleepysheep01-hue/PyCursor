from __future__ import annotations

import argparse
import json
from pathlib import Path

from pycursor.custom_report import build_custom_report
from pycursor.skill_report import build_skill_report
from pycursor.skills import load_skills


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect PyCursor capabilities")
    subparsers = parser.add_subparsers(dest="command", required=True)

    skills = subparsers.add_parser("skills", help="Generate skill_report.json")
    skills.add_argument("--root", default=".", help="Project root directory")
    skills.add_argument(
        "--out",
        default="skill_report.json",
        help="Output JSON path",
    )

    custom = subparsers.add_parser(
        "custom",
        help="Generate custom_report.json from real local probes",
    )
    custom.add_argument("--root", default=".", help="Project root directory")
    custom.add_argument(
        "--out",
        default="custom_report.json",
        help="Output JSON path",
    )
    return parser


def _write_report(report: dict[str, object], output_path: str) -> None:
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {output}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "skills":
        report = build_skill_report(load_skills(args.root))
    elif args.command == "custom":
        report = build_custom_report(args.root)
    else:
        raise ValueError(f"Unsupported inspect command: {args.command}")

    _write_report(report, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
