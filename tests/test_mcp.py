from __future__ import annotations

import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path

from pycursor.mcp import MCPManager


ROOT = Path(__file__).resolve().parent.parent


class MCPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.test_root = ROOT / ".test-tmp"
        cls.test_root.mkdir(exist_ok=True)

    def test_discovers_and_calls_stdio_tool(self) -> None:
        temp_path = self.test_root / f"case-{uuid.uuid4().hex}"
        temp_path.mkdir()
        try:
            config = {
                "servers": {
                    "demo": {
                        "command": sys.executable,
                        "args": [str(ROOT / "mcp_servers" / "demo_server.py")],
                        "cwd": str(temp_path),
                    }
                }
            }
            config_path = temp_path / "mcp.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            manager = MCPManager(config_path)
            try:
                manager.start_enabled()
                self.assertFalse(manager.errors)
                public_name = "mcp__demo__get_system_info"
                self.assertIn(public_name, manager.tools)
                observation = manager.call(public_name, {})
                self.assertIn("PyCursor demo MCP", observation.text)
                self.assertIn("python", observation.text)
            finally:
                manager.stop_all()
        finally:
            shutil.rmtree(temp_path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

