from __future__ import annotations

import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from pycursor.agents import (
    AgentInstructionError,
    agents_enabled,
    load_agent_instructions,
)


class AgentsInstructionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parent.parent
        cls.test_root = cls.root / ".test-tmp"
        cls.test_root.mkdir(exist_ok=True)

    def setUp(self) -> None:
        self.workspace = self.test_root / f"agents-{uuid.uuid4().hex}"
        self.project = self.workspace / "project"
        self.nested = self.project / "src"
        self.nested.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.workspace, ignore_errors=True)

    def test_global_then_project_specific_order(self) -> None:
        global_file = self.workspace / "global-AGENTS.md"
        global_file.write_text("全局规则", encoding="utf-8")
        (self.project / "AGENTS.md").write_text("项目规则", encoding="utf-8")
        (self.nested / "AGENTS.md").write_text("模块规则", encoding="utf-8")

        bundle = load_agent_instructions(
            self.nested,
            global_paths=(global_file,),
        )
        rendered = bundle.render()

        global_index = rendered.index("全局规则")
        project_index = rendered.index("项目规则")
        nested_index = rendered.index("模块规则")
        self.assertLess(global_index, project_index)
        self.assertLess(project_index, nested_index)

    def test_disabled_switch_returns_empty_bundle(self) -> None:
        global_file = self.workspace / "global-AGENTS.md"
        global_file.write_text("不应加载", encoding="utf-8")
        with patch.dict(os.environ, {"ENABLE_AGENTS": "0"}):
            self.assertFalse(agents_enabled())
            bundle = load_agent_instructions(
                self.nested,
                global_paths=(global_file,),
            )
        self.assertEqual(bundle.files, ())
        self.assertEqual(bundle.render(), "")

    def test_duplicate_paths_are_loaded_once(self) -> None:
        shared = self.project / "AGENTS.md"
        shared.write_text("只出现一次", encoding="utf-8")
        bundle = load_agent_instructions(
            self.nested,
            global_paths=(shared,),
        )
        matching = [item for item in bundle.files if item.source == shared.resolve()]
        self.assertEqual(len(matching), 1)

    def test_non_utf8_file_is_rejected(self) -> None:
        bad = self.workspace / "bad-AGENTS.md"
        bad.write_bytes(b"\xff\xfe\x00")
        with self.assertRaisesRegex(AgentInstructionError, "UTF-8"):
            load_agent_instructions(self.nested, global_paths=(bad,))


if __name__ == "__main__":
    unittest.main()
