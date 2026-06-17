#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv

from bale import Bot, Message          # کتابخانهٔ بله
from telegram import Bot as TgBot     # کتابخانهٔ تلگرام
from telegram.error import TelegramError

# ------------------------------------------------------------------
# ۱. تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ------------------------------------------------------------------
# ۲. بارگذاری متغیرهای محیطی (.env)
load_dotenv()

BALE_TOKEN      = os.getenv("BALE_TOKEN")
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN")
BALE_CHANNEL    = os.getenv("BALE_CHANNEL_ID")   # در setup.py به این نام ذخیره شد
TELEGRAM_CHANNEL= os.getenv("TELEGRAM_CHANNEL_ID")

# ------------------------------------------------------------------
# ۳. بررسی وجود توکن‌ها و کانال‌ها
if not BALE_TOKEN:
    log.error("❌ توکن بله (BALE_TOKEN) پیدا نشد!")
    exit(1)
if not TELEGRAM_TOKEN:
    log.error("❌ توکن تلگرام (TELEGRAM_TOKEN) پیدا نشد!")
    exit(1)
if not BALE_CHANNEL:
    log.error("❌ آیدی کانال بله (BALE_CHANNEL_ID) تنظیم نشده است!")
    exit(1)

# ------------------------------------------------------------------
# ۴. ایجاد نمونهٔ ربات‌ها
bale_bot = Bot(token=BALE_TOKEN, base_url="https://tapi.bale.ai/bot")
telegram_bot = TgBot(token=TELEGRAM_TOKEN)

# ------------------------------------------------------------------
# ۵. دایرکتوری موقت برای دانلود فایل‌ها
TEMP_DIR = Path("temp_downloads")
TEMP_DIR.mkdir(exist_ok=True)

# ------------------------------------------------------------------
# ۶. توابع کمکی

def download_from_bale(file_id: str) -> str | None:
    """دانلود فایل از بله (همگام)"""
    try:
        file_info = bale_bot.get_file(file_id)
        file_path = TEMP_DIR / file_info.file_name
        file_info.download(file_path)
        log.info(f"📥 فایل از بله دانلود شد: {file_path}")
        return str(file_path)
    except Exception as e:
        log.error(f"❌ خطا در دانلود از بله: {e}")
        return None

def send_to_destinations(text: str, file_path: str | None = None,
                         file_type: str | None = None):
    """ارسال پیام به تمام مقصدها (همگام)"""
    # ۱. ارسال به بله
    if BALE_CHANNEL:
        try:
            if file_path and file_type:
                with open(file_path, 'rb') as f:
                    if file_type == "photo":
                        bale_bot.send_photo(BALE_CHANNEL, f, caption=text)
                    elif file_type == "video":
                        bale_bot.send_video(BALE_CHANNEL, f, caption=text)
                    elif file_type == "document":
                        bale_bot.send_document(BALE_CHANNEL, f, caption=text)
                    else:
                        bale_bot.send_message(BALE_CHANNEL, text)
                os.remove(file_path)          # پاک‌کردن فایل بعد از ارسال
            else:
                bale_bot.send_message(BALE_CHANNEL, text)
            log.info("✅ پیام به کانال بله ارسال شد.")
        except Exception as e:
            log.error(f"❌ خطا در ارسال به بله: {e}")

    # ۲. ارسال به تلگرام
    if TELEGRAM_CHANNEL:
        try:
            if file_path and file_type:
                with open(file_path, 'rb') as f:
                    if file_type == "photo":
                        telegram_bot.send_photo(TELEGRAM_CHANNEL, f, caption=text)
                    elif file_type == "video":
                        telegram_bot.send_video(TELEGRAM_CHANNEL, f, caption=text)
                    elif file_type == "document":
                        telegram_bot.send_document(TELEGRAM_CHANNEL, f, caption=text)
                    else:
                        telegram_bot.send_message(TELEGRAM_CHANNEL, text)
                if os.path.exists(file_path):
                    os.remove(file_path)      # پاک‌کردن فایل بعد از ارسال
            else:
                telegram_bot.send_message(TELEGRAM_CHANNEL, text)
            log.info("✅ پیام به کانال تلگرام ارسال شد.")
        except TelegramError as e:
            log.error(f"❌ خطا در ارسال به تلگرام: {e}")

# ------------------------------------------------------------------
# ۷. تابع اصلی (ناهمگام)

async def main():
    log.info("🚀 ربات همگام‌سازی راه‌اندازی شد.")
    log.info(f"👀 در حال گوش‌دادن به کانال بله: {BALE_CHANNEL}")

    # تست اتصال به بله
    try:
        me = await bale_bot.get_me()
        log.info(f"✅ اتصال به بله برقرار شد. ربات: @{me.username}")
    except Exception as e:
        log.error(f"❌ اتصال به بله ناموفق: {e}")
        return

    last_processed_id = None

    while True:
        try:
            updates = await bale_bot.get_updates(offset=last_processed_id, timeout=30)

            for update in updates:
                if not hasattr(update, 'message'):
                    continue
                msg = update.message
                if not msg:
                    continue

                # نادیده گرفتن پیام‌های خود ربات
                if getattr(msg.from_user, "is_bot", False):
                    continue

                # فقط پیام‌های کانال را پردازش کن
                if getattr(msg.chat, "type", None) != "channel":
                    continue

                log.info(f"📩 پیام جدید از کانال بله دریافت شد.")

                text = msg.text or msg.caption or ""
                file_id   = None
                file_type = None
                file_path = None

                # تشخیص نوع فایل با بررسی وجود ویژگی‌ها
                if hasattr(msg, "photo") and getattr(msg.photo, "__len__", lambda: 0)() > 0:
                    file_id   = msg.photo[-1].file_id          # آخرین (بزرگ‌ترین) عکس
                    file_type = "photo"
                elif hasattr(msg, "video"):
                    file_id   = getattr(msg.video, "file_id", None)
                    file_type = "video" if file_id else None
                elif hasattr(msg, "document"):
                    file_id   = getattr(msg.document, "file_id", None)
                    file_type = "document" if file_id else None

                # دانلود فایل (در صورت وجود)
                if file_id:
                    file_path = download_from_bale(file_id)
                    if not file_path:
                        log.warning("⚠️ دانلود فایل ناموفق بود، فقط متن ارسال می‌شود.")
                        file_type = None   # از ارسال فایل صرف‌نظر کن

                # ارسال به مقصدها
                send_to_destinations(text, file_path, file_type)

                # به‌روزرسانی last_processed_id
                last_processed_id = update.update_id + 1

        except Exception as e:
            log.error(f"❌ خطا در حلقه اصلی: {e}")
            await asyncio.sleep(5)   # اگر خطا شد، ۵ ثانیه صبر کن

# ------------------------------------------------------------------
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("🚨 ربات متوقف شد (Ctrl+C).")
