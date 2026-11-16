from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path

from .config import PROJECT_ROOT, Settings


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "review":
        from app.review import main as review_main

        exit_code = review_main(args[1:])
        if exit_code:
            raise SystemExit(exit_code)
        return
    if "--mcp-demo" in args:
        if sys.stdout is None:
            sys.stdout = open(1, "w", encoding="utf-8", buffering=1, closefd=False)
        if sys.stderr is None:
            sys.stderr = open(2, "w", encoding="utf-8", buffering=1, closefd=False)
        sys.argv = [sys.argv[0]]
        runpy.run_path(
            str(PROJECT_ROOT / "mcp_servers" / "demo_server.py"),
            run_name="__main__",
        )
        return
    parser = argparse.ArgumentParser(description="Launch the CodeProof desktop app")
    parser.add_argument("--workspace", help="Workspace directory to open")
    parsed = parser.parse_args(args)
    settings = Settings.load()
    if parsed.workspace:
        settings.workspace = str(Path(parsed.workspace).expanduser().resolve())
    from .desktop import launch_desktop

    launch_desktop(settings)


if __name__ == "__main__":
    main()

