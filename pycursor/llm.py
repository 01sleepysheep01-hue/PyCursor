from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import Settings


@dataclass(slots=True)
class ChatReply:
    content: str
    tool_calls: list[dict[str, Any]]
    raw_message: dict[str, Any]
    usage: dict[str, Any]


class LLMError(Exception):
    pass


class OpenAICompatibleClient:
    """Chat Completions client optimized by default for DeepSeek."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        timeout: int = 120,
    ) -> ChatReply:
        settings = self.settings
        settings.validate()
        endpoint = settings.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": settings.model,
            "messages": messages,
            "temperature": settings.temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "PyCursor/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            detail = body[:1200]
            try:
                parsed = json.loads(body)
                detail = parsed.get("error", {}).get("message", detail)
            except json.JSONDecodeError:
                pass
            raise LLMError(f"模型请求失败（HTTP {exc.code}）：{detail}") from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            raise LLMError(f"无法连接模型服务：{exc}") from exc

        try:
            data = json.loads(raw)
            message = data["choices"][0]["message"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"模型返回了无法识别的响应：{raw[:800]}") from exc

        tool_calls = message.get("tool_calls") or []
        if not isinstance(tool_calls, list):
            raise LLMError("模型返回的 tool_calls 格式错误")
        return ChatReply(
            content=str(message.get("content") or ""),
            tool_calls=tool_calls,
            raw_message=message,
            usage=data.get("usage") or {},
        )

