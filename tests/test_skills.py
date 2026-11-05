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
    estimate_tokens,
    load_skills,
    parse_skill_document,
    render_skill_template,
    skill_catalog_lines,
    skill_full_text,
    skill_token_stats,
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

    def test_load_skills_from_project(self) -> None:
        registry = load_skills(self.root)
        self.assertEqual(len(registry), 3)
        by_name = {skill.name: skill for skill in registry.skills}
        self.assertEqual(
            set(by_name),
            {"run-tests", "review-diff", "fetch-issue"},
        )
        self.assertFalse(by_name["run-tests"].has_scripts)
        self.assertTrue(by_name["review-diff"].has_scripts)
        self.assertTrue(by_name["fetch-issue"].uses_mcp)
        self.assertIn("run-tests:", "\n".join(skill_catalog_lines(registry)))

    def test_loader_detects_scripts_directory(self) -> None:
        target = self.workspace / "skills" / "review-diff" / "SKILL.md"
        target.parent.mkdir(parents=True)
        (target.parent / "scripts").mkdir()
        target.write_text(
            "---\n"
            "name: review-diff\n"
            "description: Review a git diff. Use this when 用户要求审查 diff。\n"
            "---\n"
            "## 怎么算做完了\n"
            "- 已给出结论\n",
            encoding="utf-8",
        )
        registry = load_skills(self.workspace)
        self.assertTrue(registry.skills[0].has_scripts)

    def test_loader_detects_mcp_usage(self) -> None:
        target = self.workspace / "skills" / "fetch-issue" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text(
            "---\n"
            "name: fetch-issue\n"
            "description: Fetch an issue through MCP. Use this when 用户要求读取 issue。\n"
            "---\n"
            "## 怎么算做完了\n"
            "- 已返回 issue 内容\n",
            encoding="utf-8",
        )
        registry = load_skills(self.workspace)
        self.assertTrue(registry.skills[0].uses_mcp)

    def test_loader_rejects_name_directory_mismatch(self) -> None:
        target = self.workspace / "skills" / "wrong-directory" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text(render_skill_template(), encoding="utf-8")
        with self.assertRaisesRegex(SkillError, "必须与目录名一致"):
            load_skills(self.workspace)

    def test_loader_requires_skill_file(self) -> None:
        (self.workspace / "skills" / "empty-skill").mkdir(parents=True)
        with self.assertRaisesRegex(SkillError, "缺少 SKILL.md"):
            load_skills(self.workspace)

    def test_loader_returns_empty_when_disabled(self) -> None:
        with patch.dict(os.environ, {"ENABLE_SKILLS": "0"}):
            registry = load_skills(self.root)
        self.assertEqual(len(registry), 0)

    def test_disabled_switch(self) -> None:
        text = render_skill_template()
        with patch.dict(os.environ, {"ENABLE_SKILLS": "0"}):
            self.assertFalse(skills_enabled())
            with self.assertRaises(SkillDisabledError):
                parse_skill_document(text)

    def test_token_estimator_handles_english_and_chinese(self) -> None:
        self.assertGreater(estimate_tokens("运行 python -m unittest"), 3)
        self.assertLess(estimate_tokens("短"), estimate_tokens("较长的一段正文"))
        self.assertEqual(estimate_tokens("   "), 0)

    def test_token_stats_compare_catalog_with_full_documents(self) -> None:
        for name, description, body_size in (
            ("run-tests", "跑测试。Use this when 用户说测一下。", 20),
            ("review-diff", "审查 diff。Use this when 用户要求 review diff。", 30),
        ):
            target = self.workspace / "skills" / name / "SKILL.md"
            target.parent.mkdir(parents=True)
            body = "\n".join(
                f"- 检查第 {index} 项" for index in range(body_size)
            )
            target.write_text(
                "---\n"
                f"name: {name}\n"
                f"description: {description}\n"
                "---\n"
                "## 怎么算做完了\n"
                f"{body}\n",
                encoding="utf-8",
            )
        registry = load_skills(self.workspace)
        stats = skill_token_stats(registry)

        self.assertGreater(stats.catalog_tokens, 0)
        self.assertGreater(stats.full_tokens, stats.catalog_tokens)
        self.assertGreater(stats.disclosure_ratio, 1.0)
        self.assertIn("name: review-diff", skill_full_text(registry))

    def test_empty_registry_has_zero_token_stats(self) -> None:
        registry = load_skills(self.workspace)
        stats = skill_token_stats(registry)
        self.assertEqual(stats.catalog_tokens, 0)
        self.assertEqual(stats.full_tokens, 0)
        self.assertEqual(stats.disclosure_ratio, 0.0)


if __name__ == "__main__":
    unittest.main()
