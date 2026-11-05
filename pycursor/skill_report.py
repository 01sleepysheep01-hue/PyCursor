from __future__ import annotations

import re
from typing import Any

from .skills import (
    LoadedSkill,
    SkillRegistry,
    skill_token_stats,
)


TRIGGER_PATTERN = re.compile(r"[“\"]([^”\"]+)[”\"]")

DEFAULT_SKILL_TRIALS: tuple[dict[str, str | None], ...] = (
    {"query": "帮我测一下", "expected": "run-tests"},
    {"query": "测试为什么挂了", "expected": "run-tests"},
    {"query": "审一下 diff", "expected": "review-diff"},
    {"query": "review 改动有没有风险", "expected": "review-diff"},
    {"query": "看看这个 issue", "expected": "fetch-issue"},
    {"query": "读取 GitHub issue 12", "expected": "fetch-issue"},
    {"query": "今天天气怎么样", "expected": None},
    {"query": "把我这两行文字改得更正式", "expected": None},
    {"query": "检查 README 的错别字", "expected": None},
)


def skill_triggers(skill: LoadedSkill) -> tuple[str, ...]:
    instruction = skill.description.split("Use this when", 1)[-1]
    triggers = []
    for value in TRIGGER_PATTERN.findall(instruction):
        normalized = value.strip()
        if normalized and normalized not in triggers:
            triggers.append(normalized)
    return tuple(triggers)


def select_skill(query: str, registry: SkillRegistry) -> str | None:
    normalized_query = query.casefold()
    candidates: list[tuple[int, str]] = []
    for skill in registry.skills:
        for trigger in skill_triggers(skill):
            if trigger.casefold() in normalized_query:
                candidates.append((len(trigger), skill.name))
    if not candidates:
        return None

    candidates.sort(reverse=True)
    best_length, best_name = candidates[0]
    tied_names = {
        name for length, name in candidates if length == best_length
    }
    if len(tied_names) > 1:
        return None
    return best_name


def build_skill_report(
    registry: SkillRegistry,
    trials: tuple[dict[str, str | None], ...] = DEFAULT_SKILL_TRIALS,
) -> dict[str, Any]:
    stats = skill_token_stats(registry)
    results: list[dict[str, Any]] = []
    false_positive = 0

    for trial in trials:
        query = str(trial["query"])
        expected = trial.get("expected")
        hit = select_skill(query, registry)
        if expected is None and hit is not None:
            false_positive += 1
        results.append(
            {
                "query": query,
                "expected": expected,
                "hit": hit,
                "ok": hit == expected,
            }
        )

    return {
        "skills": [
            {
                "name": skill.name,
                "has_scripts": skill.has_scripts,
                "uses_mcp": skill.uses_mcp,
                "form": (
                    "prompt+script"
                    if skill.has_scripts
                    else "prompt+mcp"
                    if skill.uses_mcp
                    else "prompt"
                ),
            }
            for skill in registry.skills
        ],
        "catalog_tokens": stats.catalog_tokens,
        "full_tokens": stats.full_tokens,
        "disclosure_ratio": stats.disclosure_ratio,
        "trials": results,
        "false_positive": false_positive,
    }
