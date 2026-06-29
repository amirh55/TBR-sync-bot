# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from telegram.error import TelegramError

from .bale_api import BaleClient
from .config import Config
from .media import MediaItem, detect_kind_from_file, extension_for, extension_for_detected, extract_media
from .store import MappingStore
from .telegram_api import TelegramSender

log = logging.getLogger(__name__)


def _chat_id(message: dict) -> str:
    chat = message.get("chat") or {}
    return str(chat.get("id") or chat.get("username") or "")


def _message_id(message: dict) -> str:
    return str(message.get("message_id") or message.get("messageId") or message.get("id") or "")


def _source_key(message: dict) -> tuple[str, str]:
    return _chat_id(message), _message_id(message)


def _normalize_username(value: object) -> str:
    text = str(value or "").strip().lower()
    return text[1:] if text.startswith("@") else text


def _is_source_channel(message: dict, config: Config) -> bool:
    chat = message.get("chat") or {}
    expected = (config.bale_channel_id or "").strip()
    expected_user = _normalize_username(expected)
    username = _normalize_username(chat.get("username"))
    chat_id = str(chat.get("id") or "").strip()
    chat_type = str(chat.get("type") or "").strip().lower()

    # Public channels are best matched by username. This works even if Bale reports
    # the chat type differently across message/channel_post updates.
    if expected.startswith("@"):
        if username and username == expected_user:
            return True
        return False

    # Numeric source id is supported for private channels or responses without username.
    return bool(expected and chat_id == expected)


def _is_bot_message(message: dict) -> bool:
    user = message.get("from") or message.get("from_user") or {}
    return bool(isinstance(user, dict) and user.get("is_bot"))


def _caption_or_text(message: dict) -> str:
    return str(message.get("text") or message.get("caption") or "")


def _media_group_id(message: dict) -> str | None:
    for name in ("media_group_id", "mediaGroupId", "album_id", "grouped_id", "group_id"):
        value = message.get(name)
        if value not in (None, ""):
            return str(value)
    return None


def _reply_source(message: dict) -> tuple[str, str] | None:
    """Return (bale_chat_id, bale_message_id) of the message this one replies to, if any."""
    for key in ("reply_to_message", "replyToMessage", "reply_to", "replyTo"):
        reply = message.get(key)
        if isinstance(reply, dict):
            chat_id, msg_id = _source_key(reply)
            if not chat_id:
                # Replies usually point at the same chat as the parent message.
                chat = message.get("chat") or {}
                chat_id = str(chat.get("id") or chat.get("username") or "")
            if chat_id and msg_id:
                return chat_id, msg_id
    return None


def _deleted_payload(update: dict) -> dict | None:
    # Bale docs do not list a delete update type, but support common defensive names.
    for key in (
        "deleted_message",
        "delete_message",
        "message_deleted",
        "deleted_channel_post",
        "channel_post_deleted",
        "deleted_post",
    ):
        value = update.get(key)
        if isinstance(value, dict):
            return value
    return None


class Syncer:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.store = MappingStore(config.state_db)
        self.pending_groups: dict[str, dict[str, Any]] = {}

    async def run(self) -> None:
        log.info("TBR sync bot v14 started.")
        log.info("Bale source channel: %s", self.config.bale_channel_id)
        log.info("Telegram destination channel: %s", self.config.telegram_channel_id)
        log.info("State DB: %s", self.config.state_db)

        bale = BaleClient(self.config)
        try:
            await bale.delete_webhook()
            me = await bale.get_me()
            log.info("Connected to Bale. Bot username: @%s", me.get("username", "unknown"))

            async with TelegramSender(self.config) as telegram:
                offset = await bale.skip_pending_updates()
                while True:
                    try:
                        updates = await bale.get_updates(offset)
                        if not updates:
                            await asyncio.sleep(0.2)
                            continue

                        for update in updates:
                            update_id = update.get("update_id")
                            await self.handle_update(bale, telegram, update)
                            if isinstance(update_id, int):
                                offset = update_id + 1
                    except Exception as exc:
                        log.exception("Main loop error: %s", exc)
                        await asyncio.sleep(5)
        finally:
            await bale.close()
            self.store.close()

    async def handle_update(self, bale: BaleClient, telegram: TelegramSender, update: dict) -> None:
        # Bale raw Bot API may deliver channel posts as channel_post instead of message.
        # Support both forms so public/test channels work reliably.
        for key in ("message", "channel_post", "post"):
            message = update.get(key)
            if isinstance(message, dict):
                await self.handle_new_message(bale, telegram, message, source_key=key)
                return

        for key in ("edited_message", "edited_channel_post", "edited_post"):
            edited = update.get(key)
            if isinstance(edited, dict):
                await self.handle_edited_message(bale, telegram, edited, source_key=key)
                return

        deleted = _deleted_payload(update)
        if deleted:
            await self.handle_deleted_message(telegram, deleted)
            return

        keys = ",".join(sorted(update.keys()))
        if self.config.log_ignored_updates:
            log.info("Ignored Bale update. keys=%s raw=%s", keys, json.dumps(update, ensure_ascii=False, default=str)[:1200])
        else:
            log.debug("Ignored non-message update. keys=%s", keys)

    async def _download_items(self, bale: BaleClient, items: list[MediaItem]) -> list[tuple[str, Path]]:
        downloaded: list[tuple[str, Path]] = []
        for item in items:
            ext = extension_for(item)
            tmp = self.config.temp_dir / f"{item.kind}_{uuid.uuid4().hex}{ext}"
            try:
                path = await bale.download_file(item.file_id, tmp)
                kind = detect_kind_from_file(path, item.kind)
                target_ext = extension_for_detected(kind, path)
                if target_ext and path.suffix.lower() != target_ext.lower():
                    renamed = path.with_suffix(target_ext)
                    try:
                        path.rename(renamed)
                        path = renamed
                    except Exception as rename_exc:
                        log.debug("Could not rename %s to %s: %s", path, renamed, rename_exc)
                downloaded.append((kind, path))
            except Exception as exc:
                log.warning("Could not download Bale file kind=%s file_id=%s: %s", item.kind, item.file_id, exc)
                try:
                    if tmp.exists():
                        tmp.unlink()
                except Exception:
                    pass
        return downloaded

    def _cleanup(self, paths: list[tuple[str, Path]]) -> None:
        for _, path in paths:
            try:
                if path.exists():
                    path.unlink()
            except Exception as exc:
                log.warning("Could not delete temp file %s: %s", path, exc)

    def _reply_target(self, message: dict) -> int | None:
        """Find the Telegram message_id to reply to, based on the Bale reply_to_message."""
        reply_src = _reply_source(message)
        if not reply_src:
            return None
        mapping = self.store.get(reply_src[0], reply_src[1])
        if not mapping:
            log.info("Reply target not found in mapping for Bale message %s", reply_src[1])
            return None
        telegram_ids, _ = mapping
        return telegram_ids[0] if telegram_ids else None

    async def _send_message_now(self, bale: BaleClient, telegram: TelegramSender, message: dict) -> list[int]:
        text = _caption_or_text(message)
        media_items = extract_media(message, self.config)
        contact = message.get("contact")
        location = message.get("location")
        reply_to = self._reply_target(message)

        if self.config.debug_media:
            log.info(
                "Bale message_id=%s keys=%s media=%s reply_to=%s",
                _message_id(message),
                sorted(message.keys()),
                [(m.kind, m.file_id, m.mime_type, m.file_name) for m in media_items],
                reply_to,
            )

        if media_items:
            downloaded = await self._download_items(bale, media_items)
            try:
                if downloaded:
                    return await telegram.send_media_group(downloaded, text, reply_to_message_id=reply_to)
                if text:
                    return await telegram.send_text(text, reply_to_message_id=reply_to)
                return []
            finally:
                self._cleanup(downloaded)

        if isinstance(contact, dict):
            return await telegram.send_contact(contact, text, reply_to_message_id=reply_to)

        if isinstance(location, dict):
            return await telegram.send_location(location, text, reply_to_message_id=reply_to)

        if text:
            return await telegram.send_text(text, reply_to_message_id=reply_to)

        if self.config.fallback_send_unsupported_as_text:
            return await telegram.send_text("Unsupported Bale message was received and skipped.", reply_to_message_id=reply_to)

        keys = sorted(message.keys())
        log.warning("Unsupported/empty Bale post was skipped. message_id=%s keys=%s", _message_id(message), keys)
        if self.config.log_unsupported_json:
            with open("unsupported_updates.log", "a", encoding="utf-8") as f:
                f.write(json.dumps(message, ensure_ascii=False, default=str) + "\n")
        return []

    async def handle_new_message(self, bale: BaleClient, telegram: TelegramSender, message: dict, source_key: str = "message") -> None:
        if not _is_source_channel(message, self.config):
            if self.config.log_ignored_updates:
                chat = message.get("chat") or {}
                log.info(
                    "Ignored Bale %s from another chat. expected=%s chat_id=%s username=%s type=%s",
                    source_key,
                    self.config.bale_channel_id,
                    chat.get("id"),
                    chat.get("username"),
                    chat.get("type"),
                )
            return
        if _is_bot_message(message):
            return

        group_id = _media_group_id(message)
        media_items = extract_media(message, self.config)
        if group_id and media_items:
            await self._buffer_media_group(bale, telegram, message, media_items, group_id)
            return

        log.info("New Bale %s accepted. Forwarding...", source_key)
        ids = await self._send_message_now(bale, telegram, message)
        if ids:
            chat_id, msg_id = _source_key(message)
            self.store.save(chat_id, msg_id, ids, "message")
            log.info("Forwarded Bale message %s to Telegram ids=%s", msg_id, ids)
        else:
            log.warning("Accepted Bale message %s produced no Telegram messages.", _message_id(message))

    async def _buffer_media_group(
        self, bale: BaleClient, telegram: TelegramSender, message: dict, media_items: list[MediaItem], group_id: str
    ) -> None:
        chat_id, msg_id = _source_key(message)
        key = f"{chat_id}:{group_id}"
        group = self.pending_groups.setdefault(
            key,
            {"entries": [], "caption": "", "task": None, "bale": bale, "telegram": telegram, "reply_to": None},
        )
        if _caption_or_text(message) and not group["caption"]:
            group["caption"] = _caption_or_text(message)
        if group.get("reply_to") is None:
            reply_to = self._reply_target(message)
            if reply_to is not None:
                group["reply_to"] = reply_to
        group["entries"].append({"source": (chat_id, msg_id), "items": media_items})

        task = group.get("task")
        if task and not task.done():
            task.cancel()
        group["task"] = asyncio.create_task(self._flush_media_group_later(key))

    async def _flush_media_group_later(self, key: str) -> None:
        await asyncio.sleep(self.config.media_group_wait_seconds)
        group = self.pending_groups.pop(key, None)
        if not group:
            return

        all_media: list[MediaItem] = []
        source_for_each_item: list[tuple[str, str]] = []
        for entry in group["entries"]:
            for item in entry["items"]:
                all_media.append(item)
                source_for_each_item.append(entry["source"])

        downloaded = await self._download_items(group["bale"], all_media)
        try:
            ids = await group["telegram"].send_media_group(downloaded, group["caption"], reply_to_message_id=group.get("reply_to"))
            if ids:
                by_source: dict[tuple[str, str], list[int]] = defaultdict(list)
                if len(ids) == len(source_for_each_item):
                    for source, tg_id in zip(source_for_each_item, ids):
                        by_source[source].append(tg_id)
                else:
                    for source in set(source_for_each_item):
                        by_source[source] = ids
                for (chat_id, msg_id), mapped_ids in by_source.items():
                    self.store.save(chat_id, msg_id, mapped_ids, "media_group")
                log.info("Forwarded Bale media group %s to Telegram ids=%s", key, ids)
            else:
                log.warning("Media group %s had no sent Telegram messages.", key)
        finally:
            self._cleanup(downloaded)

    async def handle_edited_message(self, bale: BaleClient, telegram: TelegramSender, message: dict, source_key: str = "edited_message") -> None:
        if not _is_source_channel(message, self.config):
            if self.config.log_ignored_updates:
                chat = message.get("chat") or {}
                log.info(
                    "Ignored Bale %s from another chat. expected=%s chat_id=%s username=%s type=%s",
                    source_key,
                    self.config.bale_channel_id,
                    chat.get("id"),
                    chat.get("username"),
                    chat.get("type"),
                )
            return

        chat_id, msg_id = _source_key(message)
        mapping = self.store.get(chat_id, msg_id)
        if not mapping:
            log.info("Edited Bale message %s has no Telegram mapping; forwarding as new.", msg_id)
            ids = await self._send_message_now(bale, telegram, message)
            if ids:
                self.store.save(chat_id, msg_id, ids, "message")
            return

        telegram_ids, old_kind = mapping
        media_items = extract_media(message, self.config)
        contact = message.get("contact")
        location = message.get("location")
        text = _caption_or_text(message)

        if not media_items and not contact and not location and text:
            edited = await telegram.edit_existing(telegram_ids, text)
            if edited:
                self.store.save(chat_id, msg_id, [telegram_ids[0]], "message")
                log.info("Edited Telegram message for Bale message %s", msg_id)
                return

        # For media/caption changes, safer approach is delete old Telegram copy and resend the current Bale post.
        await telegram.delete_messages(telegram_ids)
        self.store.delete(chat_id, msg_id)
        ids = await self._send_message_now(bale, telegram, message)
        if ids:
            self.store.save(chat_id, msg_id, ids, old_kind or "message")
            log.info("Replaced Telegram copy for edited Bale message %s", msg_id)

    async def handle_deleted_message(self, telegram: TelegramSender, payload: dict) -> None:
        chat = payload.get("chat") or {}
        chat_id = str(chat.get("id") or payload.get("chat_id") or payload.get("chatId") or "")
        msg_id = str(payload.get("message_id") or payload.get("messageId") or payload.get("id") or "")
        if not chat_id or not msg_id:
            log.warning("Delete update did not include chat/message id. keys=%s", sorted(payload.keys()))
            return

        mapping = self.store.get(chat_id, msg_id)
        if not mapping:
            log.info("Delete update for Bale message %s has no Telegram mapping.", msg_id)
            return

        telegram_ids, _ = mapping
        await telegram.delete_messages(telegram_ids)
        self.store.delete(chat_id, msg_id)
        log.info("Deleted Telegram messages %s for deleted Bale message %s", telegram_ids, msg_id)
