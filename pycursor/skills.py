from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


MAX_SKILL_BYTES = 32_768
MAX_SKILL_LINES = 200
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]")

DEFAULT_SKILL_NAME = "run-tests"
DEFAULT_SKILL_DESCRIPTION = (
    "运行项目测试并总结失败原因。"
    "Use this when 用户说“测一下”“跑测试”“为什么挂了”“测试没过”。"
)


class SkillError(ValueError):
    """技能配置错误。"""


class SkillDisabledError(SkillError):
    """技能系统已被环境变量关闭。"""


@dataclass(frozen=True, slots=True)
class SkillDocument:
    name: str
    description: str
    body: str
    metadata: dict[str, str] = field(default_factory=dict)
    source: Path | None = None
    raw_text: str = ""


@dataclass(frozen=True, slots=True)
class LoadedSkill:
    document: SkillDocument
    directory: Path
    has_scripts: bool
    uses_mcp: bool

    @property
    def name(self) -> str:
        return self.document.name

    @property
    def description(self) -> str:
        return self.document.description


@dataclass(frozen=True, slots=True)
class SkillRegistry:
    root: Path
    skills: tuple[LoadedSkill, ...]

    def get(self, name: str) -> LoadedSkill:
        for skill in self.skills:
            if skill.name == name:
                return skill
        raise KeyError(f"未知技能：{name}")

    def __len__(self) -> int:
        return len(self.skills)


@dataclass(frozen=True, slots=True)
class SkillTokenStats:
    catalog_tokens: int
    full_tokens: int
    disclosure_ratio: float


def skills_enabled() -> bool:
    value = os.environ.get("ENABLE_SKILLS", "1").strip().lower()
    return value not in {"0", "false", "no", "off", "disabled"}


def _require_enabled() -> None:
    if not skills_enabled():
        raise SkillDisabledError(
            "技能系统已关闭。请设置 ENABLE_SKILLS=1 后再使用。"
        )


def _validate_skill_name(name: str) -> None:
    if not SKILL_NAME_PATTERN.fullmatch(name):
        raise SkillError(
            f"技能名不合法：{name!r}。只允许小写字母、数字和单个连字符。"
        )


def _parse_scalar(value: str, *, key: str) -> str:
    value = value.strip()
    if not value:
        raise SkillError(f"技能字段 {key} 不能为空。")

    if value.startswith('"'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise SkillError(f"技能字段 {key} 的双引号格式错误。") from exc
        if not isinstance(parsed, str):
            raise SkillError(f"技能字段 {key} 必须是字符串。")
        return parsed.strip()

    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            raise SkillError(f"技能字段 {key} 的单引号没有闭合。")
        return value[1:-1].strip()

    return value


def _parse_frontmatter(
    frontmatter: str,
    *,
    source: Path | None,
) -> dict[str, str]:
    metadata: dict[str, str] = {}

    for line_number, raw_line in enumerate(frontmatter.splitlines(), start=2):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line[:1].isspace():
            location = f"{source}:" if source else ""
            raise SkillError(
                f"{location}{line_number}: 暂不支持多行或嵌套 YAML。"
            )
        if ":" not in raw_line:
            location = f"{source}:" if source else ""
            raise SkillError(
                f"{location}{line_number}: 元数据必须是 key: value 格式。"
            )

        key, raw_value = raw_line.split(":", 1)
        key = key.strip()
        if not key:
            raise SkillError(f"第 {line_number} 行的元数据键为空。")
        if key in metadata:
            raise SkillError(f"技能元数据重复：{key}")
        metadata[key] = _parse_scalar(raw_value, key=key)

    for required in ("name", "description"):
        if not metadata.get(required):
            raise SkillError(f"SKILL.md 缺少必填字段：{required}")

    _validate_skill_name(metadata["name"])
    return metadata


def parse_skill_document(
    text: str,
    *,
    source: Path | None = None,
) -> SkillDocument:
    """
    解析 SKILL.md。

    格式：
        ---
        name: run-tests
        description: "..."
        ---

        正文
    """
    _require_enabled()

    if len(text.encode("utf-8")) > MAX_SKILL_BYTES:
        raise SkillError(
            f"SKILL.md 超过大小限制：{MAX_SKILL_BYTES} bytes。"
        )

    normalized = text.removeprefix("\ufeff").replace("\r\n", "\n")
    if len(normalized.splitlines()) > MAX_SKILL_LINES:
        raise SkillError(
            f"SKILL.md 超过行数限制：{MAX_SKILL_LINES} 行。"
        )

    lines = normalized.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillError("SKILL.md 必须以 YAML 头 --- 开始。")

    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break

    if closing_index is None:
        raise SkillError("SKILL.md 的 YAML 头缺少结束标记 ---。")

    metadata = _parse_frontmatter(
        "\n".join(lines[1:closing_index]),
        source=source,
    )
    body = "\n".join(lines[closing_index + 1 :]).strip()

    if not body:
        raise SkillError("SKILL.md 正文不能为空。")
    if "## 怎么算做完了" not in body:
        raise SkillError('SKILL.md 必须包含“## 怎么算做完了”一节。')

    return SkillDocument(
        name=metadata["name"],
        description=metadata["description"],
        body=body,
        metadata=metadata,
        source=source,
        raw_text=normalized,
    )


def render_skill_template(
    *,
    name: str = DEFAULT_SKILL_NAME,
    description: str = DEFAULT_SKILL_DESCRIPTION,
) -> str:
    _require_enabled()
    _validate_skill_name(name)
    description_json = json.dumps(description, ensure_ascii=False)

    return f"""---
name: {name}
description: {description_json}
---

## 什么时候用

用户要求验证代码、复现测试失败或定位测试报错时使用。

## 步骤

1. 根据 README 和 pyproject.toml 判断项目测试命令。
2. 先运行一次测试，不要一上来就增加大量详细输出参数。
3. 最多读取 3 个失败用例的 traceback。
4. 按“哪个用例 / 期望什么 / 实际什么 / 最可能原因”总结。
5. 本技能只报告结果，不修改代码。

## 不要做什么

- 不要为了掩盖失败修改测试。
- 不要回注完整 traceback。
- 不要在任务没有结论时宣布完成。

## 怎么算做完了

- 已给出测试通过与失败数量。
- 每个失败用例都有期望、实际和原因。
- 输出中包含明确的下一步建议。
"""


def write_default_skill(project_root: Path | str | None = None) -> Path:
    """
    创建 skills/run-tests/SKILL.md。

    返回值是创建后的 SKILL.md 路径。
    已存在的文件不会被覆盖。
    """
    _require_enabled()
    root = Path(project_root or Path.cwd()).expanduser().resolve()
    skill_dir = root / "skills" / DEFAULT_SKILL_NAME
    target = skill_dir / "SKILL.md"

    if target.exists():
        raise FileExistsError(f"技能文件已存在，拒绝覆盖：{target}")

    skill_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(render_skill_template(), encoding="utf-8")
    return target


def load_skills(project_root: Path | str | None = None) -> SkillRegistry:
    """
    扫描 project_root/skills/*/SKILL.md。

    ENABLE_SKILLS=0 时直接返回空注册表，保持旧版行为。
    """
    root = Path(project_root or Path.cwd()).expanduser().resolve()
    if not skills_enabled():
        return SkillRegistry(root=root, skills=())

    skills_root = (root / "skills").resolve()
    if not skills_root.is_dir():
        return SkillRegistry(root=root, skills=())

    loaded: list[LoadedSkill] = []
    seen_names: set[str] = set()

    for skill_dir in sorted(skills_root.iterdir(), key=lambda path: path.name):
        if not skill_dir.is_dir() or skill_dir.name.startswith("."):
            continue

        resolved_dir = skill_dir.resolve()
        try:
            resolved_dir.relative_to(skills_root)
        except ValueError as exc:
            raise SkillError(
                f"技能目录不能指向 skills/ 之外：{skill_dir}"
            ) from exc

        skill_path = resolved_dir / "SKILL.md"
        if not skill_path.is_file():
            raise SkillError(f"技能目录缺少 SKILL.md：{resolved_dir}")

        try:
            text = skill_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise SkillError(f"SKILL.md 不是 UTF-8：{skill_path}") from exc

        document = parse_skill_document(text, source=skill_path)
        if document.name != resolved_dir.name:
            raise SkillError(
                "技能 name 必须与目录名一致："
                f"{resolved_dir.name!r} != {document.name!r}"
            )

        duplicate_key = document.name.casefold()
        if duplicate_key in seen_names:
            raise SkillError(f"发现重复技能名称：{document.name}")
        seen_names.add(duplicate_key)

        has_scripts = (resolved_dir / "scripts").is_dir()
        uses_mcp = (
            document.metadata.get("uses_mcp", "").strip().lower()
            in {"1", "true", "yes", "on"}
            or re.search(
                r"\bmcp\b",
                f"{document.description}\n{document.body}",
                flags=re.IGNORECASE,
            )
            is not None
        )
        loaded.append(
            LoadedSkill(
                document=document,
                directory=resolved_dir,
                has_scripts=has_scripts,
                uses_mcp=uses_mcp,
            )
        )

    return SkillRegistry(root=root, skills=tuple(loaded))


def skill_catalog_lines(registry: SkillRegistry) -> list[str]:
    lines: list[str] = []
    for skill in registry.skills:
        markers: list[str] = []
        if skill.has_scripts:
            markers.append("scripts")
        if skill.uses_mcp:
            markers.append("mcp")
        suffix = f" [{'/'.join(markers)}]" if markers else ""
        lines.append(f"{skill.name}: {skill.description}{suffix}")
    return lines


def estimate_tokens(text: str) -> int:
    """Estimate prompt tokens without downloading a model-specific tokenizer."""
    return len(TOKEN_PATTERN.findall(text))


def skill_catalog_text(registry: SkillRegistry) -> str:
    return "\n".join(skill_catalog_lines(registry))


def skill_full_text(registry: SkillRegistry) -> str:
    return "\n\n".join(
        skill.document.raw_text
        for skill in registry.skills
        if skill.document.raw_text
    )


def skill_token_stats(registry: SkillRegistry) -> SkillTokenStats:
    catalog_tokens = estimate_tokens(skill_catalog_text(registry))
    full_tokens = estimate_tokens(skill_full_text(registry))
    ratio = (
        round(full_tokens / catalog_tokens, 3)
        if catalog_tokens and full_tokens
        else 0.0
    )
    return SkillTokenStats(
        catalog_tokens=catalog_tokens,
        full_tokens=full_tokens,
        disclosure_ratio=ratio,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect PyCursor skills")
    parser.add_argument("--root", default=".", help="项目根目录")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    registry = load_skills(args.root)
    token_stats = skill_token_stats(registry)
    if args.json:
        payload = {
            "enabled": skills_enabled(),
            "root": str(registry.root),
            "catalog_tokens": token_stats.catalog_tokens,
            "full_tokens": token_stats.full_tokens,
            "disclosure_ratio": token_stats.disclosure_ratio,
            "skills": [
                {
                    "name": skill.name,
                    "description": skill.description,
                    "has_scripts": skill.has_scripts,
                    "uses_mcp": skill.uses_mcp,
                    "path": str(skill.document.source),
                }
                for skill in registry.skills
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif not skills_enabled():
        print("Skills disabled: ENABLE_SKILLS=0")
    elif not registry.skills:
        print("No skills found.")
    else:
        print(f"Found {len(registry.skills)} skill(s):")
        for line in skill_catalog_lines(registry):
            print(f"- {line}")
        print(
            "Token estimates: "
            f"catalog={token_stats.catalog_tokens}, "
            f"full={token_stats.full_tokens}, "
            f"ratio={token_stats.disclosure_ratio}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
