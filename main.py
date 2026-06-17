import os
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv

from bale import Bot, Message
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

# ------------------- توابع کمکی -------------------

async def download_from_bale(bale_bot_instance, file_id: str, file_type: str) -> str | None:
    """دانلود فایل از بله (ناهمگام)"""
    try:
        # در python-bale-bot متد get_file محتوای فایل را به صورت bytes برمی‌گرداند
        file_bytes = await bale_bot_instance.get_file(file_id)
        
        # ساخت نام فایل موقت
        file_name = f"{file_type}_{file_id}.file"
        file_path = TEMP_DIR / file_name
        
        # ذخیره bytes در فایل
        with open(file_path, 'wb') as f:
            f.write(file_bytes)
            
        log.info(f"📥 فایل از بله دانلود شد: {file_path}")
        return str(file_path)
    except Exception as e:
        log.error(f"❌ خطا در دانلود از بله: {e}")
        return None

async def send_to_destinations(bale_bot_instance, telegram_bot_instance, text: str, file_path: str = None, file_type: str = None):
    """ارسال پیام به تمام مقصدها (ناهمگام)"""
    # ارسال به بله
    if BALE_CHANNEL:
        try:
            if file_path and file_type:
                # کتابخانه بله خودش فایل را از روی مسیر باز می‌کند
                if file_type == "photo":
                    await bale_bot_instance.send_photo(BALE_CHANNEL, file_path, caption=text)
                elif file_type == "video":
                    await bale_bot_instance.send_video(BALE_CHANNEL, file_path, caption=text)
                elif file_type == "document":
                    await bale_bot_instance.send_document(BALE_CHANNEL, file_path, caption=text)
            else:
                await bale_bot_instance.send_message(BALE_CHANNEL, text)
        except Exception as e:
            log.error(f"❌ خطا در ارسال به بله: {e}")

    # ارسال به تلگرام
    if TELEGRAM_CHANNEL:
        try:
            if file_path and file_type:
                if file_type == "photo":
                    await telegram_bot_instance.send_photo(TELEGRAM_CHANNEL, file_path, caption=text)
                elif file_type == "video":
                    await telegram_bot_instance.send_video(TELEGRAM_CHANNEL, file_path, caption=text)
                elif file_type == "document":
                    await telegram_bot_instance.send_document(TELEGRAM_CHANNEL, file_path, caption=text)
            else:
                await telegram_bot_instance.send_message(TELEGRAM_CHANNEL, text)
        except TelegramError as e:
            log.error(f"❌ خطا در ارسال به تلگرام: {e}")
            
    # پاک کردن فایل موقت پس از ارسال
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            log.warning(f"⚠️ خطا در حذف فایل موقت: {e}")

# ------------------- تابع اصلی (ناهمگام) -------------------

async def main():
    log.info("🚀 ربات همگام‌سازی راه‌اندازی شد.")
    log.info(f"👀 در حال گوش‌دادن به کانال بله: {BALE_CHANNEL}")

    # استفاده از async with برای راه‌اندازی خودکار Session هر دو کتابخانه
    async with Bot(token=BALE_TOKEN) as bale_bot, TgBot(token=TELEGRAM_TOKEN) as telegram_bot:
        
        # تست اتصال به بله با دریافت اطلاعات ربات
        try:
            me = await bale_bot.get_me()
            log.info(f"✅ اتصال به بله برقرار شد. ربات: @{me.username}")
        except Exception as e:
            log.error(f"❌ اتصال به بله ناموفق: {e}")
            log.error("لطفاً توکن BALE_TOKEN را بررسی کنید.")
            return

        last_processed_id = None

        while True:
            try:
                # دریافت پیام‌های جدید (بدون timeout چون این کتابخانه پشتیبانی نمی‌کند)
                updates = await bale_bot.get_updates(offset=last_processed_id)

                if not updates:
                    # اگر پیامی نبود، ۱ ثانیه صبر کنید تا به API فشار نیاید (جلوگیری از Rate Limit)
                    await asyncio.sleep(1)
                    continue

                for update in updates:
                    if not hasattr(update, 'message'):
                        continue

                    msg = update.message
                    if not msg:
                        continue

                    # نادیده گرفتن پیام‌های خود ربات (با چک کردن None بودن from_user برای پیام‌های کانال)
                    if msg.from_user and msg.from_user.is_bot:
                        continue

                    # فقط پیام‌های کانال را پردازش کن
                    if msg.chat.type != "channel":
                        continue

                    log.info(f"📩 پیام جدید از کانال بله دریافت شد.")

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

                    # دانلود فایل (در صورت وجود)
                    if file_id:
                        file_path = await download_from_bale(bale_bot, file_id, file_type)
                        if not file_path:
                            log.warning("⚠️ دانلود فایل ناموفق بود، فقط متن ارسال می‌شود.")

                    # ارسال به مقصدها
                    await send_to_destinations(bale_bot, telegram_bot, text, file_path, file_type)

                    # به‌روزرسانی last_processed_id
                    last_processed_id = update.update_id + 1

            except Exception as e:
                log.error(f"❌ خطا در حلقه اصلی: {e}")
                await asyncio.sleep(5) # در صورت خطا، ۵ ثانیه صبر کن

if __name__ == "__main__":
    asyncio.run(main())
