# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import logging
import signal
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import __version__
from .bale_api import BaleClient, FileTooLargeError
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
        self.source_ids: set[str] = set()
        self.source_usernames: set[str] = set()
        self._group_tasks: set[asyncio.Task] = set()
        self._stopping = asyncio.Event()

    # --------------------------------------------------------------- lifecycle

    def request_stop(self, reason: str = "") -> None:
        if not self._stopping.is_set():
            log.info("Shutdown requested%s. Finishing pending work...", f" ({reason})" if reason else "")
            self._stopping.set()

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for name in ("SIGTERM", "SIGINT"):
            sig = getattr(signal, name, None)
            if sig is None:
                continue
            try:
                loop.add_signal_handler(sig, self.request_stop, name)
            except (NotImplementedError, RuntimeError):
                # Windows does not support add_signal_handler for these.
                pass

    async def _resolve_source_chat(self, bale: BaleClient) -> None:
        """Learn every identifier the source channel can appear under.

        Bale does not always include `username` on channel_post updates, so a
        config that uses @name must also know the numeric id or posts get dropped.
        """
        expected = (self.config.bale_channel_id or "").strip()
        if not expected:
            return
        if expected.startswith("@"):
            self.source_usernames.add(_normalize_username(expected))
        else:
            self.source_ids.add(expected)

        try:
            chat = await bale.get_chat(expected)
        except Exception as exc:
            log.warning("Could not resolve Bale source chat %s via getChat: %s", expected, exc)
            return

        chat_id = str(chat.get("id") or "").strip()
        username = _normalize_username(chat.get("username"))
        if chat_id:
            self.source_ids.add(chat_id)
        if username:
            self.source_usernames.add(username)
        log.info("Bale source chat resolved. ids=%s usernames=%s", sorted(self.source_ids), sorted(self.source_usernames))

    async def _initial_offset(self, bale: BaleClient) -> int | None:
        stored = self.store.get_offset()
        if stored is not None:
            log.info("Resuming from stored Bale update offset %s.", stored)
            return stored
        offset = await bale.skip_pending_updates()
        if offset is not None:
            self.store.set_offset(offset)
        return offset

    async def run(self) -> None:
        log.info("TBR sync bot v%s started.", __version__)
        log.info("Bale source channel: %s", self.config.bale_channel_id)
        log.info("Telegram destination channel: %s", self.config.telegram_channel_id)
        log.info("State DB: %s", self.config.state_db)

        self._install_signal_handlers()
        bale = BaleClient(self.config)
        try:
            await bale.delete_webhook()
            me = await bale.get_me()
            log.info("Connected to Bale. Bot username: @%s", me.get("username", "unknown"))
            await self._resolve_source_chat(bale)

            async with TelegramSender(self.config) as telegram:
                offset = await self._initial_offset(bale)

                while not self._stopping.is_set():
                    try:
                        updates = await bale.get_updates(offset)
                    except Exception as exc:
                        log.warning("Could not fetch Bale updates: %s", exc)
                        await asyncio.sleep(5)
                        continue

                    if not updates:
                        await asyncio.sleep(0.2)
                        continue

                    for update in updates:
                        update_id = update.get("update_id")
                        try:
                            await self.handle_update(bale, telegram, update)
                        except Exception:
                            # A single bad update must never block the queue forever.
                            log.exception("Failed to process Bale update %s; skipping it.", update_id)
                        finally:
                            if isinstance(update_id, int):
                                offset = update_id + 1
                                self.store.set_offset(offset)

                await self._flush_all_pending()
                log.info("Shutdown complete.")
        finally:
            await bale.close()
            self.store.close()

    # ------------------------------------------------------------- dispatching

    def _is_source_channel(self, message: dict) -> bool:
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id") or "").strip()
        username = _normalize_username(chat.get("username"))
        if chat_id and chat_id in self.source_ids:
            return True
        return bool(username and username in self.source_usernames)

    def _log_wrong_chat(self, source_key: str, message: dict) -> None:
        if not self.config.log_ignored_updates:
            return
        chat = message.get("chat") or {}
        log.info(
            "Ignored Bale %s from another chat. expected=%s chat_id=%s username=%s type=%s",
            source_key,
            self.config.bale_channel_id,
            chat.get("id"),
            chat.get("username"),
            chat.get("type"),
        )

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

    # ------------------------------------------------------------------ media

    async def _download_items(self, bale: BaleClient, items: list[MediaItem]) -> tuple[list[tuple[str, Path]], int]:
        """Download media to temp files. Returns (downloaded, skipped_count)."""
        downloaded: list[tuple[str, Path]] = []
        skipped = 0
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
            except FileTooLargeError as exc:
                skipped += 1
                log.warning("Skipped oversized Bale file kind=%s: %s", item.kind, exc)
            except Exception as exc:
                skipped += 1
                log.warning("Could not download Bale file kind=%s file_id=%s: %s", item.kind, item.file_id, exc)
            finally:
                try:
                    if tmp.exists() and not any(tmp == p for _, p in downloaded):
                        tmp.unlink()
                except Exception:
                    pass
        return downloaded, skipped

    def _with_skip_notice(self, text: str, skipped: int) -> str:
        if skipped <= 0 or not self.config.skipped_file_notice:
            return text
        try:
            notice = self.config.skipped_file_notice.format(count=skipped)
        except (KeyError, IndexError):
            notice = self.config.skipped_file_notice
        return f"{text}\n\n{notice}" if text else notice

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
            downloaded, skipped = await self._download_items(bale, media_items)
            caption = self._with_skip_notice(text, skipped)
            try:
                if downloaded:
                    return await telegram.send_media_group(downloaded, caption, reply_to_message_id=reply_to)
                if caption:
                    return await telegram.send_text(caption, reply_to_message_id=reply_to)
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
            try:
                self.config.unsupported_log.parent.mkdir(parents=True, exist_ok=True)
                with self.config.unsupported_log.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(message, ensure_ascii=False, default=str) + "\n")
            except Exception as exc:
                log.warning("Could not write unsupported update log: %s", exc)
        return []

    # ------------------------------------------------------------- new message

    def _already_forwarded(self, message: dict) -> bool:
        chat_id, msg_id = _source_key(message)
        if not msg_id:
            return False
        return self.store.get(chat_id, msg_id) is not None

    async def handle_new_message(self, bale: BaleClient, telegram: TelegramSender, message: dict, source_key: str = "message") -> None:
        if not self._is_source_channel(message):
            self._log_wrong_chat(source_key, message)
            return
        if _is_bot_message(message):
            return
        if self._already_forwarded(message):
            # Bale re-delivers the batch if the bot died before the offset was stored.
            log.info("Bale message %s was already forwarded; skipping duplicate.", _message_id(message))
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

    # ------------------------------------------------------------ media groups

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
        if any(entry["source"] == (chat_id, msg_id) for entry in group["entries"]):
            return
        group["entries"].append({"source": (chat_id, msg_id), "items": media_items})

        task = group.get("task")
        if task and not task.done():
            task.cancel()
        new_task = asyncio.create_task(self._flush_media_group_later(key))
        self._group_tasks.add(new_task)
        new_task.add_done_callback(self._group_tasks.discard)
        new_task.add_done_callback(self._log_task_error)
        group["task"] = new_task

    @staticmethod
    def _log_task_error(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.error("Media group flush failed: %s", exc, exc_info=exc)

    async def _flush_media_group_later(self, key: str) -> None:
        await asyncio.sleep(self.config.media_group_wait_seconds)
        await self._flush_media_group(key)

    async def _flush_all_pending(self) -> None:
        for key in list(self.pending_groups.keys()):
            group = self.pending_groups.get(key)
            if not group:
                continue
            task = group.get("task")
            if task and not task.done():
                task.cancel()
            try:
                await self._flush_media_group(key)
            except Exception:
                log.exception("Could not flush pending media group %s during shutdown.", key)

    async def _flush_media_group(self, key: str) -> None:
        group = self.pending_groups.pop(key, None)
        if not group:
            return

        all_media: list[MediaItem] = []
        source_for_each_item: list[tuple[str, str]] = []
        seen_keys: set[str] = set()
        for entry in group["entries"]:
            for item in entry["items"]:
                if item.unique_key in seen_keys:
                    continue
                seen_keys.add(item.unique_key)
                all_media.append(item)
                source_for_each_item.append(entry["source"])

        downloaded, skipped = await self._download_items(group["bale"], all_media)
        caption = self._with_skip_notice(group["caption"], skipped)
        try:
            ids = await group["telegram"].send_media_group(downloaded, caption, reply_to_message_id=group.get("reply_to"))
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

    # ---------------------------------------------------------- edit / delete

    async def handle_edited_message(self, bale: BaleClient, telegram: TelegramSender, message: dict, source_key: str = "edited_message") -> None:
        if not self._is_source_channel(message):
            self._log_wrong_chat(source_key, message)
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
            edited_ids = await telegram.edit_existing(telegram_ids, text)
            if edited_ids:
                self.store.save(chat_id, msg_id, edited_ids, "message")
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
