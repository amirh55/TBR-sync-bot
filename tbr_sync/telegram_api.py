# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from pathlib import Path

from telegram import Bot, InputMediaPhoto, InputMediaVideo, Message
from telegram.error import TelegramError

from .config import Config
from .text import bale_markdown_to_telegram_html

log = logging.getLogger(__name__)

MAX_CAPTION = 1024
MAX_TEXT = 4096


class TelegramSender:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.bot = Bot(token=config.telegram_token)

    async def __aenter__(self):
        await self.bot.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.bot.__aexit__(exc_type, exc, tb)

    def format_text(self, text: str | None) -> str:
        return bale_markdown_to_telegram_html(text or "", self.config)

    @staticmethod
    def _ids(result) -> list[int]:
        if result is None:
            return []
        if isinstance(result, (list, tuple)):
            return [m.message_id for m in result if hasattr(m, "message_id")]
        if hasattr(result, "message_id"):
            return [result.message_id]
        return []

    async def _send_text_chunks(self, html_text: str, reply_to_message_id: int | None = None) -> list[int]:
        ids: list[int] = []
        if not html_text:
            return ids
        first = True
        for start in range(0, len(html_text), MAX_TEXT):
            chunk = html_text[start : start + MAX_TEXT]
            msg = await self.bot.send_message(
                self.config.telegram_channel_id,
                chunk,
                parse_mode="HTML",
                reply_to_message_id=reply_to_message_id if first else None,
                allow_sending_without_reply=True,
            )
            ids.append(msg.message_id)
            first = False
        return ids

    async def send_text(self, text: str | None, reply_to_message_id: int | None = None) -> list[int]:
        html_text = self.format_text(text)
        return await self._send_text_chunks(html_text, reply_to_message_id=reply_to_message_id, allow_sending_without_reply=True)

    async def send_contact(self, contact: dict, caption: str | None = None, reply_to_message_id: int | None = None) -> list[int]:
        ids: list[int] = []
        phone = contact.get("phone_number") or contact.get("phoneNumber")
        first_name = contact.get("first_name") or contact.get("firstName") or "Contact"
        last_name = contact.get("last_name") or contact.get("lastName")
        if not phone:
            return await self.send_text(caption, reply_to_message_id=reply_to_message_id, allow_sending_without_reply=True)
        msg = await self.bot.send_contact(
            self.config.telegram_channel_id,
            phone_number=str(phone),
            first_name=str(first_name),
            last_name=last_name,
            reply_to_message_id=reply_to_message_id,
            allow_sending_without_reply=True,
        )
        ids.append(msg.message_id)
        ids.extend(await self.send_text(caption))
        return ids

    async def send_location(self, location: dict, caption: str | None = None, reply_to_message_id: int | None = None) -> list[int]:
        ids: list[int] = []
        lat = location.get("latitude")
        lon = location.get("longitude")
        if lat is None or lon is None:
            return await self.send_text(caption, reply_to_message_id=reply_to_message_id, allow_sending_without_reply=True)
        msg = await self.bot.send_location(
            self.config.telegram_channel_id,
            latitude=float(lat),
            longitude=float(lon),
            reply_to_message_id=reply_to_message_id,
            allow_sending_without_reply=True,
        )
        ids.append(msg.message_id)
        ids.extend(await self.send_text(caption))
        return ids

    async def send_file(self, kind: str, path: Path, text: str | None = None, reply_to_message_id: int | None = None) -> list[int]:
        html_text = self.format_text(text)
        caption = html_text if html_text and len(html_text) <= MAX_CAPTION else None
        extra_text = html_text if html_text and len(html_text) > MAX_CAPTION else ""
        filename = path.name

        sent: Message | None = None
        with path.open("rb") as f:
            if kind == "photo":
                sent = await self.bot.send_photo(self.config.telegram_channel_id, f, caption=caption, parse_mode="HTML" if caption else None, filename=filename, reply_to_message_id=reply_to_message_id, allow_sending_without_reply=True)
            elif kind == "video":
                sent = await self.bot.send_video(self.config.telegram_channel_id, f, caption=caption, parse_mode="HTML" if caption else None, filename=filename, supports_streaming=True, reply_to_message_id=reply_to_message_id, allow_sending_without_reply=True)
            elif kind == "animation":
                sent = await self.bot.send_animation(self.config.telegram_channel_id, f, caption=caption, parse_mode="HTML" if caption else None, filename=filename, reply_to_message_id=reply_to_message_id, allow_sending_without_reply=True)
            elif kind == "audio":
                sent = await self.bot.send_audio(self.config.telegram_channel_id, f, caption=caption, parse_mode="HTML" if caption else None, filename=filename, reply_to_message_id=reply_to_message_id, allow_sending_without_reply=True)
            elif kind == "voice":
                sent = await self.bot.send_voice(self.config.telegram_channel_id, f, caption=caption, parse_mode="HTML" if caption else None, filename=filename, reply_to_message_id=reply_to_message_id, allow_sending_without_reply=True)
            elif kind == "sticker":
                try:
                    sent = await self.bot.send_sticker(self.config.telegram_channel_id, f, reply_to_message_id=reply_to_message_id, allow_sending_without_reply=True)
                except TelegramError:
                    f.seek(0)
                    sent = await self.bot.send_document(self.config.telegram_channel_id, f, caption=caption, parse_mode="HTML" if caption else None, filename=filename, reply_to_message_id=reply_to_message_id, allow_sending_without_reply=True)
            else:
                sent = await self.bot.send_document(self.config.telegram_channel_id, f, caption=caption, parse_mode="HTML" if caption else None, filename=filename, reply_to_message_id=reply_to_message_id, allow_sending_without_reply=True)

        ids = self._ids(sent)
        ids.extend(await self._send_text_chunks(extra_text))
        return ids

    async def send_media_group(self, items: list[tuple[str, Path]], text: str | None = None, reply_to_message_id: int | None = None) -> list[int]:
        if not items:
            return await self.send_text(text, reply_to_message_id=reply_to_message_id, allow_sending_without_reply=True)
        if len(items) == 1:
            return await self.send_file(items[0][0], items[0][1], text, reply_to_message_id=reply_to_message_id, allow_sending_without_reply=True)

        # Telegram albums can mix photo/video. Other kinds are sent separately.
        album_items = [(kind, path) for kind, path in items if kind in {"photo", "video"}]
        other_items = [(kind, path) for kind, path in items if kind not in {"photo", "video"}]
        ids: list[int] = []

        if album_items:
            html_text = self.format_text(text)
            caption = html_text if html_text and len(html_text) <= MAX_CAPTION else None
            extra_text = html_text if html_text and len(html_text) > MAX_CAPTION else ""
            opened = []
            media = []
            try:
                for index, (kind, path) in enumerate(album_items):
                    f = path.open("rb")
                    opened.append(f)
                    item_caption = caption if index == 0 else None
                    if kind == "photo":
                        media.append(InputMediaPhoto(media=f, caption=item_caption, parse_mode="HTML" if item_caption else None, filename=path.name))
                    else:
                        media.append(InputMediaVideo(media=f, caption=item_caption, parse_mode="HTML" if item_caption else None, filename=path.name, supports_streaming=True))
                result = await self.bot.send_media_group(
                    self.config.telegram_channel_id,
                    media=media,
                    reply_to_message_id=reply_to_message_id,
                    allow_sending_without_reply=True,
                )
                ids.extend(self._ids(result))
                ids.extend(await self._send_text_chunks(extra_text))
            finally:
                for f in opened:
                    try:
                        f.close()
                    except Exception:
                        pass

        for index, (kind, path) in enumerate(other_items):
            reply_for_other = reply_to_message_id if not ids else None
            ids.extend(await self.send_file(kind, path, text if not ids and index == 0 else "", reply_to_message_id=reply_for_other))
        return ids

    async def edit_existing(self, telegram_message_ids: list[int], new_text: str | None) -> bool:
        if not telegram_message_ids:
            return False
        html_text = self.format_text(new_text)
        if not html_text:
            return False
        first_id = telegram_message_ids[0]
        try:
            await self.bot.edit_message_text(
                chat_id=self.config.telegram_channel_id,
                message_id=first_id,
                text=html_text[:MAX_TEXT],
                parse_mode="HTML",
            )
            # Remove extra text chunks from the old version when possible.
            for mid in telegram_message_ids[1:]:
                try:
                    await self.bot.delete_message(self.config.telegram_channel_id, mid)
                except TelegramError:
                    pass
            return True
        except TelegramError as exc:
            log.warning("Could not edit Telegram message %s; will resend. Error: %s", first_id, exc)
            return False

    async def delete_messages(self, telegram_message_ids: list[int]) -> None:
        for mid in telegram_message_ids:
            try:
                await self.bot.delete_message(self.config.telegram_channel_id, mid)
            except TelegramError as exc:
                log.warning("Could not delete Telegram message %s: %s", mid, exc)
