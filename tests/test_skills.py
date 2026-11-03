from __future__ import annotations

import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from pycursor.skills import (
    SkillDisabledError,
    SkillError,
    parse_skill_document,
    render_skill_template,
    skills_enabled,
    write_default_skill,
)


class SkillsParserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parent.parent
        cls.test_root = cls.root / ".test-tmp"
        cls.test_root.mkdir(exist_ok=True)

    def setUp(self) -> None:
        self.workspace = self.test_root / f"skills-{uuid.uuid4().hex}"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.workspace, ignore_errors=True)

    def test_default_template_round_trip(self) -> None:
        text = render_skill_template()
        skill = parse_skill_document(text)
        self.assertEqual(skill.name, "run-tests")
        self.assertIn("跑测试", skill.description)
        self.assertIn("## 怎么算做完了", skill.body)

    def test_write_default_skill(self) -> None:
        target = write_default_skill(self.workspace)
        self.assertEqual(target, self.workspace / "skills" / "run-tests" / "SKILL.md")
        self.assertTrue(target.is_file())
        parsed = parse_skill_document(
            target.read_text(encoding="utf-8"),
            source=target,
        )
        self.assertEqual(parsed.name, "run-tests")

    def test_existing_template_is_not_overwritten(self) -> None:
        target = self.workspace / "skills" / "run-tests" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text("keep me", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            write_default_skill(self.workspace)
        self.assertEqual(target.read_text(encoding="utf-8"), "keep me")

    def test_frontmatter_is_required(self) -> None:
        with self.assertRaisesRegex(SkillError, "必须以 YAML 头"):
            parse_skill_document("# no frontmatter")

    def test_closing_frontmatter_is_required(self) -> None:
        with self.assertRaisesRegex(SkillError, "缺少结束标记"):
            parse_skill_document("---\nname: run-tests\n## body")

    def test_required_fields(self) -> None:
        with self.assertRaisesRegex(SkillError, "description"):
            parse_skill_document("---\nname: run-tests\n---\n## 怎么算做完了")

    def test_invalid_skill_name(self) -> None:
        with self.assertRaisesRegex(SkillError, "技能名不合法"):
            parse_skill_document(
                "---\nname: Run_Tests\ndescription: test\n---\n## 怎么算做完了"
            )

    def test_duplicate_metadata_key(self) -> None:
        with self.assertRaisesRegex(SkillError, "元数据重复"):
            parse_skill_document(
                "---\n"
                "name: run-tests\n"
                "name: review-diff\n"
                "description: test\n"
                "---\n"
                "## 怎么算做完了"
            )

    def test_missing_completion_section(self) -> None:
        with self.assertRaisesRegex(SkillError, "怎么算做完了"):
            parse_skill_document(
                "---\nname: run-tests\ndescription: test\n---\n# body"
            )

    def test_disabled_switch(self) -> None:
        text = render_skill_template()
        with patch.dict(os.environ, {"ENABLE_SKILLS": "0"}):
            self.assertFalse(skills_enabled())
            with self.assertRaises(SkillDisabledError):
                parse_skill_document(text)


if __name__ == "__main__":
    unittest.main()
