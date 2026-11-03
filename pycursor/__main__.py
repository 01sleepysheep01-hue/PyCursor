from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path

from .config import PROJECT_ROOT, Settings


def main() -> None:
    if "--mcp-demo" in sys.argv:
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
    parser = argparse.ArgumentParser(description="Launch the PyCursor desktop app")
    parser.add_argument("--workspace", help="Workspace directory to open")
    args = parser.parse_args()
    settings = Settings.load()
    if args.workspace:
        settings.workspace = str(Path(args.workspace).expanduser().resolve())
    from .desktop import launch_desktop

    launch_desktop(settings)


if __name__ == "__main__":
    main()

