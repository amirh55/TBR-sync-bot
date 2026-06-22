# -*- coding: utf-8 -*-
import os
import sys
import html
import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv
from bale import Bot
from telegram import Bot as TgBot, InputMediaPhoto, InputMediaVideo
from telegram.error import TelegramError


logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# Keep logs safe and readable on servers/PM2.
# python-telegram-bot/httpx can print URLs containing the Telegram bot token.
for noisy_logger in ("httpx", "httpcore", "telegram", "telegram.ext", "apscheduler"):
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

# \u0645\u0642\u0627\u062f\u06cc\u0631 .env \u0647\u0645\u06cc\u0634\u0647 \u0631\u0648\u06cc \u0645\u062a\u063a\u06cc\u0631\u0647\u0627\u06cc \u0642\u0628\u0644\u06cc \u0645\u062d\u06cc\u0637 override \u0634\u0648\u0646\u062f
load_dotenv(override=True)


def env(*names, default=None):
    """\u062e\u0648\u0627\u0646\u062f\u0646 \u0645\u062a\u063a\u06cc\u0631 \u0645\u062d\u06cc\u0637\u06cc \u0628\u0627 \u067e\u0634\u062a\u06cc\u0628\u0627\u0646\u06cc \u0627\u0632 \u062d\u0631\u0648\u0641 \u06a9\u0648\u0686\u06a9 \u0648 \u0628\u0632\u0631\u06af."""
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value.strip()
    return default


BALE_TOKEN = env("bale_token", "BALE_TOKEN")
TELEGRAM_TOKEN = env("telegram_token", "TELEGRAM_TOKEN")
BALE_CHANNEL_ID = env("bale_channel_id", "BALE_CHANNEL_ID")
TELEGRAM_CHANNEL_ID = env("telegram_channel_id", "TELEGRAM_CHANNEL_ID")

BALE_USERNAME_TO_REPLACE = env("bale_username_to_replace", "BALE_USERNAME_TO_REPLACE")
TELEGRAM_USERNAME_REPLACEMENT = env("telegram_username_replacement", "TELEGRAM_USERNAME_REPLACEMENT")

SYNC_OLD_MESSAGES = env("sync_old_messages", "SYNC_OLD_MESSAGES", default="false").lower() == "true"
POLL_TIMEOUT = int(env("poll_timeout", "POLL_TIMEOUT", default="25"))
MEDIA_GROUP_WAIT_SECONDS = float(env("media_group_wait_seconds", "MEDIA_GROUP_WAIT_SECONDS", default="1.2"))
FORCE_RTL = env("force_rtl", "FORCE_RTL", default="false").lower() == "true"
SKIP_DUPLICATE_MEDIA_DOCUMENTS = env("skip_duplicate_media_documents", "SKIP_DUPLICATE_MEDIA_DOCUMENTS", default="true").lower() == "true"
DEBUG_MEDIA = env("debug_media", "DEBUG_MEDIA", default="false").lower() == "true"

if not BALE_TOKEN:
    log.error("ERROR: bale_token is missing in .env")
    sys.exit(1)
if not TELEGRAM_TOKEN:
    log.error("ERROR: telegram_token is missing in .env")
    sys.exit(1)
if not BALE_CHANNEL_ID:
    log.error("ERROR: bale_channel_id is missing in .env. Example: @source_channel")
    sys.exit(1)
if not TELEGRAM_CHANNEL_ID:
    log.error("ERROR: telegram_channel_id is missing in .env. Example: @destination_channel")
    sys.exit(1)

TEMP_DIR = Path("temp_downloads")
TEMP_DIR.mkdir(exist_ok=True)


def safe_get(obj, attr, default=None):
    """\u062f\u0631\u06cc\u0627\u0641\u062a \u0627\u0645\u0646 \u0645\u0642\u062f\u0627\u0631 \u0627\u0632 \u0634\u06cc\u0621 \u06cc\u0627 \u062f\u06cc\u06a9\u0634\u0646\u0631\u06cc."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


def is_source_channel(chat) -> bool:
    """\u0641\u0642\u0637 \u067e\u06cc\u0627\u0645 \u06a9\u0627\u0646\u0627\u0644 \u0645\u0646\u0628\u0639 \u0628\u0644\u0647 \u0631\u0627 \u0642\u0628\u0648\u0644 \u0645\u06cc\u200c\u06a9\u0646\u062f.

    \u0627\u06af\u0631 \u06a9\u062a\u0627\u0628\u062e\u0627\u0646\u0647 username \u06a9\u0627\u0646\u0627\u0644 \u0631\u0627 \u0628\u0631\u0646\u06af\u0631\u062f\u0627\u0646\u062f\u060c \u0628\u0631\u0627\u06cc \u0627\u06cc\u0646\u06a9\u0647 \u0631\u0628\u0627\u062a \u0627\u0632 \u06a9\u0627\u0631 \u0646\u06cc\u0641\u062a\u062f
    \u067e\u06cc\u0627\u0645 \u06a9\u0627\u0646\u0627\u0644 \u0631\u0627 \u0631\u062f \u0646\u0645\u06cc\u200c\u06a9\u0646\u06cc\u0645\u061b \u0686\u0648\u0646 \u0645\u0639\u0645\u0648\u0644\u0627\u064b \u0631\u0628\u0627\u062a \u0641\u0642\u0637 \u062f\u0631 \u0647\u0645\u0627\u0646 \u06a9\u0627\u0646\u0627\u0644 \u0639\u0636\u0648 \u0627\u0633\u062a.
    """
    if safe_get(chat, "type") != "channel":
        return False

    expected = (BALE_CHANNEL_ID or "").strip()
    username = safe_get(chat, "username")
    chat_id = safe_get(chat, "id")

    if expected.startswith("@"):
        if username:
            return username.lower() == expected[1:].lower()
        return True

    return str(chat_id) == expected


RTL_MARK = "\u200f"


def add_rtl_marks(html_text: str) -> str:
    """\u0627\u06af\u0631 \u0645\u062a\u0646 \u0641\u0627\u0631\u0633\u06cc/\u0639\u0631\u0628\u06cc \u0628\u0627 \u0627\u06cc\u0645\u0648\u062c\u06cc \u0634\u0631\u0648\u0639 \u0634\u0648\u062f\u060c \u062a\u0644\u06af\u0631\u0627\u0645 \u06af\u0627\u0647\u06cc \u0622\u0646 \u0631\u0627 \u0686\u067e\u200c\u0628\u0647\u200c\u0631\u0627\u0633\u062a \u0646\u0634\u0627\u0646 \u0645\u06cc\u200c\u062f\u0647\u062f.

    \u0628\u0627 \u0627\u0636\u0627\u0641\u0647 \u06a9\u0631\u062f\u0646 RLM \u062f\u0631 \u0627\u0628\u062a\u062f\u0627\u06cc \u062e\u0637\u200c\u0647\u0627\u06cc \u063a\u06cc\u0631\u062e\u0627\u0644\u06cc\u060c \u062c\u0647\u062a \u0646\u0645\u0627\u06cc\u0634 \u062f\u0631 \u062a\u0644\u06af\u0631\u0627\u0645 \u0631\u0627\u0633\u062a\u200c\u0628\u0647\u200c\u0686\u067e \u0645\u06cc\u200c\u0634\u0648\u062f.
    """
    if not html_text:
        return ""

    lines = html_text.split("\n")
    fixed_lines = []
    for line in lines:
        if line.strip() and not line.startswith(RTL_MARK):
            fixed_lines.append(RTL_MARK + line)
        else:
            fixed_lines.append(line)
    return "\n".join(fixed_lines)


def convert_bale_markdown_to_telegram_html(text: str) -> str:
    """\u062a\u0628\u062f\u06cc\u0644 \u0633\u0627\u062f\u0647 \u0648 \u0645\u0642\u0627\u0648\u0645 Markdown \u0628\u0644\u0647 \u0628\u0647 HTML \u062a\u0644\u06af\u0631\u0627\u0645.

    \u0628\u0644\u0647 \u062f\u0631 \u06a9\u0627\u0646\u0627\u0644\u200c\u0647\u0627 \u06af\u0627\u0647\u06cc \u06a9\u0644 \u0645\u062a\u0646 \u0631\u0627 \u0627\u06cc\u0646\u200c\u0637\u0648\u0631\u06cc \u0645\u06cc\u200c\u062f\u0647\u062f:
    \U0001f534\U0001f1e8\U0001f1ed*\u0645\u062a\u0646 \u0686\u0646\u062f\u062e\u0637\u06cc ...\n@channel\n*

    Regex \u0645\u0639\u0645\u0648\u0644\u06cc \u0627\u06cc\u0646 \u062d\u0627\u0644\u062a \u0631\u0627 \u0646\u0645\u06cc\u200c\u06af\u06cc\u0631\u062f\u060c \u0686\u0648\u0646 \u0633\u062a\u0627\u0631\u0647 \u067e\u0627\u06cc\u0627\u0646\u06cc \u0645\u0645\u06a9\u0646 \u0627\u0633\u062a \u0628\u0639\u062f \u0627\u0632 newline \u0628\u0627\u0634\u062f.
    \u0628\u0631\u0627\u06cc \u0647\u0645\u06cc\u0646 \u0645\u062a\u0646 \u0631\u0627 \u06a9\u0627\u0631\u0627\u06a9\u062a\u0631 \u0628\u0647 \u06a9\u0627\u0631\u0627\u06a9\u062a\u0631 \u0645\u06cc\u200c\u062e\u0648\u0627\u0646\u06cc\u0645 \u0648 \u0647\u0631 * \u06cc\u0627 ** \u0631\u0627 \u0628\u0647 <b> / </b> \u062a\u0628\u062f\u06cc\u0644 \u0645\u06cc\u200c\u06a9\u0646\u06cc\u0645.
    """
    if not text:
        return ""

    if BALE_USERNAME_TO_REPLACE and TELEGRAM_USERNAME_REPLACEMENT:
        text = text.replace(BALE_USERNAME_TO_REPLACE, TELEGRAM_USERNAME_REPLACEMENT)

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    out = []
    bold_open = False
    i = 0
    while i < len(text):
        ch = text[i]

        if ch == "*":
            # \u067e\u0634\u062a\u06cc\u0628\u0627\u0646\u06cc \u0647\u0645\u0632\u0645\u0627\u0646 \u0627\u0632 *bold* \u0648 **bold**\u060c \u0628\u062f\u0648\u0646 \u067e\u06cc\u0686\u06cc\u062f\u0647 \u06a9\u0631\u062f\u0646 \u06a9\u062f
            if i + 1 < len(text) and text[i + 1] == "*":
                i += 2
            else:
                i += 1

            out.append("</b>" if bold_open else "<b>")
            bold_open = not bold_open
            continue

        out.append(html.escape(ch, quote=False))
        i += 1

    if bold_open:
        out.append("</b>")

    html_text = "".join(out)
    return add_rtl_marks(html_text) if FORCE_RTL else html_text


async def get_updates_safe(bale_bot: Bot, offset=None):
    """\u06af\u0631\u0641\u062a\u0646 \u0622\u067e\u062f\u06cc\u062a\u200c\u0647\u0627 \u0628\u0627 long polling \u062f\u0631 \u0635\u0648\u0631\u062a \u067e\u0634\u062a\u06cc\u0628\u0627\u0646\u06cc \u06a9\u062a\u0627\u0628\u062e\u0627\u0646\u0647."""
    try:
        return await bale_bot.get_updates(offset=offset, timeout=POLL_TIMEOUT)
    except TypeError:
        return await bale_bot.get_updates(offset=offset)


async def skip_pending_updates(bale_bot: Bot):
    """\u0646\u0627\u062f\u06cc\u062f\u0647 \u06af\u0631\u0641\u062a\u0646 \u067e\u06cc\u0627\u0645\u200c\u0647\u0627\u06cc \u0642\u0628\u0644\u06cc.

    \u0637\u0628\u0642 \u0645\u0633\u062a\u0646\u062f\u0627\u062a \u0628\u0644\u0647\u060c offset \u0645\u0646\u0641\u06cc \u0622\u067e\u062f\u06cc\u062a\u200c\u0647\u0627\u06cc \u0627\u0646\u062a\u0647\u0627\u06cc \u0635\u0641 \u0631\u0627 \u0645\u06cc\u200c\u06af\u06cc\u0631\u062f
    \u0648 \u0622\u067e\u062f\u06cc\u062a\u200c\u0647\u0627\u06cc \u0642\u0628\u0644\u06cc \u0631\u0627 \u0641\u0631\u0627\u0645\u0648\u0634 \u0645\u06cc\u200c\u06a9\u0646\u062f. \u0645\u0627 \u0647\u0645\u0627\u0646 \u0622\u062e\u0631\u06cc\u0646 \u0622\u067e\u062f\u06cc\u062a \u0631\u0627 \u0647\u0645 \u0627\u0631\u0633\u0627\u0644 \u0646\u0645\u06cc\u200c\u06a9\u0646\u06cc\u0645
    \u0648 offset \u0631\u0627 \u0631\u0648\u06cc \u0628\u0639\u062f \u0627\u0632 \u0622\u0646 \u0645\u06cc\u200c\u06af\u0630\u0627\u0631\u06cc\u0645.
    """
    if SYNC_OLD_MESSAGES:
        log.info("sync_old_messages=true; old pending updates will be processed.")
        return None

    try:
        updates = await get_updates_safe(bale_bot, offset=-1)
        if not updates:
            log.info("Pending update queue is empty. Listening for new posts only.")
            return None

        last_update_id = max(
            safe_get(update, "update_id", -1)
            for update in updates
            if safe_get(update, "update_id") is not None
        )
        next_offset = last_update_id + 1
        log.info(f"Old pending updates were skipped. next_offset={next_offset}")
        return next_offset
    except Exception as e:
        log.warning(f"WARNING: Could not skip pending updates: {e}")
        log.warning("To avoid copying old posts, the bot will wait for the next run.")
        return None


async def download_from_bale(bale_bot: Bot, file_id: str, file_type: str) -> str | None:
    """\u062f\u0627\u0646\u0644\u0648\u062f \u0641\u0627\u06cc\u0644 \u0627\u0632 \u0628\u0644\u0647 \u0628\u0627 \u0647\u0645\u0627\u0646 \u0645\u0646\u0637\u0642 \u0633\u0627\u062f\u0647 \u0646\u0633\u062e\u0647 \u0627\u0648\u0644\u06cc\u0647."""
    try:
        file_info = await bale_bot.get_file(file_id)
        file_path = TEMP_DIR / f"{file_type}_{file_id}.file"

        with open(file_path, "wb") as f:
            if hasattr(file_info, "save_to_memory"):
                await file_info.save_to_memory(f)
            elif hasattr(file_info, "download"):
                await file_info.download(str(file_path))
            elif isinstance(file_info, (bytes, bytearray)):
                f.write(file_info)
            else:
                raise Exception(f"\u0641\u0631\u0645\u062a \u0646\u0627\u0634\u0646\u0627\u062e\u062a\u0647 file_info: {type(file_info)}")

        return str(file_path)
    except Exception as e:
        log.error(f"ERROR: failed to download file from Bale: {e}")
        return None


async def send_to_telegram(telegram_bot: TgBot, text: str, file_path: str = None, file_type: str = None) -> bool:
    """\u0627\u0631\u0633\u0627\u0644 \u067e\u06cc\u0627\u0645/\u0641\u0627\u06cc\u0644 \u0628\u0647 \u062a\u0644\u06af\u0631\u0627\u0645 \u0628\u0627 parse_mode=HTML.

    \u0646\u06a9\u062a\u0647 \u0645\u0647\u0645: \u0646\u0633\u062e\u0647\u200c\u0647\u0627\u06cc \u0642\u0628\u0644\u06cc \u062f\u0631 \u062d\u0627\u0644\u062a \xab\u067e\u06cc\u0627\u0645 \u062e\u0627\u0644\u06cc / \u0645\u062f\u06cc\u0627\u06cc \u062a\u0634\u062e\u06cc\u0635 \u062f\u0627\u062f\u0647 \u0646\u0634\u062f\u0647\xbb \u0647\u0645 success \u0644\u0627\u06af \u0645\u06cc\u200c\u0632\u062f\u0646\u062f.
    \u0627\u06cc\u0646 \u0646\u0633\u062e\u0647 \u0641\u0642\u0637 \u0648\u0642\u062a\u06cc \u0648\u0627\u0642\u0639\u0627\u064b \u06cc\u06a9\u06cc \u0627\u0632 \u0645\u062a\u062f\u0647\u0627\u06cc \u062a\u0644\u06af\u0631\u0627\u0645 \u0635\u062f\u0627 \u0632\u062f\u0647 \u0634\u0648\u062f True \u0628\u0631\u0645\u06cc\u200c\u06af\u0631\u062f\u0627\u0646\u062f.
    """
    formatted_text = convert_bale_markdown_to_telegram_html(text or "")
    caption = formatted_text or None
    sent = False

    try:
        if file_path and file_type:
            with open(file_path, "rb") as f:
                if file_type == "photo":
                    await telegram_bot.send_photo(TELEGRAM_CHANNEL_ID, f, caption=caption, parse_mode="HTML")
                    sent = True
                elif file_type == "video":
                    await telegram_bot.send_video(TELEGRAM_CHANNEL_ID, f, caption=caption, parse_mode="HTML")
                    sent = True
                elif file_type == "document":
                    await telegram_bot.send_document(TELEGRAM_CHANNEL_ID, f, caption=caption, parse_mode="HTML")
                    sent = True
                elif file_type == "animation":
                    await telegram_bot.send_animation(TELEGRAM_CHANNEL_ID, f, caption=caption, parse_mode="HTML")
                    sent = True
                elif file_type == "audio":
                    await telegram_bot.send_audio(TELEGRAM_CHANNEL_ID, f, caption=caption, parse_mode="HTML")
                    sent = True
                else:
                    log.warning(f"WARNING: unsupported file_type={file_type}; skipped")
        elif formatted_text:
            await telegram_bot.send_message(TELEGRAM_CHANNEL_ID, formatted_text, parse_mode="HTML")
            sent = True

        if sent:
            log.info("Message sent to Telegram successfully.")
        else:
            log.warning("WARNING: empty/unsupported Bale post was not sent to Telegram.")
        return sent
    except TelegramError as e:
        log.error(f"ERROR: failed to send to Telegram: {e}")
        log.error("Make sure the Telegram bot is admin in the destination channel and telegram_channel_id is correct.")
        return False
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                log.warning(f"WARNING: failed to delete temp file: {e}")


def get_media_group_id(msg):
    """\u0634\u0646\u0627\u0633\u0647 \u0622\u0644\u0628\u0648\u0645/\u0645\u062f\u06cc\u0627\u06af\u0631\u0648\u067e \u062f\u0631 \u0646\u0633\u062e\u0647\u200c\u0647\u0627\u06cc \u0645\u062e\u062a\u0644\u0641 \u06a9\u062a\u0627\u0628\u062e\u0627\u0646\u0647 \u0645\u0645\u06a9\u0646 \u0627\u0633\u062a \u0646\u0627\u0645 \u0645\u062a\u0641\u0627\u0648\u062a\u06cc \u062f\u0627\u0634\u062a\u0647 \u0628\u0627\u0634\u062f."""
    for name in ("media_group_id", "mediaGroupId", "album_id", "grouped_id", "group_id"):
        value = safe_get(msg, name)
        if value not in (None, ""):
            return str(value)
    return None


def get_file_id(obj):
    """file_id \u062f\u0631 \u0646\u0633\u062e\u0647\u200c\u0647\u0627\u06cc \u0645\u062e\u062a\u0644\u0641 \u06a9\u062a\u0627\u0628\u062e\u0627\u0646\u0647 \u0645\u0645\u06a9\u0646 \u0627\u0633\u062a \u0628\u0627 \u0646\u0627\u0645\u200c\u0647\u0627\u06cc \u06a9\u0645\u06cc \u0645\u062a\u0641\u0627\u0648\u062a \u0628\u0631\u06af\u0631\u062f\u062f."""
    for name in ("file_id", "fileId", "id"):
        value = safe_get(obj, name)
        if value not in (None, ""):
            return str(value)
    return None


def get_file_unique_key(obj):
    """\u06a9\u0644\u06cc\u062f \u062a\u0642\u0631\u06cc\u0628\u06cc \u0628\u0631\u0627\u06cc \u062c\u0644\u0648\u06af\u06cc\u0631\u06cc \u0627\u0632 \u0627\u0631\u0633\u0627\u0644 \u062f\u0648\u0628\u0627\u0631\u0647 \u06cc\u06a9 \u0641\u0627\u06cc\u0644 \u0645\u0634\u0627\u0628\u0647."""
    for name in ("file_unique_id", "fileUniqueId", "unique_id", "uniqueId"):
        value = safe_get(obj, name)
        if value not in (None, ""):
            return f"unique:{value}"

    file_id = get_file_id(obj)
    if file_id:
        return f"id:{file_id}"

    size = safe_get(obj, "file_size") or safe_get(obj, "fileSize")
    name = safe_get(obj, "file_name") or safe_get(obj, "fileName")
    mime = safe_get(obj, "mime_type") or safe_get(obj, "mimeType")
    if size or name or mime:
        return f"meta:{name}:{mime}:{size}"

    return None


def get_mime_type(obj):
    value = safe_get(obj, "mime_type") or safe_get(obj, "mimeType") or ""
    return str(value).lower().strip()


def get_file_name(obj):
    value = safe_get(obj, "file_name") or safe_get(obj, "fileName") or ""
    return str(value).lower().strip()


def listify(value):
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def looks_like_media_document(obj):
    """
    \u0628\u0639\u0636\u06cc \u067e\u06cc\u0627\u0645\u200c\u0647\u0627\u06cc \u0628\u0644\u0647 \u06cc\u06a9 \u0639\u06a9\u0633/\u0648\u06cc\u062f\u06cc\u0648 \u0631\u0627 \u0628\u0647\u200c\u062c\u0627\u06cc photo/video \u06cc\u0627 \u0639\u0644\u0627\u0648\u0647 \u0628\u0631 \u0622\u0646\u060c \u062f\u0631 document \u0645\u06cc\u200c\u062f\u0647\u0646\u062f.
    \u0627\u06cc\u0646 \u062a\u0627\u0628\u0639 \u0641\u0642\u0637 \u062a\u0634\u062e\u06cc\u0635 \u0627\u0648\u0644\u06cc\u0647 \u0627\u0633\u062a\u061b \u0627\u06af\u0631 MIME/\u0646\u0627\u0645 \u0648\u062c\u0648\u062f \u0646\u062f\u0627\u0634\u062a\u060c \u0628\u0639\u062f \u0627\u0632 \u062f\u0627\u0646\u0644\u0648\u062f \u0628\u0627 \u0627\u0645\u0636\u0627\u06cc \u0641\u0627\u06cc\u0644 \u0647\u0645 \u0686\u06a9 \u0645\u06cc\u200c\u06a9\u0646\u06cc\u0645.
    """
    mime = get_mime_type(obj)
    name = get_file_name(obj)

    if mime.startswith("image/") or mime.startswith("video/"):
        return True

    media_exts = (
        ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp",
        ".mp4", ".mov", ".m4v", ".webm",
    )
    if name.endswith(media_exts):
        return True

    # \u0641\u0627\u06cc\u0644\u200c\u0647\u0627\u06cc \u0628\u06cc\u200c\u0646\u0627\u0645/\u0628\u06cc\u200cMIME \u0628\u0644\u0647 \u0645\u0645\u06a9\u0646 \u0627\u0633\u062a \u0647\u0645\u0627\u0646 \u0639\u06a9\u0633 \u0628\u0627\u0634\u0646\u062f \u0648 \u062f\u0631 \u062a\u0644\u06af\u0631\u0627\u0645 \u0628\u0627 document_...file \u062f\u06cc\u062f\u0647 \u0634\u0648\u0646\u062f.
    if not name and not mime:
        return True

    return False


def media_kind_from_document_meta(obj):
    """\u0627\u06af\u0631 document \u062f\u0631\u0648\u0627\u0642\u0639 \u0639\u06a9\u0633/\u0648\u06cc\u062f\u06cc\u0648 \u0628\u0627\u0634\u062f\u060c \u0646\u0648\u0639 \u0645\u0646\u0627\u0633\u0628 \u062a\u0644\u06af\u0631\u0627\u0645 \u0631\u0627 \u062d\u062f\u0633 \u0645\u06cc\u200c\u0632\u0646\u062f."""
    mime = get_mime_type(obj)
    name = get_file_name(obj)

    if mime == "image/gif" or name.endswith(".gif"):
        return "animation"
    if mime.startswith("image/") or name.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp")):
        return "photo"
    if mime.startswith("video/") or name.endswith((".mp4", ".mov", ".m4v", ".webm")):
        return "video"

    return "document"


def media_kind_from_file_signature(path: str, default_kind: str = "document") -> str:
    """\u062a\u0634\u062e\u06cc\u0635 \u0645\u062d\u062a\u0648\u0627 \u0627\u0632 \u0631\u0648\u06cc \u0628\u0627\u06cc\u062a\u200c\u0647\u0627\u06cc \u0627\u0648\u0644 \u0641\u0627\u06cc\u0644\u061b \u0628\u0631\u0627\u06cc document_...file \u06a9\u0647 MIME \u0646\u062f\u0627\u0631\u062f \u0645\u0641\u06cc\u062f \u0627\u0633\u062a."""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
    except Exception:
        return default_kind

    if head.startswith(b"\xff\xd8\xff"):
        return "photo"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "photo"
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "animation"
    if head.startswith(b"RIFF") and b"WEBP" in head[:16]:
        return "photo"
    if len(head) > 12 and b"ftyp" in head[4:12]:
        return "video"

    return default_kind


def add_media_item(items, seen_keys, kind, obj):
    file_id = get_file_id(obj)
    if not file_id:
        return False

    key = get_file_unique_key(obj) or f"{kind}:{file_id}"
    if key in seen_keys:
        return False

    seen_keys.add(key)
    items.append((kind, file_id, obj))
    return True


def extract_media_items(msg):
    """
    \u0627\u0633\u062a\u062e\u0631\u0627\u062c \u0641\u0627\u06cc\u0644\u200c\u0647\u0627\u06cc \u0642\u0627\u0628\u0644 \u0627\u0631\u0633\u0627\u0644.

    \u062e\u0631\u0648\u062c\u06cc \u062f\u0648 \u0644\u06cc\u0633\u062a \u062f\u0627\u0631\u062f:
    - primary_items: \u0645\u062f\u06cc\u0627\u06cc \u0627\u0635\u0644\u06cc \u06a9\u0647 \u0628\u0627\u06cc\u062f \u0627\u0631\u0633\u0627\u0644 \u0634\u0648\u062f.
    - fallback_items: document\u0647\u0627\u06cc\u06cc \u06a9\u0647 \u0627\u062d\u062a\u0645\u0627\u0644\u0627\u064b \u0647\u0645\u0627\u0646 \u0639\u06a9\u0633/\u0648\u06cc\u062f\u06cc\u0648 \u0647\u0633\u062a\u0646\u062f. \u0641\u0642\u0637 \u0648\u0642\u062a\u06cc primary \u062f\u0627\u0646\u0644\u0648\u062f/\u0627\u0631\u0633\u0627\u0644 \u0646\u0634\u062f \u0627\u0633\u062a\u0641\u0627\u062f\u0647 \u0645\u06cc\u200c\u0634\u0648\u0646\u062f.

    \u0627\u06cc\u0646 \u0631\u0648\u0634 \u0645\u0634\u06a9\u0644 \u0646\u0633\u062e\u0647 \u0642\u0628\u0644 \u0631\u0627 \u062d\u0644 \u0645\u06cc\u200c\u06a9\u0646\u062f: \u062f\u06cc\u06af\u0631 document \u062a\u0635\u0648\u06cc\u0631\u06cc \u0631\u0627 \u06a9\u0648\u0631\u06a9\u0648\u0631\u0627\u0646\u0647 \u062d\u0630\u0641 \u0646\u0645\u06cc\u200c\u06a9\u0646\u06cc\u0645\u060c
    \u0628\u0644\u06a9\u0647 \u0622\u0646 \u0631\u0627 fallback \u0646\u06af\u0647 \u0645\u06cc\u200c\u062f\u0627\u0631\u06cc\u0645 \u062a\u0627 \u0627\u06af\u0631 photo/video \u0627\u0635\u0644\u06cc \u062f\u0631 \u062f\u0633\u062a\u0631\u0633 \u0646\u0628\u0648\u062f\u060c \u067e\u0633\u062a \u0627\u0632 \u062f\u0633\u062a \u0646\u0631\u0648\u062f.
    """
    primary_items = []
    fallback_items = []
    seen_keys = set()
    has_photo_or_video = False

    # \u062f\u0631 \u0628\u0639\u0636\u06cc \u0646\u0633\u062e\u0647\u200c\u0647\u0627 photo \u06cc\u06a9 \u0644\u06cc\u0633\u062a \u0627\u0632 \u0633\u0627\u06cc\u0632\u0647\u0627\u06cc \u06cc\u06a9 \u0639\u06a9\u0633 \u0627\u0633\u062a\u061b \u0628\u0647\u062a\u0631\u06cc\u0646/\u0622\u062e\u0631\u06cc\u0646 \u0633\u0627\u06cc\u0632 \u06a9\u0627\u0641\u06cc \u0627\u0633\u062a.
    for attr in ("photos", "photo"):
        photos = safe_get(msg, attr)
        if photos:
            if isinstance(photos, (list, tuple)):
                photo = list(photos)[-1] if photos else None
            else:
                photo = photos
            if photo and add_media_item(primary_items, seen_keys, "photo", photo):
                has_photo_or_video = True
            break

    for attr in ("videos", "video"):
        videos = listify(safe_get(msg, attr))
        for video in videos:
            if add_media_item(primary_items, seen_keys, "video", video):
                has_photo_or_video = True

    for attr, kind in (("animation", "animation"), ("audio", "audio")):
        for item in listify(safe_get(msg, attr)):
            add_media_item(primary_items, seen_keys, kind, item)

    # \u0647\u0645 document \u0648 \u0647\u0645 documents \u0631\u0627 \u067e\u0648\u0634\u0634 \u0645\u06cc\u200c\u062f\u0647\u06cc\u0645.
    documents = []
    documents.extend(listify(safe_get(msg, "document")))
    documents.extend(listify(safe_get(msg, "documents")))

    for document in documents:
        if not document:
            continue

        if looks_like_media_document(document):
            guessed_kind = media_kind_from_document_meta(document)
            # \u0627\u06af\u0631 photo/video \u0627\u0635\u0644\u06cc \u0648\u062c\u0648\u062f \u062f\u0627\u0631\u062f\u060c \u0627\u06cc\u0646 \u0631\u0627 \u0641\u0642\u0637 fallback \u0646\u06af\u0647 \u0645\u06cc\u200c\u062f\u0627\u0631\u06cc\u0645 \u062a\u0627 duplicate \u0646\u0633\u0627\u0632\u062f.
            if SKIP_DUPLICATE_MEDIA_DOCUMENTS and has_photo_or_video:
                file_id = get_file_id(document)
                if file_id:
                    fallback_items.append((guessed_kind, file_id, document))
                continue

            # \u0627\u06af\u0631 \u0639\u06a9\u0633 \u0641\u0642\u0637 \u0628\u0647\u200c\u0635\u0648\u0631\u062a document \u0622\u0645\u062f\u0647\u060c \u0647\u0645\u0627\u0646 \u0631\u0627 \u0628\u0647\u200c\u0639\u0646\u0648\u0627\u0646 \u0639\u06a9\u0633/\u0648\u06cc\u062f\u06cc\u0648 \u0645\u06cc\u200c\u0641\u0631\u0633\u062a\u06cc\u0645 \u0646\u0647 document.
            add_media_item(primary_items, seen_keys, guessed_kind, document)
        else:
            add_media_item(primary_items, seen_keys, "document", document)

    if DEBUG_MEDIA:
        log.info(f"Media detected: primary={[(k, fid) for k, fid, _ in primary_items]} fallback={[(k, fid) for k, fid, _ in fallback_items]}")

    return primary_items, fallback_items


async def send_media_group_to_telegram(telegram_bot: TgBot, caption_text: str, media_items):
    """\u0627\u0631\u0633\u0627\u0644 \u0622\u0644\u0628\u0648\u0645 \u0639\u06a9\u0633/\u0648\u06cc\u062f\u06cc\u0648 \u0628\u0647 \u062a\u0644\u06af\u0631\u0627\u0645. \u0627\u06af\u0631 \u06af\u0631\u0648\u0647 \u0641\u0642\u0637 \u06cc\u06a9 \u0641\u0627\u06cc\u0644 \u062f\u0627\u0634\u062a\u060c \u0647\u0645\u0627\u0646 \u0627\u0631\u0633\u0627\u0644 \u0633\u0627\u062f\u0647 \u0627\u0646\u062c\u0627\u0645 \u0645\u06cc\u200c\u0634\u0648\u062f."""
    if not media_items:
        if caption_text:
            await send_to_telegram(telegram_bot, caption_text)
        return

    if len(media_items) == 1:
        kind, path = media_items[0]
        await send_to_telegram(telegram_bot, caption_text, path, kind)
        return

    formatted_caption = convert_bale_markdown_to_telegram_html(caption_text or "") or None
    opened_files = []
    telegram_media = []

    try:
        for index, (kind, path) in enumerate(media_items):
            # sendMediaGroup \u062a\u0644\u06af\u0631\u0627\u0645 \u0628\u0631\u0627\u06cc \u062a\u0631\u06a9\u06cc\u0628 \u0639\u06a9\u0633/\u0648\u06cc\u062f\u06cc\u0648 \u0645\u0646\u0627\u0633\u0628 \u0627\u0633\u062a\u061b \u0641\u0627\u06cc\u0644\u200c\u0647\u0627\u06cc \u062f\u06cc\u06af\u0631 \u062c\u062f\u0627 \u0627\u0631\u0633\u0627\u0644 \u0645\u06cc\u200c\u0634\u0648\u0646\u062f.
            if kind not in ("photo", "video"):
                raise ValueError("only photo/video media groups are supported")

            f = open(path, "rb")
            opened_files.append(f)
            caption = formatted_caption if index == 0 else None
            if kind == "photo":
                telegram_media.append(InputMediaPhoto(media=f, caption=caption, parse_mode="HTML" if caption else None))
            else:
                telegram_media.append(InputMediaVideo(media=f, caption=caption, parse_mode="HTML" if caption else None))

        await telegram_bot.send_media_group(chat_id=TELEGRAM_CHANNEL_ID, media=telegram_media)
        log.info(f"Media group {len(media_items)} items sent to Telegram successfully.")
    except Exception as e:
        log.warning(f"WARNING: media group failed; sending files one by one: {e}")
        for index, (kind, path) in enumerate(media_items):
            await send_to_telegram(telegram_bot, caption_text if index == 0 else "", path, kind)
    finally:
        for f in opened_files:
            try:
                f.close()
            except Exception:
                pass
        for _, path in media_items:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception as e:
                    log.warning(f"WARNING: failed to delete temp file: {e}")


async def flush_media_group_later(group_key, telegram_bot: TgBot, pending_groups):
    await asyncio.sleep(MEDIA_GROUP_WAIT_SECONDS)
    group = pending_groups.pop(group_key, None)
    if not group:
        return
    await send_media_group_to_telegram(telegram_bot, group.get("caption", ""), group.get("items", []))


async def handle_message(bale_bot: Bot, telegram_bot: TgBot, msg, pending_groups=None):
    chat = safe_get(msg, "chat")
    if not is_source_channel(chat):
        return

    from_user = safe_get(msg, "from_user")
    if from_user and safe_get(from_user, "is_bot"):
        return

    text = safe_get(msg, "text") or safe_get(msg, "caption") or ""
    primary_items, fallback_items = extract_media_items(msg)
    group_id = get_media_group_id(msg)

    downloaded_items = []
    for file_type, file_id, obj in primary_items:
        file_path = await download_from_bale(bale_bot, file_id, file_type)
        if file_path:
            # \u0627\u06af\u0631 \u0641\u0627\u06cc\u0644 document/unknown \u0628\u0648\u062f \u0648\u0644\u06cc \u0645\u062d\u062a\u0648\u0627\u06cc\u0634 \u0639\u06a9\u0633/\u0648\u06cc\u062f\u06cc\u0648 \u0627\u0633\u062a\u060c \u0646\u0648\u0639 \u0645\u0646\u0627\u0633\u0628 \u062a\u0644\u06af\u0631\u0627\u0645 \u0631\u0627 \u0627\u0646\u062a\u062e\u0627\u0628 \u06a9\u0646.
            final_type = media_kind_from_file_signature(file_path, file_type)
            downloaded_items.append((final_type, file_path))

    # \u0627\u06af\u0631 photo/video \u0627\u0635\u0644\u06cc \u062a\u0634\u062e\u06cc\u0635 \u062f\u0627\u062f\u0647 \u0634\u062f \u0648\u0644\u06cc \u062f\u0627\u0646\u0644\u0648\u062f \u0646\u0634\u062f\u060c fallback document \u0631\u0627 \u0627\u0645\u062a\u062d\u0627\u0646 \u06a9\u0646 \u062a\u0627 \u067e\u0633\u062a \u0627\u0632 \u062f\u0633\u062a \u0646\u0631\u0648\u062f.
    if not downloaded_items and fallback_items:
        if DEBUG_MEDIA:
            log.info("Primary media was not downloaded; trying fallback media documents...")
        for file_type, file_id, obj in fallback_items:
            file_path = await download_from_bale(bale_bot, file_id, file_type)
            if file_path:
                final_type = media_kind_from_file_signature(file_path, file_type)
                downloaded_items.append((final_type, file_path))

    # \u0627\u06af\u0631 \u0686\u0646\u062f \u0648\u06cc\u062f\u06cc\u0648/\u0639\u06a9\u0633 \u0628\u0647\u200c\u0635\u0648\u0631\u062a \u0622\u0644\u0628\u0648\u0645 \u0627\u0632 \u0628\u0644\u0647 \u0628\u0631\u0633\u062f\u060c \u0645\u0639\u0645\u0648\u0644\u0627\u064b \u0686\u0646\u062f \u0622\u067e\u062f\u06cc\u062a \u0628\u0627 media_group_id \u06cc\u06a9\u0633\u0627\u0646 \u0627\u0633\u062a.
    # \u06a9\u0645\u06cc \u0635\u0628\u0631 \u0645\u06cc\u200c\u06a9\u0646\u06cc\u0645 \u062a\u0627 \u0628\u0642\u06cc\u0647 \u0641\u0627\u06cc\u0644\u200c\u0647\u0627\u06cc \u0647\u0645\u0627\u0646 \u0622\u0644\u0628\u0648\u0645 \u0628\u0631\u0633\u0646\u062f\u060c \u0633\u067e\u0633 \u06cc\u06a9\u062c\u0627 \u0628\u0647 \u062a\u0644\u06af\u0631\u0627\u0645 \u0645\u06cc\u200c\u0641\u0631\u0633\u062a\u06cc\u0645.
    if group_id and downloaded_items and pending_groups is not None:
        key = f"{safe_get(chat, 'id', '')}:{group_id}"
        group = pending_groups.setdefault(key, {"caption": "", "items": [], "task": None})
        group["items"].extend(downloaded_items)
        if text and not group["caption"]:
            group["caption"] = text

        task = group.get("task")
        if task and not task.done():
            task.cancel()
        group["task"] = asyncio.create_task(flush_media_group_later(key, telegram_bot, pending_groups))
        return

    if len(downloaded_items) > 1:
        await send_media_group_to_telegram(telegram_bot, text, downloaded_items)
        return

    if downloaded_items:
        file_type, file_path = downloaded_items[0]
        await send_to_telegram(telegram_bot, text, file_path, file_type)
    else:
        await send_to_telegram(telegram_bot, text)


async def main():
    log.info("TBR sync bot started.")
    log.info(f"Bale source channel: {BALE_CHANNEL_ID}")
    log.info(f"Telegram destination channel: {TELEGRAM_CHANNEL_ID}")
    log.info(f"media_group_wait_seconds={MEDIA_GROUP_WAIT_SECONDS} | force_rtl={FORCE_RTL} | skip_duplicate_media_documents={SKIP_DUPLICATE_MEDIA_DOCUMENTS} | debug_media={DEBUG_MEDIA}")

    async with Bot(token=BALE_TOKEN) as bale_bot, TgBot(token=TELEGRAM_TOKEN) as telegram_bot:
        try:
            me = await bale_bot.get_me()
            log.info(f"Connected to Bale. Bot: @{safe_get(me, 'username')}")
        except Exception as e:
            log.error(f"ERROR: could not connect to Bale: {e}")
            return

        last_processed_id = await skip_pending_updates(bale_bot)
        pending_groups = {}

        while True:
            try:
                updates = await get_updates_safe(bale_bot, offset=last_processed_id)
                if not updates:
                    await asyncio.sleep(0.2)
                    continue

                for update in updates:
                    update_id = safe_get(update, "update_id")
                    msg = safe_get(update, "message")
                    if msg:
                        log.info("New Bale post received. Forwarding...")
                        await handle_message(bale_bot, telegram_bot, msg, pending_groups)

                    if update_id is not None:
                        last_processed_id = update_id + 1

            except Exception as e:
                log.error(f"ERROR in main loop: {e}")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
