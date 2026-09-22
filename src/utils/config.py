from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when MailLaunch configuration is invalid."""


@dataclass(frozen=True)
class SendSettings:
    min_delay_seconds: float = 60
    max_delay_seconds: float = 180
    retry_failed: bool = True
    retry_attempts: int = 2


@dataclass(frozen=True)
class Settings:
    provider: str = "gmail"
    daily_limit: int = 100
    gmail_client_id: str | None = None
    gmail_client_secret: str | None = None
    microsoft_client_id: str | None = None
    send: SendSettings = SendSettings()


def _as_mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a mapping")
    return value


def load_settings(path: str | Path | None = None) -> Settings:
    load_dotenv()
    config_path = Path(path or "maillaunch.config.yaml")
    raw: dict[str, Any] = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        raw = _as_mapping(loaded, "configuration")

    provider = str(raw.get("provider", "gmail")).lower()
    if provider not in {"gmail", "microsoft"}:
        raise ConfigError("provider must be gmail or microsoft")

    daily_limit = int(raw.get("daily_limit", 100))
    if daily_limit < 1:
        raise ConfigError("daily_limit must be positive")

    send_raw = _as_mapping(raw.get("send"), "send")
    send = SendSettings(
        min_delay_seconds=float(send_raw.get("min_delay_seconds", 60)),
        max_delay_seconds=float(send_raw.get("max_delay_seconds", 180)),
        retry_failed=bool(send_raw.get("retry_failed", True)),
        retry_attempts=int(send_raw.get("retry_attempts", 2)),
    )
    if send.min_delay_seconds < 0 or send.max_delay_seconds < send.min_delay_seconds:
        raise ConfigError("send delay bounds are invalid")
    if send.retry_attempts < 0:
        raise ConfigError("retry_attempts cannot be negative")

    gmail = _as_mapping(raw.get("gmail"), "gmail")
    microsoft = _as_mapping(raw.get("microsoft"), "microsoft")
    return Settings(
        provider=provider,
        daily_limit=daily_limit,
        gmail_client_id=os.getenv("GMAIL_CLIENT_ID") or gmail.get("client_id") or None,
        gmail_client_secret=os.getenv("GMAIL_CLIENT_SECRET") or gmail.get("client_secret") or None,
        microsoft_client_id=os.getenv("MICROSOFT_CLIENT_ID") or microsoft.get("client_id") or None,
        send=send,
    )
