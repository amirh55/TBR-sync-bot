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

BALE_TOKEN = os.getenv("BALE_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
BALE_CHANNEL = os.getenv("BALE_CHANNEL")
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL")

if not BALE_TOKEN or not TELEGRAM_TOKEN or not BALE_CHANNEL:
    log.error("❌ توکن‌ها یا آیدی کانال بله در فایل .env تنظیم نشده‌اند!")
    exit(1)

# دایرکتوری موقت
TEMP_DIR = Path("temp_downloads")
TEMP_DIR.mkdir(exist_ok=True)

# ایجاد نمونه از ربات‌ها
bale_bot = Bot(token=BALE_TOKEN)
telegram_bot = TgBot(token=TELEGRAM_TOKEN)

# ------------------- توابع کمکی -------------------

async def download_from_bale(file_id: str, file_type: str) -> str | None:
    """دانلود فایل از بله (ناهمگام)"""
    try:
        # در python-bale-bot متد get_file مستقیماً محتوای فایل را به صورت bytes برمی‌گرداند [[2]]
        file_bytes = await bale_bot.get_file(file_id)
        
        file_name = f"{file_type}_{file_id}.file"
        file_path = TEMP_DIR / file_name
        
        with open(file_path, 'wb') as f:
            f.write(file_bytes)
            
        log.info(f"📥 فایل از بله دانلود شد: {file_path}")
        return str(file_path)
    except Exception as e:
        log.error(f"❌ خطا در دانلود از بله: {e}")
        return None

async def send_to_telegram(text: str, file_path: str = None, file_type: str = None):
    """ارسال پیام به کانال تلگرام"""
    if not TELEGRAM_CHANNEL:
        return
        
    try:
        if file_path and file_type:
            # در python-telegram-bot v20 بهترین راه ارسال فایل، پاس دادن آبجکت file باز شده است
            with open(file_path, 'rb') as f:
                if file_type == "photo":
                    await telegram_bot.send_photo(chat_id=TELEGRAM_CHANNEL, photo=f, caption=text)
                elif file_type == "video":
                    await telegram_bot.send_video(chat_id=TELEGRAM_CHANNEL, video=f, caption=text)
                elif file_type == "document":
                    await telegram_bot.send_document(chat_id=TELEGRAM_CHANNEL, document=f, caption=text)
                elif file_type == "audio":
                    await telegram_bot.send_audio(chat_id=TELEGRAM_CHANNEL, audio=f, caption=text)
        else:
            await telegram_bot.send_message(chat_id=TELEGRAM_CHANNEL, text=text)
        log.info("✅ پیام با موفقیت به تلگرام ارسال شد.")
    except TelegramError as e:
        log.error(f"❌ خطا در ارسال به تلگرام: {e}")
    except Exception as e:
        log.error(f"❌ خطای غیرمنتظره در ارسال به تلگرام: {e}")

# ------------------- مدیریت رویدادها -------------------

@bale_bot.event
async def on_message(message: Message):
    """مدیریت پیام‌های دریافتی از بله (روش استاندارد python-bale-bot) [[2]]"""
    # فقط پیام‌های کانال هدف را پردازش کن (تبدیل به str برای جلوگیری از ارور مقایسه int و str)
    if str(message.chat.id) != str(BALE_CHANNEL):
        return
        
    # نادیده گرفتن پیام‌های ارسالی توسط خود ربات (برای جلوگیری از لوپ بی‌نهایت)
    if message.author and hasattr(bale_bot, 'user') and bale_bot.user and message.author.user_id == bale_bot.user.user_id:
        return

    log.info(f"📩 پیام جدید از کانال بله دریافت شد.")

    text = message.text or message.caption or ""
    file_id = None
    file_type = None
    file_path = None

    # تشخیص نوع فایل بر اساس داکیومنت رسمی python-bale-bot [[1]]
    if message.photos:  # دقت کنید که photos به صورت جمع (لیست) است
        file_id = message.photos[-1].file_id
        file_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        file_type = "video"
    elif message.document:
        file_id = message.document.file_id
        file_type = "document"
    elif message.audio:
        file_id = message.audio.file_id
        file_type = "audio"

    # دانلود فایل (در صورت وجود)
    if file_id:
        file_path = await download_from_bale(file_id, file_type)
        if not file_path:
            log.warning("⚠️ دانلود فایل ناموفق بود، فقط متن ارسال می‌شود.")

    # ارسال به تلگرام
    await send_to_telegram(text, file_path, file_type)

    # پاک کردن فایل موقت پس از ارسال
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            log.warning(f"⚠️ خطا در حذف فایل موقت: {e}")

# ------------------- اجرای اصلی -------------------

async def main():
    log.info("🚀 ربات همگام‌سازی راه‌اندازی شد.")
    log.info(f"👀 در حال گوش‌دادن به کانال بله: {BALE_CHANNEL}")

    try:
        me = await bale_bot.get_me()
        bot_name = getattr(me, 'username', None) or getattr(me, 'first_name', 'Unknown')
        log.info(f"✅ اتصال به بله برقرار شد. ربات: @{bot_name}")
    except Exception as e:
        log.error(f"❌ اتصال به بله ناموفق: {e}")
        log.error("لطفاً توکن BALE_TOKEN را بررسی کنید.")
        return

    # شروع ربات بله (این تابع رویدادها را به صورت خودکار گوش می‌دهد) [[2]]
    await bale_bot.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("🛑 ربات متوقف شد.")
