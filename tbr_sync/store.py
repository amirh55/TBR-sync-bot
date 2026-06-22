# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path


class MappingStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.conn = sqlite3.connect(path)
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
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

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
