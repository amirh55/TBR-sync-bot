# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Awaitable, Callable, TypeVar

from telegram import Bot, InputMediaPhoto, InputMediaVideo, Message
from telegram.error import BadRequest, Forbidden, InvalidToken, NetworkError, RetryAfter, TelegramError, TimedOut

from .config import Config
from .text import bale_markdown_to_telegram_html, split_plain_text

log = logging.getLogger(__name__)

MAX_CAPTION = 1024
MAX_TEXT = 4096
MAX_ALBUM_ITEMS = 10
# Worst-case HTML escaping expands a character ~5x (& -> &amp;), so splitting the
# plain text at this limit guarantees the rendered chunk still fits in MAX_TEXT.
SAFE_PLAIN_LIMIT = MAX_TEXT // 6

T = TypeVar("T")


def _album_batches(items: list[tuple[str, Path]]) -> list[list[tuple[str, Path]]]:
    """Split an album into Telegram-sized batches, never leaving a batch of one.

    Telegram accepts 2..10 items per sendMediaGroup call, so 11 items become 6+5
    rather than 10+1 (which the API would reject).
    """
    if len(items) <= MAX_ALBUM_ITEMS:
        return [list(items)]
    batches = [list(items[i : i + MAX_ALBUM_ITEMS]) for i in range(0, len(items), MAX_ALBUM_ITEMS)]
    if len(batches[-1]) == 1:
        batches[-1].insert(0, batches[-2].pop())
    return batches


class TelegramSender:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.bot = Bot(token=config.telegram_token)

    async def __aenter__(self):
        await self.bot.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.bot.__aexit__(exc_type, exc, tb)

    # ------------------------------------------------------------------ helpers

    async def _retry(self, description: str, action: Callable[[], Awaitable[T]]) -> T:
        """Run a Telegram call, honouring flood control and retrying network blips.

        `action` must open its own file handles: a retried upload has to start
        reading the file from the beginning again.
        """
        attempts = max(1, self.config.telegram_max_retries)
        backoff = 1.0
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                return await action()
            except RetryAfter as exc:
                wait = float(getattr(exc, "retry_after", 0) or backoff) + 0.5
                last_exc = exc
                log.warning(
                    "Telegram flood control on %s; waiting %.1fs (attempt %s/%s).", description, wait, attempt, attempts
                )
                await asyncio.sleep(wait)
            except (BadRequest, Forbidden, InvalidToken):
                # In python-telegram-bot BadRequest subclasses NetworkError, but a
                # malformed request will never succeed on retry. Fail fast.
                raise
            except (TimedOut, NetworkError) as exc:
                last_exc = exc
                if attempt >= attempts:
                    break
                log.warning(
                    "Telegram network error on %s: %s; retrying in %.1fs (attempt %s/%s).",
                    description,
                    exc,
                    backoff,
                    attempt,
                    attempts,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

        raise last_exc if last_exc else TelegramError(f"{description} failed after {attempts} attempts")

    def format_text(self, text: str | None) -> str:
        return bale_markdown_to_telegram_html(text or "", self.config)

    def render_chunks(self, text: str | None) -> list[str]:
        """Turn raw Bale text into HTML pieces that each fit inside one Telegram message."""
        raw = (text or "").strip()
        if not raw:
            return []

        chunks: list[str] = []
        for plain in split_plain_text(raw, MAX_TEXT):
            rendered = self.format_text(plain)
            if not rendered:
                continue
            if len(rendered) <= MAX_TEXT:
                chunks.append(rendered)
                continue
            # Escaping pushed this piece over the limit; re-split conservatively.
            for sub in split_plain_text(plain, SAFE_PLAIN_LIMIT):
                sub_rendered = self.format_text(sub)
                if sub_rendered:
                    chunks.append(sub_rendered[:MAX_TEXT])
        return chunks

    def _caption_and_rest(self, text: str | None) -> tuple[str | None, list[str]]:
        """Use the text as a media caption when it fits; otherwise send it as follow-up messages."""
        chunks = self.render_chunks(text)
        if len(chunks) == 1 and len(chunks[0]) <= MAX_CAPTION:
            return chunks[0], []
        return None, chunks

    @staticmethod
    def _ids(result) -> list[int]:
        if result is None:
            return []
        if isinstance(result, (list, tuple)):
            return [m.message_id for m in result if hasattr(m, "message_id")]
        if hasattr(result, "message_id"):
            return [result.message_id]
        return []

    async def _send_html_chunks(self, chunks: list[str], reply_to_message_id: int | None = None) -> list[int]:
        ids: list[int] = []
        first = True
        for chunk in chunks:
            reply_for_chunk = reply_to_message_id if first else None
            msg = await self._retry(
                "send_message",
                lambda c=chunk, r=reply_for_chunk: self.bot.send_message(
                    self.config.telegram_channel_id,
                    c,
                    parse_mode="HTML",
                    reply_to_message_id=r,
                    allow_sending_without_reply=True,
                ),
            )
            ids.append(msg.message_id)
            first = False
        return ids

    # -------------------------------------------------------------------- send

    async def send_text(self, text: str | None, reply_to_message_id: int | None = None) -> list[int]:
        return await self._send_html_chunks(self.render_chunks(text), reply_to_message_id=reply_to_message_id)

    async def send_contact(self, contact: dict, caption: str | None = None, reply_to_message_id: int | None = None) -> list[int]:
        phone = contact.get("phone_number") or contact.get("phoneNumber")
        first_name = contact.get("first_name") or contact.get("firstName") or "Contact"
        last_name = contact.get("last_name") or contact.get("lastName")
        if not phone:
            return await self.send_text(caption, reply_to_message_id=reply_to_message_id)

        msg = await self._retry(
            "send_contact",
            lambda: self.bot.send_contact(
                self.config.telegram_channel_id,
                phone_number=str(phone),
                first_name=str(first_name),
                last_name=last_name,
                reply_to_message_id=reply_to_message_id,
                allow_sending_without_reply=True,
            ),
        )
        ids = [msg.message_id]
        ids.extend(await self.send_text(caption))
        return ids

    async def send_location(self, location: dict, caption: str | None = None, reply_to_message_id: int | None = None) -> list[int]:
        lat = location.get("latitude")
        lon = location.get("longitude")
        if lat is None or lon is None:
            return await self.send_text(caption, reply_to_message_id=reply_to_message_id)

        msg = await self._retry(
            "send_location",
            lambda: self.bot.send_location(
                self.config.telegram_channel_id,
                latitude=float(lat),
                longitude=float(lon),
                reply_to_message_id=reply_to_message_id,
                allow_sending_without_reply=True,
            ),
        )
        ids = [msg.message_id]
        ids.extend(await self.send_text(caption))
        return ids

    async def _send_one_file(self, kind: str, path: Path, caption: str | None, reply_to_message_id: int | None) -> Message | None:
        parse_mode = "HTML" if caption else None
        common = dict(
            caption=caption,
            parse_mode=parse_mode,
            filename=path.name,
            reply_to_message_id=reply_to_message_id,
            allow_sending_without_reply=True,
        )
        chat = self.config.telegram_channel_id

        with path.open("rb") as f:
            if kind == "photo":
                return await self.bot.send_photo(chat, f, **common)
            if kind == "video":
                return await self.bot.send_video(chat, f, supports_streaming=True, **common)
            if kind == "animation":
                return await self.bot.send_animation(chat, f, **common)
            if kind == "audio":
                return await self.bot.send_audio(chat, f, **common)
            if kind == "voice":
                return await self.bot.send_voice(chat, f, **common)
            if kind == "sticker":
                try:
                    return await self.bot.send_sticker(
                        chat, f, reply_to_message_id=reply_to_message_id, allow_sending_without_reply=True
                    )
                except TelegramError:
                    f.seek(0)
                    return await self.bot.send_document(chat, f, **common)
            return await self.bot.send_document(chat, f, **common)

    async def send_file(self, kind: str, path: Path, text: str | None = None, reply_to_message_id: int | None = None) -> list[int]:
        caption, extra_chunks = self._caption_and_rest(text)
        sent = await self._retry(
            f"send {kind}",
            lambda: self._send_one_file(kind, path, caption, reply_to_message_id),
        )
        ids = self._ids(sent)
        ids.extend(await self._send_html_chunks(extra_chunks))
        return ids

    async def _send_album_batch(
        self, batch: list[tuple[str, Path]], caption: str | None, reply_to_message_id: int | None
    ) -> object:
        opened = []
        media = []
        try:
            for index, (kind, path) in enumerate(batch):
                f = path.open("rb")
                opened.append(f)
                item_caption = caption if index == 0 else None
                item_parse_mode = "HTML" if item_caption else None
                if kind == "photo":
                    media.append(InputMediaPhoto(media=f, caption=item_caption, parse_mode=item_parse_mode, filename=path.name))
                else:
                    media.append(
                        InputMediaVideo(
                            media=f,
                            caption=item_caption,
                            parse_mode=item_parse_mode,
                            filename=path.name,
                            supports_streaming=True,
                        )
                    )
            return await self.bot.send_media_group(
                self.config.telegram_channel_id,
                media=media,
                reply_to_message_id=reply_to_message_id,
                allow_sending_without_reply=True,
            )
        finally:
            for f in opened:
                try:
                    f.close()
                except Exception:
                    pass

    async def send_media_group(
        self, items: list[tuple[str, Path]], text: str | None = None, reply_to_message_id: int | None = None
    ) -> list[int]:
        if not items:
            return await self.send_text(text, reply_to_message_id=reply_to_message_id)
        if len(items) == 1:
            return await self.send_file(items[0][0], items[0][1], text, reply_to_message_id=reply_to_message_id)

        # Telegram albums can mix photo/video. Other kinds are sent separately.
        album_items = [(kind, path) for kind, path in items if kind in {"photo", "video"}]
        other_items = [(kind, path) for kind, path in items if kind not in {"photo", "video"}]

        caption, extra_chunks = self._caption_and_rest(text)
        ids: list[int] = []
        caption_used = False

        if album_items:
            for index, batch in enumerate(_album_batches(album_items)):
                batch_caption = caption if index == 0 else None
                reply_for_batch = reply_to_message_id if index == 0 else None
                if len(batch) == 1:
                    ids.extend(await self.send_file(batch[0][0], batch[0][1], None, reply_to_message_id=reply_for_batch))
                else:
                    result = await self._retry(
                        "send_media_group",
                        lambda b=batch, c=batch_caption, r=reply_for_batch: self._send_album_batch(b, c, r),
                    )
                    ids.extend(self._ids(result))
                if batch_caption:
                    caption_used = True
            ids.extend(await self._send_html_chunks(extra_chunks))
            extra_chunks = []

        for index, (kind, path) in enumerate(other_items):
            reply_for_other = reply_to_message_id if not ids else None
            # Only attach the caption here if the album did not already carry it.
            attach = text if (not caption_used and index == 0 and not ids) else None
            ids.extend(await self.send_file(kind, path, attach, reply_to_message_id=reply_for_other))
            if attach:
                extra_chunks = []

        ids.extend(await self._send_html_chunks(extra_chunks))
        return ids

    # ------------------------------------------------------------ edit / delete

    async def edit_existing(self, telegram_message_ids: list[int], new_text: str | None) -> list[int]:
        """Edit the existing Telegram copy in place. Returns the new id list, or [] if the edit failed."""
        if not telegram_message_ids:
            return []
        chunks = self.render_chunks(new_text)
        if not chunks:
            return []

        first_id = telegram_message_ids[0]
        try:
            await self._retry(
                "edit_message_text",
                lambda: self.bot.edit_message_text(
                    chat_id=self.config.telegram_channel_id,
                    message_id=first_id,
                    text=chunks[0],
                    parse_mode="HTML",
                ),
            )
        except TelegramError as exc:
            log.warning("Could not edit Telegram message %s; will resend. Error: %s", first_id, exc)
            return []

        # Remove extra text chunks from the old version when possible.
        for mid in telegram_message_ids[1:]:
            try:
                await self.bot.delete_message(self.config.telegram_channel_id, mid)
            except TelegramError:
                pass

        ids = [first_id]
        # The edited text no longer fits in one message; append the remainder.
        if len(chunks) > 1:
            ids.extend(await self._send_html_chunks(chunks[1:]))
        return ids

    async def delete_messages(self, telegram_message_ids: list[int]) -> None:
        for mid in telegram_message_ids:
            try:
                await self._retry(
                    "delete_message",
                    lambda m=mid: self.bot.delete_message(self.config.telegram_channel_id, m),
                )
            except TelegramError as exc:
                log.warning("Could not delete Telegram message %s: %s", mid, exc)
