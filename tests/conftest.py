# -*- coding: utf-8 -*-
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tbr_sync.config import Config  # noqa: E402


@pytest.fixture
def config(tmp_path):
    def _make(**overrides):
        base = dict(
            bale_token="bale-token",
            telegram_token="1:telegram-token",
            bale_channel_id="@src",
            telegram_channel_id="@dst",
            bale_username_to_replace=None,
            telegram_username_replacement=None,
            sync_old_messages=False,
            poll_timeout=25,
            poll_limit=100,
            media_group_wait_seconds=0.05,
            force_rtl=False,
            skip_duplicate_media_documents=True,
            debug_media=False,
            log_unsupported_json=False,
            state_db=tmp_path / "state.db",
            temp_dir=tmp_path,
            fallback_send_unsupported_as_text=False,
            log_ignored_updates=False,
            max_file_mb=45,
            telegram_max_retries=3,
            unsupported_log=tmp_path / "unsupported.log",
            skipped_file_notice="skipped {count}",
        )
        base.update(overrides)
        return Config(**base)

    return _make
