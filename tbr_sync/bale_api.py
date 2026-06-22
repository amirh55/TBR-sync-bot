# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

import httpx

from .config import Config

log = logging.getLogger(__name__)


class BaleApiError(RuntimeError):
    pass


class BaleClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.api_base = f"https://tapi.bale.ai/bot{config.bale_token}"
        self.file_base = f"https://tapi.bale.ai/file/bot{config.bale_token}"
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(config.poll_timeout + 10, connect=15))

    async def close(self) -> None:
        await self.client.aclose()

    async def request(self, method: str, data: dict | None = None) -> object:
        url = f"{self.api_base}/{method}"
        response = await self.client.post(url, data=data or {})
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise BaleApiError(f"Bale {method} failed: {payload.get('description') or payload}")
        return payload.get("result")

    async def get_me(self) -> dict:
        result = await self.request("getMe")
        return result if isinstance(result, dict) else {}

    async def delete_webhook(self) -> None:
        try:
            await self.request("deleteWebhook")
        except Exception as exc:
            log.warning("Could not delete Bale webhook; continuing with polling: %s", exc)

    async def get_updates(self, offset: int | None) -> list[dict]:
        data: dict[str, str | int] = {
            "timeout": self.config.poll_timeout,
            "limit": self.config.poll_limit,
        }
        if offset is not None:
            data["offset"] = offset
        result = await self.request("getUpdates", data)
        return result if isinstance(result, list) else []

    async def skip_pending_updates(self) -> int | None:
        if self.config.sync_old_messages:
            log.info("sync_old_messages=true; old pending updates will be processed.")
            return None

        updates = await self.get_updates(offset=-1)
        if not updates:
            log.info("Pending update queue is empty. Listening for new posts only.")
            return None

        update_ids = [u.get("update_id") for u in updates if isinstance(u.get("update_id"), int)]
        if not update_ids:
            return None

        next_offset = max(update_ids) + 1
        log.info("Old pending updates skipped. next_offset=%s", next_offset)
        return next_offset

    async def get_file(self, file_id: str) -> dict:
        result = await self.request("getFile", {"file_id": file_id})
        return result if isinstance(result, dict) else {}

    async def download_file(self, file_id: str, destination: Path) -> Path:
        info = await self.get_file(file_id)
        file_path = info.get("file_path")
        if not file_path:
            raise BaleApiError(f"getFile returned no file_path for file_id={file_id}")

        url = f"{self.file_base}/{quote(str(file_path))}"
        response = await self.client.get(url)
        response.raise_for_status()
        destination.write_bytes(response.content)
        return destination
