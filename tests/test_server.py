from __future__ import annotations

import json
import shutil
import unittest
import urllib.request
import uuid
from pathlib import Path
from unittest.mock import patch

from pycursor.agent import AgentResult
from pycursor.config import Settings
from pycursor.mcp import MCPManager
from pycursor.server import TaskManager, start_server
from pycursor.sessions import SessionStore


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.test_root = Path(__file__).resolve().parent.parent / ".test-tmp"
        cls.test_root.mkdir(exist_ok=True)

    def test_health_and_file_listing(self) -> None:
        workspace = self.test_root / f"case-{uuid.uuid4().hex}"
        workspace.mkdir()
        try:
            (workspace / "hello.txt").write_text("hello", encoding="utf-8")
            settings = Settings(
                api_key="test",
                workspace=str(workspace),
                auto_start_mcp=False,
            )
            server, app = start_server(
                settings,
                port=0,
                start_mcp=False,
                sessions=SessionStore(workspace / ".sessions"),
            )
            try:
                host, port = server.server_address
                with urllib.request.urlopen(f"http://{host}:{port}/api/health") as response:
                    health = json.loads(response.read())
                self.assertTrue(health["ok"])
                with urllib.request.urlopen(f"http://{host}:{port}/api/files") as response:
                    files = json.loads(response.read())
                self.assertIn(
                    "hello.txt",
                    [entry["path"] for entry in files["entries"]],
                )
            finally:
                server.shutdown()
                server.server_close()
                app.mcp.stop_all()
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_deepseek_defaults(self) -> None:
        settings = Settings()
        self.assertEqual(settings.base_url, "https://api.deepseek.com/v1")
        self.assertEqual(settings.model, "deepseek-chat")

    def test_task_manager_emits_sse_events(self) -> None:
        workspace = self.test_root / f"case-{uuid.uuid4().hex}"
        workspace.mkdir()
        try:
            settings = Settings(
                api_key="test",
                workspace=str(workspace),
                auto_start_mcp=False,
            )
            sessions = SessionStore(workspace / ".sessions")
            mcp = MCPManager(self.test_root / "missing-mcp.json")
            manager = TaskManager(settings, mcp=mcp, sessions=sessions)
            with patch("pycursor.server.AgentRunner") as runner_type:
                runner_type.return_value.run.return_value = AgentResult(
                    content="done",
                    trace=["[step 1] model"],
                )
                task = manager.submit("test")
                self.assertIsNotNone(task.thread)
                task.thread.join(timeout=3)
            events = task.bus.wait_many(0)
            self.assertEqual(events[0].type, "task.queued")
            self.assertEqual(task.status, "completed")
            self.assertTrue(task.bus.closed)
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

