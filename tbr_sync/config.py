# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _env(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value.strip()
    return default


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Config:
    bale_token: str
    telegram_token: str
    bale_channel_id: str
    telegram_channel_id: str
    bale_username_to_replace: str | None
    telegram_username_replacement: str | None
    sync_old_messages: bool
    poll_timeout: int
    poll_limit: int
    media_group_wait_seconds: float
    force_rtl: bool
    skip_duplicate_media_documents: bool
    debug_media: bool
    log_unsupported_json: bool
    state_db: Path
    temp_dir: Path
    fallback_send_unsupported_as_text: bool

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv(override=True)

        bale_token = _env("bale_token", "BALE_TOKEN")
        telegram_token = _env("telegram_token", "TELEGRAM_TOKEN")
        bale_channel_id = _env("bale_channel_id", "BALE_CHANNEL_ID", "bale_channel", "BALE_CHANNEL")
        telegram_channel_id = _env("telegram_channel_id", "TELEGRAM_CHANNEL_ID", "telegram_channel", "TELEGRAM_CHANNEL")

        missing = []
        if not bale_token:
            missing.append("bale_token")
        if not telegram_token:
            missing.append("telegram_token")
        if not bale_channel_id:
            missing.append("bale_channel_id")
        if not telegram_channel_id:
            missing.append("telegram_channel_id")
        if missing:
            raise SystemExit("Missing required .env values: " + ", ".join(missing))

        temp_dir = Path(_env("temp_dir", "TEMP_DIR", default="temp_downloads") or "temp_downloads")
        temp_dir.mkdir(parents=True, exist_ok=True)

        return cls(
            bale_token=bale_token,
            telegram_token=telegram_token,
            bale_channel_id=bale_channel_id,
            telegram_channel_id=telegram_channel_id,
            bale_username_to_replace=_env("bale_username_to_replace", "BALE_USERNAME_TO_REPLACE"),
            telegram_username_replacement=_env("telegram_username_replacement", "TELEGRAM_USERNAME_REPLACEMENT"),
            sync_old_messages=_bool(_env("sync_old_messages", "SYNC_OLD_MESSAGES"), False),
            poll_timeout=int(_env("poll_timeout", "POLL_TIMEOUT", default="25") or 25),
            poll_limit=int(_env("poll_limit", "POLL_LIMIT", default="100") or 100),
            media_group_wait_seconds=float(_env("media_group_wait_seconds", "MEDIA_GROUP_WAIT_SECONDS", default="1.2") or 1.2),
            force_rtl=_bool(_env("force_rtl", "FORCE_RTL"), False),
            skip_duplicate_media_documents=_bool(_env("skip_duplicate_media_documents", "SKIP_DUPLICATE_MEDIA_DOCUMENTS"), True),
            debug_media=_bool(_env("debug_media", "DEBUG_MEDIA"), False),
            log_unsupported_json=_bool(_env("log_unsupported_json", "LOG_UNSUPPORTED_JSON"), False),
            state_db=Path(_env("state_db", "STATE_DB", default=".tbr_sync.db") or ".tbr_sync.db"),
            temp_dir=temp_dir,
            fallback_send_unsupported_as_text=_bool(
                _env("fallback_send_unsupported_as_text", "FALLBACK_SEND_UNSUPPORTED_AS_TEXT"), False
            ),
        )
