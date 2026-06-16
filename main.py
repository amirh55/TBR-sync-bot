import os
import time
import logging
from pathlib import Path
from dotenv import load_dotenv

# کتابخانه‌های مربوط به بله و تلگرام
from bale import Bot, Message, File  # کتابخانه رسمی بله
from telegram import Bot as TgBot    # کتابخانه تلگرام (تغییر نام برای جلوگیری از تداخل)
from telegram.error import TelegramError

# تنظیمات لاگ‌گیری
logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# بارگذاری متغیرهای محیطی از فایل .env
load_dotenv()

# ------------------- خواندن تنظیمات از محیط -------------------
BALE_TOKEN = os.getenv("BALE_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
BALE_CHANNEL = os.getenv("BALE_CHANNEL")      # آیدی عددی کانال بله
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL")  # آیدی عددی کانال تلگرام
RUBIKA_CHANNEL = os.getenv("RUBIKA_CHANNEL")    # اگر از روبیکا هم استفاده می‌کنید

# بررسی وجود توکن‌ها
if not BALE_TOKEN:
    log.error("توکن بله در فایل .env پیدا نشد!")
    exit(1)
if not TELEGRAM_TOKEN:
    log.error("توکن تلگرام در فایل .env پیدا نشد!")
    exit(1)

# ایجاد نمونه از ربات‌ها
bale_bot = Bot(token=BALE_TOKEN)
telegram_bot = TgBot(token=TELEGRAM_TOKEN)

# دایرکتوری موقت برای ذخیره فایل‌های دانلودی
TEMP_DIR = Path("temp_downloads")
TEMP_DIR.mkdir(exist_ok=True)

# ------------------- توابع کمکی -------------------

def download_from_bale(file_id: str) -> str | None:
    """
    دانلود فایل از بله با استفاده از کتابخانه رسمی.
    مسیر فایل دانلود شده را برمی‌گرداند.
    """
    try:
        file_info = bale_bot.get_file(file_id)
        # متد download_file در python-bale-bot فایل را در مسیر فعلی ذخیره می‌کند
        # برای ذخیره در دایرکتوری موقت، مسیر را مشخص می‌کنیم
        file_path = TEMP_DIR / file_info.file_name
        file_info.download(file_path)
        log.info(f"فایل از بله دانلود شد: {file_path}")
        return str(file_path)
    except Exception as e:
        log.error(f"خطا در دانلود از بله: {e}")
        return None

def send_to_destinations(text: str, file_path: str = None, file_type: str = None):
    """
    ارسال پیام (متن یا فایل) به تمام کانال‌های مقصد (بله، تلگرام، روبیکا).
    """
    # ------------------- ارسال به بله -------------------
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
                # بعد از ارسال، فایل موقت را پاک می‌کنیم
                os.remove(file_path)
            else:
                bale_bot.send_message(BALE_CHANNEL, text)
            log.info("✅ پیام به کانال بله ارسال شد.")
        except Exception as e:
            log.error(f"❌ خطا در ارسال به بله: {e}")

    # ------------------- ارسال به تلگرام -------------------
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
                # فایل قبلاً توسط بخش بله حذف شده، اما اگر بله فعال نبود، اینجا حذف می‌شود
                if os.path.exists(file_path):
                    os.remove(file_path)
            else:
                telegram_bot.send_message(TELEGRAM_CHANNEL, text)
            log.info("✅ پیام به کانال تلگرام ارسال شد.")
        except TelegramError as e:
            log.error(f"❌ خطا در ارسال به تلگرام: {e}")

    # ------------------- ارسال به روبیکا (اختیاری) -------------------
    if RUBIKA_CHANNEL:
        # اگر از rubpy برای روبیکا استفاده می‌کنید، کد مربوطه را اینجا اضافه کنید.
        # اما پیشنهاد می‌کنم از کتابخانه‌ی رسمی روبیکا هم استفاده کنید.
        pass

# ------------------- تابع اصلی (Polling) -------------------

def main():
    log.info("🚀 ربات همگام‌سازی راه‌اندازی شد.")
    log.info(f"👀 در حال گوش‌دادن به کانال بله: {BALE_CHANNEL}")

    # آخرین آیدی پیام پردازش‌شده (برای جلوگیری از پردازش مجدد)
    last_processed_id = None

    while True:
        try:
            # دریافت پیام‌های جدید از کانال بله
            # توجه: در python-bale-bot متد get_updates وجود دارد
            updates = bale_bot.get_updates(offset=last_processed_id, timeout=30)
            
            for update in updates:
                # فقط پیام‌های جدید را پردازش کن
                if update.message:
                    msg = update.message
                    
                    # اگر پیام از خود ربات باشد، نادیده بگیر (برای جلوگیری از حلقه)
                    if msg.from_user.is_bot:
                        continue

                    # ذخیره‌ی متن پیام
                    text = msg.text or msg.caption or ""
                    
                    # متغیرهای مربوط به فایل
                    file_id = None
                    file_type = None
                    file_path = None

                    # بررسی نوع محتوای پیام (عکس، ویدیو، سند، متن)
                    if msg.photo:
                        file_id = msg.photo[-1].file_id   # آخرین (بهترین کیفیت)
                        file_type = "photo"
                    elif msg.video:
                        file_id = msg.video.file_id
                        file_type = "video"
                    elif msg.document:
                        file_id = msg.document.file_id
                        file_type = "document"
                    
                    # اگر فایل وجود داشت، آن را دانلود کن
                    if file_id:
                        file_path = download_from_bale(file_id)
                        if not file_path:
                            log.warning("دانلود فایل ناموفق بود، فقط متن ارسال می‌شود.")
                    
                    # ارسال به تمام مقصدها
                    send_to_destinations(text, file_path, file_type)
                    
                    # به‌روزرسانی last_processed_id
                    last_processed_id = update.update_id + 1

        except Exception as e:
            log.error(f"خطا در حلقه اصلی: {e}")
            time.sleep(5)  # در صورت خطا، ۵ ثانیه صبر کن و دوباره تلاش کن

if __name__ == "__main__":
    main()
