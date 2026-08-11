# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

OFFSET_KEY = "bale_update_offset"


class MappingStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.conn = sqlite3.connect(path)
        # WAL keeps the mapping durable if the process is killed mid-write.
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS message_map (
                bale_chat_id TEXT NOT NULL,
                bale_message_id TEXT NOT NULL,
                telegram_message_ids TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'message',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (bale_chat_id, bale_message_id)
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------------ mapping

    def save(self, bale_chat_id: str, bale_message_id: str, telegram_message_ids: list[int], kind: str) -> None:
        now = time.time()
        self.conn.execute(
            """
            INSERT INTO message_map (bale_chat_id, bale_message_id, telegram_message_ids, kind, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(bale_chat_id, bale_message_id) DO UPDATE SET
                telegram_message_ids=excluded.telegram_message_ids,
                kind=excluded.kind,
                updated_at=excluded.updated_at
            """,
            (bale_chat_id, bale_message_id, json.dumps(telegram_message_ids), kind, now, now),
        )
        self.conn.commit()

    def get(self, bale_chat_id: str, bale_message_id: str) -> tuple[list[int], str] | None:
        row = self.conn.execute(
            "SELECT telegram_message_ids, kind FROM message_map WHERE bale_chat_id=? AND bale_message_id=?",
            (bale_chat_id, bale_message_id),
        ).fetchone()
        if not row:
            return None
        try:
            ids = [int(x) for x in json.loads(row[0])]
        except Exception:
            ids = []
        return ids, row[1]

    def delete(self, bale_chat_id: str, bale_message_id: str) -> None:
        self.conn.execute(
            "DELETE FROM message_map WHERE bale_chat_id=? AND bale_message_id=?",
            (bale_chat_id, bale_message_id),
        )
        self.conn.commit()

    # -------------------------------------------------------------------- state

    def get_state(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM bot_state WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_state(self, key: str, value: str) -> None:
        self.conn.execute(
            """
            INSERT INTO bot_state (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, value, time.time()),
        )
        self.conn.commit()

    def get_offset(self) -> int | None:
        """Last Bale update offset that was fully processed, so a restart resumes instead of losing posts."""
        raw = self.get_state(OFFSET_KEY)
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def set_offset(self, offset: int) -> None:
        self.set_state(OFFSET_KEY, str(int(offset)))
