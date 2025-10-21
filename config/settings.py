from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import List, Optional, Tuple

from dotenv import load_dotenv
from pydantic import BaseModel, Field, validator

from collector.timeutil import parse_quiet_hours

load_dotenv()


def _parse_bool(value: str | bool | None, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


class SettingsModel(BaseModel):
    alpha_url: str = Field(default="https://alpha123.uk/zh")
    language: str = Field(default="zh")
    timezone: str = Field(default="Asia/Taipei")
    ahead_minutes: int = Field(default=30, ge=1)
    reminder_offsets: List[int] = Field(default_factory=lambda: [30, 5])
    quiet_hours: Optional[str] = None

    state_file: Path = Field(default=Path("./state/alpha-state.json"))
    state_ttl_hours: int = Field(default=48)

    db_host: str = Field(default="127.0.0.1")
    db_port: int = Field(default=3306)
    db_user: str = Field(default="alpha")
    db_password: str = Field(default="")
    db_name: str = Field(default="alpha_bot")
    db_pool_minsize: int = Field(default=1, ge=1)
    db_pool_maxsize: int = Field(default=5, ge=1)

    cron_expression: str = Field(default="*/1 * * * *")
    run_once: bool = Field(default=False)

    playwright_proxy: Optional[str] = None

    spug_base_url: str = Field(default="https://push.spug.cc")
    spug_token: Optional[str] = None
    spug_timeout_seconds: int = Field(default=10, ge=1)
    spug_quiet_channel: Optional[str] = None

    spug_xsend_user_id: Optional[str] = None
    spug_channel: str = Field(default="voice")

    spug_template_id: Optional[str] = None
    spug_targets: List[str] = Field(default_factory=list)

    log_level: str = Field(default="INFO")
    notify_tba_once: bool = Field(default=True)

    class Config:
        arbitrary_types_allowed = True

    @validator("reminder_offsets", pre=True)
    def _parse_offsets(cls, value):
        if isinstance(value, list):
            return [int(v) for v in value]
        if isinstance(value, str):
            return [int(part.strip()) for part in value.split(",") if part.strip()]
        raise ValueError("reminder_offsets must be list or comma-separated string")

    @validator("spug_targets", pre=True)
    def _parse_targets(cls, value):
        if value is None:
            return []
        if isinstance(value, list):
            return [item.strip() for item in value if item]
        return [item.strip() for item in str(value).split(",") if item.strip()]

    @validator("state_file", pre=True)
    def _parse_state_file(cls, value):
        if isinstance(value, Path):
            return value
        return Path(str(value)).expanduser()


@dataclass
class Settings:
    alpha_url: str
    language: str
    timezone: str
    ahead_minutes: int
    reminder_offsets: List[int]
    quiet_hours: Optional[Tuple[time, time]]
    state_file: Path
    state_ttl_hours: int
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str
    db_pool_minsize: int
    db_pool_maxsize: int
    cron_expression: str
    run_once: bool
    playwright_proxy: Optional[str]
    spug_base_url: str
    spug_token: Optional[str]
    spug_timeout_seconds: int
    spug_quiet_channel: Optional[str]
    spug_xsend_user_id: Optional[str]
    spug_channel: str
    spug_template_id: Optional[str]
    spug_targets: List[str]
    log_level: str
    notify_tba_once: bool


BOOL_FIELDS = {"run_once", "notify_tba_once"}


def load_settings() -> Settings:
    raw: dict[str, str] = {}
    for name in SettingsModel.model_fields:
        env_key = name.upper()
        if env_key in os.environ and os.environ[env_key] != "":
            raw[name] = os.environ[env_key]

    for field in BOOL_FIELDS:
        if field in raw:
            raw[field] = _parse_bool(raw[field])

    model = SettingsModel(**raw)
    quiet_window = parse_quiet_hours(model.quiet_hours)
    return Settings(
        alpha_url=model.alpha_url,
        language=model.language,
        timezone=model.timezone,
        ahead_minutes=model.ahead_minutes,
        reminder_offsets=model.reminder_offsets,
        quiet_hours=quiet_window,
        state_file=model.state_file,
        state_ttl_hours=model.state_ttl_hours,
        db_host=model.db_host,
        db_port=model.db_port,
        db_user=model.db_user,
        db_password=model.db_password,
        db_name=model.db_name,
        db_pool_minsize=model.db_pool_minsize,
        db_pool_maxsize=model.db_pool_maxsize,
        cron_expression=model.cron_expression,
        run_once=model.run_once,
        playwright_proxy=model.playwright_proxy,
        spug_base_url=model.spug_base_url,
        spug_token=model.spug_token,
        spug_timeout_seconds=model.spug_timeout_seconds,
        spug_quiet_channel=model.spug_quiet_channel,
        spug_xsend_user_id=model.spug_xsend_user_id,
        spug_channel=model.spug_channel,
        spug_template_id=model.spug_template_id,
        spug_targets=model.spug_targets,
        log_level=model.log_level.upper(),
        notify_tba_once=model.notify_tba_once,
    )
