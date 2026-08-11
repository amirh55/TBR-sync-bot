# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_SKIPPED_NOTICE = "⚠️ {count} فایل به دلیل محدودیت حجم تلگرام ارسال نشد."


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


def _int(value: str | None, default: int, field: str) -> int:
    if value in (None, ""):
        return default
    try:
        return int(str(value).strip())
    except ValueError:
        raise SystemExit(f"Invalid .env value for {field}: {value!r} (expected a whole number)")


def _float(value: str | None, default: float, field: str) -> float:
    if value in (None, ""):
        return default
    try:
        return float(str(value).strip())
    except ValueError:
        raise SystemExit(f"Invalid .env value for {field}: {value!r} (expected a number)")


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
    log_ignored_updates: bool
    max_file_mb: int
    telegram_max_retries: int
    unsupported_log: Path
    skipped_file_notice: str

    @property
    def max_file_bytes(self) -> int:
        """Zero or below means no size limit is enforced."""
        return max(0, self.max_file_mb) * 1024 * 1024

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
            raise SystemExit(
                "Missing required .env values: "
                + ", ".join(missing)
                + "\nRun 'python3 setup_env.py' (or 'tbrctl config') to create the .env file."
            )

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
            poll_timeout=_int(_env("poll_timeout", "POLL_TIMEOUT"), 25, "poll_timeout"),
            poll_limit=_int(_env("poll_limit", "POLL_LIMIT"), 100, "poll_limit"),
            media_group_wait_seconds=_float(
                _env("media_group_wait_seconds", "MEDIA_GROUP_WAIT_SECONDS"), 1.2, "media_group_wait_seconds"
            ),
            force_rtl=_bool(_env("force_rtl", "FORCE_RTL"), False),
            skip_duplicate_media_documents=_bool(_env("skip_duplicate_media_documents", "SKIP_DUPLICATE_MEDIA_DOCUMENTS"), True),
            debug_media=_bool(_env("debug_media", "DEBUG_MEDIA"), False),
            log_unsupported_json=_bool(_env("log_unsupported_json", "LOG_UNSUPPORTED_JSON"), False),
            state_db=Path(_env("state_db", "STATE_DB", default=".tbr_sync.db") or ".tbr_sync.db"),
            temp_dir=temp_dir,
            fallback_send_unsupported_as_text=_bool(
                _env("fallback_send_unsupported_as_text", "FALLBACK_SEND_UNSUPPORTED_AS_TEXT"), False
            ),
            log_ignored_updates=_bool(_env("log_ignored_updates", "LOG_IGNORED_UPDATES"), False),
            # Telegram bot uploads cap at 50MB; stay a little under it.
            max_file_mb=_int(_env("max_file_mb", "MAX_FILE_MB"), 45, "max_file_mb"),
            telegram_max_retries=_int(_env("telegram_max_retries", "TELEGRAM_MAX_RETRIES"), 5, "telegram_max_retries"),
            unsupported_log=Path(
                _env("unsupported_log", "UNSUPPORTED_LOG", default="unsupported_updates.log") or "unsupported_updates.log"
            ),
            skipped_file_notice=_env("skipped_file_notice", "SKIPPED_FILE_NOTICE", default=DEFAULT_SKIPPED_NOTICE) or "",
        )
