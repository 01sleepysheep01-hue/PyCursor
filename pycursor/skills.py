from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


MAX_SKILL_BYTES = 32_768
MAX_SKILL_LINES = 200
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

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
