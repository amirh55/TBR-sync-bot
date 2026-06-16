import os
import logging
from pathlib import Path
from dotenv import load_dotenv

from bale import Bot, Message, Updater
from bale.handlers import MessageHandler, Filters
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

# ایجاد نمونه از ربات‌ها
bale_bot = Bot(token=BALE_TOKEN)
telegram_bot = TgBot(token=TELEGRAM_TOKEN)

# دایرکتوری موقت
TEMP_DIR = Path("temp_downloads")
TEMP_DIR.mkdir(exist_ok=True)

# ------------------- توابع کمکی -------------------

def download_from_bale(file_id: str) -> str | None:
    """دانلود فایل از بله"""
    try:
        file_info = bale_bot.get_file(file_id)
        file_path = TEMP_DIR / file_info.file_name
        file_info.download(file_path)
        log.info(f"📥 فایل از بله دانلود شد: {file_path}")
        return str(file_path)
    except Exception as e:
        log.error(f"❌ خطا در دانلود از بله: {e}")
        return None

def send_to_destinations(text: str, file_path: str = None, file_type: str = None):
    """ارسال پیام به تمام مقصدها"""
    # ارسال به بله
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
                os.remove(file_path)
            else:
                bale_bot.send_message(BALE_CHANNEL, text)
            log.info("✅ پیام به کانال بله ارسال شد.")
        except Exception as e:
            log.error(f"❌ خطا در ارسال به بله: {e}")

    # ارسال به تلگرام
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
                    os.remove(file_path)
            else:
                telegram_bot.send_message(TELEGRAM_CHANNEL, text)
            log.info("✅ پیام به کانال تلگرام ارسال شد.")
        except TelegramError as e:
            log.error(f"❌ خطا در ارسال به تلگرام: {e}")

# ------------------- تابع پردازش پیام -------------------

def handle_message(update, context):
    """پردازش پیام‌های جدید از کانال بله"""
    msg = update.message
    if not msg or msg.from_user.is_bot:
        return

    # فقط پیام‌های کانال را پردازش کن (نه پیام‌های خصوصی)
    if msg.chat.type != "channel":
        return

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

    # دانلود فایل (اگر وجود داشته باشد)
    if file_id:
        file_path = download_from_bale(file_id)
        if not file_path:
            log.warning("⚠️ دانلود فایل ناموفق بود، فقط متن ارسال می‌شود.")

    # ارسال به مقصدها
    send_to_destinations(text, file_path, file_type)

# ------------------- تابع اصلی -------------------

def main():
    log.info("🚀 ربات همگام‌سازی راه‌اندازی شد.")
    log.info(f"👀 در حال گوش‌دادن به کانال بله: {BALE_CHANNEL}")

    # ایجاد Updater
    updater = Updater(token=BALE_TOKEN)
    dp = updater.dispatcher

    # افزودن هندلر برای پیام‌های کانال
    dp.add_handler(MessageHandler(Filters.chat_type.channel, handle_message))

    # شروع polling
    updater.start_polling()
    log.info("✅ ربات در حال اجرا است. برای توقف Ctrl+C را بزنید.")
    updater.idle()

if __name__ == "__main__":
    main()
