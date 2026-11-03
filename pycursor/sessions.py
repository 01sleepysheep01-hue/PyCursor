from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .config import STATE_DIR


class SessionStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or (STATE_DIR / "sessions")
        self.directory.mkdir(parents=True, exist_ok=True)

    def new_id(self) -> str:
        return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]

    def path(self, session_id: str) -> Path:
        safe = "".join(ch for ch in session_id if ch.isalnum() or ch in "-_")
        if not safe:
            raise ValueError("非法 session id")
        return self.directory / f"{safe}.json"

    def load(self, session_id: str) -> dict[str, Any]:
        path = self.path(session_id)
        if not path.exists():
            return {"id": session_id, "messages": [], "updated": time.time()}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"id": session_id, "messages": [], "updated": time.time()}

    def append_exchange(
        self,
        session_id: str,
        *,
        user: str,
        assistant: str,
        task_id: str,
        trace_summary: list[str],
    ) -> None:
        data = self.load(session_id)
        messages = data.setdefault("messages", [])
        messages.append(
            {
                "role": "user",
                "content": user,
                "timestamp": time.time(),
                "task_id": task_id,
            }
        )
        messages.append(
            {
                "role": "assistant",
                "content": assistant,
                "timestamp": time.time(),
                "task_id": task_id,
                "trace_summary": trace_summary[-30:],
            }
        )
        data["updated"] = time.time()
        path = self.path(session_id)
        temp = path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(path)

    def recent_messages(self, session_id: str, limit: int = 16) -> list[dict[str, str]]:
        data = self.load(session_id)
        output: list[dict[str, str]] = []
        for item in data.get("messages", [])[-limit:]:
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and isinstance(content, str):
                output.append({"role": role, "content": content[-8_000:]})
        return output

