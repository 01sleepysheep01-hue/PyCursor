from __future__ import annotations

import json
import os
import stat
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _choose_state_dir() -> Path:
    candidates = [
        Path(os.environ["PYCURSOR_STATE_DIR"])
        if os.environ.get("PYCURSOR_STATE_DIR")
        else None,
        Path.home() / ".pycursor",
        PROJECT_ROOT / ".pycursor",
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    raise RuntimeError("无法创建 PyCursor 状态目录")


STATE_DIR = _choose_state_dir()
CONFIG_PATH = STATE_DIR / "config.json"


def _read_dot_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


@dataclass(slots=True)
class Settings:
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    workspace: str = str(PROJECT_ROOT / "examples" / "workspace")
    max_steps: int = 12
    command_timeout: int = 45
    context_char_limit: int = 70_000
    mcp_config: str = str(PROJECT_ROOT / "mcp.json")
    auto_start_mcp: bool = True
    temperature: float = 0.1

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Settings":
        env_file = _read_dot_env(PROJECT_ROOT / ".env")
        saved: dict[str, Any] = {}
        if path.exists():
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                saved = {}

        values: dict[str, Any] = {}
        for field in fields(cls):
            env_name = f"PYCURSOR_{field.name.upper()}"
            if env_name in os.environ:
                values[field.name] = os.environ[env_name]
            elif field.name == "api_key" and "DEEPSEEK_API_KEY" in os.environ:
                values[field.name] = os.environ["DEEPSEEK_API_KEY"]
            elif field.name in env_file:
                values[field.name] = env_file[field.name]
            elif field.name == "api_key" and "DEEPSEEK_API_KEY" in env_file:
                values[field.name] = env_file["DEEPSEEK_API_KEY"]
            elif field.name in saved:
                values[field.name] = saved[field.name]

        settings = cls(**values)
        settings.workspace = str(Path(settings.workspace).expanduser().resolve())
        settings.mcp_config = str(Path(settings.mcp_config).expanduser().resolve())
        settings.max_steps = max(1, min(int(settings.max_steps), 40))
        settings.command_timeout = max(1, min(int(settings.command_timeout), 300))
        settings.context_char_limit = max(8_000, int(settings.context_char_limit))
        settings.temperature = max(0.0, min(float(settings.temperature), 2.0))
        if isinstance(settings.auto_start_mcp, str):
            settings.auto_start_mcp = settings.auto_start_mcp.strip().lower() not in {
                "",
                "0",
                "false",
                "no",
                "off",
            }
        return settings

    def save(self, path: Path = CONFIG_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["api_key"] = "••••••••" if self.api_key else ""
        return data

    def validate(self) -> None:
        workspace = Path(self.workspace)
        if not workspace.exists():
            raise ValueError(f"工作区不存在：{workspace}")
        if not workspace.is_dir():
            raise ValueError(f"工作区不是目录：{workspace}")
        if not self.api_key:
            raise ValueError(
                "尚未配置 DeepSeek API Key。请打开“设置”填写 Key，"
                "或设置 DEEPSEEK_API_KEY / PYCURSOR_API_KEY。"
            )
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("API Base URL 必须以 http:// 或 https:// 开头")
        if not self.model.strip():
            raise ValueError("模型名称不能为空")

