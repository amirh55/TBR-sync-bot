import os
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv

from bale import Bot, Message, InputFile
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

def safe_get(obj, attr, default=None):
    """دریافت امن مقدار از شیء یا دیکشنری (جلوگیری از ارورهای کتابخانه)"""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)

async def download_from_bale(bale_bot_instance, file_id: str, file_type: str) -> str | None:
    """دانلود فایل از بله (ناهمگام و مقاوم در برابر فرمت‌های مختلف خروجی)"""
    try:
        file_info = await bale_bot_instance.get_file(file_id)
        
        file_name = f"{file_type}_{file_id}.file"
        file_path = TEMP_DIR / file_name
        
        with open(file_path, 'wb') as f:
            # حالت ۱: اگر کتابخانه متد save_to_memory داشته باشد
            if hasattr(file_info, 'save_to_memory'):
                await file_info.save_to_memory(f)
            # حالت ۲: اگر متد download داشته باشد
            elif hasattr(file_info, 'download'):
                await file_info.download(str(file_path))
            # حالت ۳: اگر مستقیماً bytes برگردانده باشد
            elif isinstance(file_info, (bytes, bytearray)):
                f.write(file_info)
            # حالت ۴: اگر به صورت دیکشنری حاوی لینک دانلود باشد
            elif isinstance(file_info, dict):
                file_url = file_info.get('file_url') or file_info.get('url')
                if file_url:
                    import aiohttp
                    async with aiohttp.ClientSession() as session:
                        async with session.get(file_url) as resp:
                            if resp.status == 200:
                                f.write(await resp.read())
                            else:
                                raise Exception(f"خطا در دانلود از URL: {resp.status}")
                else:
                    raise Exception("لینک دانلود در فایل پیدا نشد.")
            else:
                raise Exception(f"فرمت ناشناخته برای file_info: {type(file_info)}")
            
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
                with open(file_path, 'rb') as f:
                    input_file = InputFile(f)
                    if file_type == "photo":
                        await bale_bot_instance.send_photo(BALE_CHANNEL, input_file, caption=text)
                    elif file_type == "video":
                        await bale_bot_instance.send_video(BALE_CHANNEL, input_file, caption=text)
                    elif file_type == "document":
                        await bale_bot_instance.send_document(BALE_CHANNEL, input_file, caption=text)
                    elif file_type == "animation":
                        await bale_bot_instance.send_animation(BALE_CHANNEL, input_file, caption=text)
                    elif file_type == "audio":
                        await bale_bot_instance.send_audio(BALE_CHANNEL, input_file, caption=text)
            else:
                await bale_bot_instance.send_message(BALE_CHANNEL, text)
        except Exception as e:
            log.error(f"❌ خطا در ارسال به بله: {e}")

    # ارسال به تلگرام
    if TELEGRAM_CHANNEL:
        try:
            if file_path and file_type:
                with open(file_path, 'rb') as f:
                    if file_type == "photo":
                        await telegram_bot_instance.send_photo(TELEGRAM_CHANNEL, f, caption=text)
                    elif file_type == "video":
                        await telegram_bot_instance.send_video(TELEGRAM_CHANNEL, f, caption=text)
                    elif file_type == "document":
                        await telegram_bot_instance.send_document(TELEGRAM_CHANNEL, f, caption=text)
                    elif file_type == "animation":
                        await telegram_bot_instance.send_animation(TELEGRAM_CHANNEL, f, caption=text)
                    elif file_type == "audio":
                        await telegram_bot_instance.send_audio(TELEGRAM_CHANNEL, f, caption=text)
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

    async with Bot(token=BALE_TOKEN) as bale_bot, TgBot(token=TELEGRAM_TOKEN) as telegram_bot:
        
        try:
            me = await bale_bot.get_me()
            log.info(f"✅ اتصال به بله برقرار شد. ربات: @{safe_get(me, 'username')}")
        except Exception as e:
            log.error(f"❌ اتصال به بله ناموفق: {e}")
            log.error("لطفاً توکن BALE_TOKEN را بررسی کنید.")
            return

        last_processed_id = None

        while True:
            try:
                updates = await bale_bot.get_updates(offset=last_processed_id)

                if not updates:
                    await asyncio.sleep(1)
                    continue

                for update in updates:
                    msg = safe_get(update, 'message')
                    if not msg:
                        continue

                    # بررسی فرستنده (با استفاده از safe_get برای جلوگیری از ارور dict)
                    from_user = safe_get(msg, 'from_user')
                    if from_user and safe_get(from_user, 'is_bot'):
                        continue

                    # بررسی نوع چت
                    chat = safe_get(msg, 'chat')
                    if safe_get(chat, 'type') != "channel":
                        continue

                    log.info(f"📩 پیام جدید از کانال بله دریافت شد.")

                    text = safe_get(msg, 'text') or safe_get(msg, 'caption') or ""
                    file_id = None
                    file_type = None
                    file_path = None

                    # استخراج فایل‌ها با safe_get
                    photos = safe_get(msg, 'photos')
                    video = safe_get(msg, 'video')
                    document = safe_get(msg, 'document')
                    animation = safe_get(msg, 'animation')
                    audio = safe_get(msg, 'audio')

                    if photos:
                        file_id = safe_get(photos[-1], 'file_id')
                        file_type = "photo"
                    elif video:
                        file_id = safe_get(video, 'file_id')
                        file_type = "video"
                    elif document:
                        file_id = safe_get(document, 'file_id')
                        file_type = "document"
                    elif animation:
                        file_id = safe_get(animation, 'file_id')
                        file_type = "animation"
                    elif audio:
                        file_id = safe_get(audio, 'file_id')
                        file_type = "audio"

                    if file_id:
                        file_path = await download_from_bale(bale_bot, file_id, file_type)
                        if not file_path:
                            log.warning("⚠️ دانلود فایل ناموفق بود، فقط متن ارسال می‌شود.")

                    await send_to_destinations(bale_bot, telegram_bot, text, file_path, file_type)

                    last_processed_id = safe_get(update, 'update_id') + 1

            except Exception as e:
                log.error(f"❌ خطا در حلقه اصلی: {e}")
                await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
