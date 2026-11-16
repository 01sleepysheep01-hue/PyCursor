from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


REVIEW_CATEGORIES = frozenset({"correctness", "security", "performance", "quality"})
REVIEW_SEVERITIES = frozenset({"suggestion", "warning", "critical"})


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    path: str
    line: int
    category: str
    severity: str
    message: str
    rule_id: str

    def __post_init__(self) -> None:
        if not self.path.strip():
            raise ValueError("finding path cannot be empty")
        if self.line < 1:
            raise ValueError("finding line must be positive")
        if self.category not in REVIEW_CATEGORIES:
            raise ValueError(f"unknown review category: {self.category}")
        if self.severity not in REVIEW_SEVERITIES:
            raise ValueError(f"unknown review severity: {self.severity}")
        if not self.rule_id.strip():
            raise ValueError("rule_id cannot be empty")

    @property
    def finding_id(self) -> str:
        payload = ":".join(
            (
                self.path.replace("\\", "/"),
                str(self.line),
                self.category,
                self.severity,
                self.rule_id,
                _normalize(self.message),
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, str | int]:
        return {
            "finding_id": self.finding_id,
            "path": self.path,
            "line": self.line,
            "category": self.category,
            "severity": self.severity,
            "rule_id": self.rule_id,
            "message": self.message,
        }
