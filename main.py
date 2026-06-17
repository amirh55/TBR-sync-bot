import os
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv

from bale import Bot
from telegram import Bot as TgBot
from telegram.error import TelegramError

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

load_dotenv()

# خواندن متغیرهای محیطی
BALE_TOKEN = os.getenv("BALE_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
BALE_CHANNEL = os.getenv("BALE_CHANNEL")
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL")

if not BALE_TOKEN:
    log.error("❌ توکن بله در فایل .env پیدا نشد!")
    exit(1)
if not TELEGRAM_TOKEN:
    log.error("❌ توکن تلگرام در فایل .env پیدا نشد!")
    exit(1)
if not BALE_CHANNEL:
    log.error("❌ آیدی کانال بله در فایل .env تنظیم نشده است!")
    exit(1)

# دایرکتوری موقت
TEMP_DIR = Path("temp_downloads")
TEMP_DIR.mkdir(exist_ok=True)

# ------------------- توابع کمکی (async) -------------------

async def download_from_bale(bale_bot: Bot, file_id: str) -> str | None:
    """دانلود فایل از بله (ناهمگام)"""
    try:
        file_info = await bale_bot.get_file(file_id)
        file_path = TEMP_DIR / file_info.file_path.split("/")[-1]
        await file_info.download_to_drive(str(file_path))
        log.info(f"📥 فایل از بله دانلود شد: {file_path}")
        return str(file_path)
    except Exception as e:
        log.error(f"❌ خطا در دانلود از بله: {e}")
        return None

async def send_to_bale(bale_bot: Bot, text: str, file_path: str = None, file_type: str = None):
    """ارسال پیام به کانال بله"""
    try:
        if file_path and file_type and os.path.exists(file_path):
            with open(file_path, 'rb') as f:
                if file_type == "photo":
                    await bale_bot.send_photo(BALE_CHANNEL, f, caption=text)
                elif file_type == "video":
                    await bale_bot.send_video(BALE_CHANNEL, f, caption=text)
                elif file_type == "document":
                    await bale_bot.send_document(BALE_CHANNEL, f, caption=text)
                else:
                    await bale_bot.send_message(BALE_CHANNEL, text)
        else:
            await bale_bot.send_message(BALE_CHANNEL, text)
        log.info("✅ پیام به کانال بله ارسال شد.")
    except Exception as e:
        log.error(f"❌ خطا در ارسال به بله: {e}")

async def send_to_telegram(tg_bot: TgBot, text: str, file_path: str = None, file_type: str = None):
    """ارسال پیام به کانال تلگرام"""
    if not TELEGRAM_CHANNEL:
        return
    try:
        if file_path and file_type and os.path.exists(file_path):
            with open(file_path, 'rb') as f:
                if file_type == "photo":
                    await tg_bot.send_photo(TELEGRAM_CHANNEL, f, caption=text)
                elif file_type == "video":
                    await tg_bot.send_video(TELEGRAM_CHANNEL, f, caption=text)
                elif file_type == "document":
                    await tg_bot.send_document(TELEGRAM_CHANNEL, f, caption=text)
                else:
                    await tg_bot.send_message(TELEGRAM_CHANNEL, text)
        else:
            await tg_bot.send_message(TELEGRAM_CHANNEL, text)
        log.info("✅ پیام به کانال تلگرام ارسال شد.")
    except TelegramError as e:
        log.error(f"❌ خطا در ارسال به تلگرام: {e}")

def cleanup_file(file_path: str):
    """حذف فایل موقت"""
    if file_path and os.path.exists(file_path):
        os.remove(file_path)

# ------------------- تابع اصلی (ناهمگام) -------------------

async def main():
    # ساخت botها داخل async context
    bale_bot = Bot(token=BALE_TOKEN)
    tg_bot = TgBot(token=TELEGRAM_TOKEN)

    log.info("🚀 ربات همگام‌سازی راه‌اندازی شد.")
    log.info(f"👀 در حال گوش‌دادن به کانال بله: {BALE_CHANNEL}")

    # تست اتصال به بله
    try:
        me = await bale_bot.get_me()
        log.info(f"✅ اتصال به بله برقرار شد. ربات: @{me.username}")
    except Exception as e:
        log.error(f"❌ اتصال به بله ناموفق: {e}")
        log.error("لطفاً توکن BALE_TOKEN را بررسی کنید.")
        return

    # تست اتصال به تلگرام
    try:
        tg_me = await tg_bot.get_me()
        log.info(f"✅ اتصال به تلگرام برقرار شد. ربات: @{tg_me.username}")
    except Exception as e:
        log.error(f"❌ اتصال به تلگرام ناموفق: {e}")

    last_processed_id = None

    while True:
        try:
            updates = await bale_bot.get_updates(offset=last_processed_id, timeout=30)

            for update in updates:
                if not hasattr(update, 'message') or not update.message:
                    last_processed_id = update.update_id + 1
                    continue

                msg = update.message

                # نادیده گرفتن پیام‌های ربات
                if msg.from_user and msg.from_user.is_bot:
                    last_processed_id = update.update_id + 1
                    continue

                # فقط پیام‌های کانال
                if not msg.chat or msg.chat.type != "channel":
                    last_processed_id = update.update_id + 1
                    continue

                log.info("📩 پیام جدید از کانال بله دریافت شد.")

                text = msg.text or msg.caption or ""
                file_id = None
                file_type = None
                file_path = None

                # تشخیص نوع فایل
                if msg.photo:
                    file_id = msg.photo[-1].file_id
                    file_type = "photo"
                elif msg.video:
                    file_id = msg.video.file_id
                    file_type = "video"
                elif msg.document:
                    file_id = msg.document.file_id
                    file_type = "document"

                # دانلود فایل
                if file_id:
                    file_path = await download_from_bale(bale_bot, file_id)
                    if not file_path:
                        log.warning("⚠️ دانلود فایل ناموفق بود، فقط متن ارسال می‌شود.")

                # ارسال به مقصدها
                await send_to_bale(bale_bot, text, file_path, file_type)
                await send_to_telegram(tg_bot, text, file_path, file_type)

                # پاکسازی فایل موقت
                cleanup_file(file_path)

                last_processed_id = update.update_id + 1

        except Exception as e:
            log.error(f"❌ خطا در حلقه اصلی: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
