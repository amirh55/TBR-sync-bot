import os
import time
import sqlite3
import logging
import threading
import requests
from telegram import Bot
from rubpy import Client
from dotenv import load_dotenv

# ===================== راه‌اندازی لاگینگ =====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ===================== بارگذاری تنظیمات =====================
if not os.path.exists(".env"):
    log.error("فایل .env پیدا نشد! ابتدا دستور python setup.py را اجرا کنید.")
    exit(1)

load_dotenv()

BALE_TOKEN       = os.getenv("BALE_TOKEN")
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
RUBIKA_AUTH      = os.getenv("RUBIKA_AUTH")
BALE_CHANNEL     = os.getenv("BALE_CHANNEL_ID")
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL_ID")
RUBIKA_CHANNEL   = os.getenv("RUBIKA_CHANNEL_GUID")
SOURCE           = os.getenv("SOURCE_CHANNEL")

# ===================== پایگاه داده (SQLite) =====================
# یک connection سراسری با thread-safety برای جلوگیری از باز/بسته کردن مکرر
_db_lock = threading.Lock()
_db_conn: sqlite3.Connection = None

def get_db() -> sqlite3.Connection:
    global _db_conn
    if _db_conn is None:
        _db_conn = sqlite3.connect("bot_database.db", check_same_thread=False)
        _db_conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_messages (
                id            TEXT PRIMARY KEY,
                media_group_id TEXT
            )
        """)
        _db_conn.commit()
        log.info("دیتابیس راه‌اندازی شد.")
    return _db_conn

def is_msg_processed(msg_id: str) -> bool:
    with _db_lock:
        cur = get_db().execute(
            "SELECT 1 FROM processed_messages WHERE id = ?", (msg_id,)
        )
        return cur.fetchone() is not None

def is_media_group_processed(media_group_id: str) -> bool:
    if not media_group_id:
        return False
    with _db_lock:
        cur = get_db().execute(
            "SELECT 1 FROM processed_messages WHERE media_group_id = ?",
            (media_group_id,)
        )
        return cur.fetchone() is not None

def save_msg(msg_id: str, media_group_id: str = None):
    with _db_lock:
        get_db().execute(
            "INSERT OR IGNORE INTO processed_messages (id, media_group_id) VALUES (?, ?)",
            (msg_id, media_group_id)
        )
        get_db().commit()

# ===================== دانلود از بله =====================
def download_from_bale(file_id: str) -> str | None:
    try:
        res = requests.get(
            f"https://api.bale.ai/bot{BALE_TOKEN}/getFile",
            params={"file_id": file_id},
            timeout=30
        ).json()
        if not res.get("ok"):
            log.warning(f"بله getFile ناموفق: {res}")
            return None
        file_path = res["result"]["file_path"]
        url = f"https://api.bale.ai/file/bot{BALE_TOKEN}/{file_path}"
        filename = file_path.split("/")[-1]
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(filename, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return filename
    except Exception as e:
        log.error(f"خطا در دانلود از بله: {e}")
        return None

# ===================== ارسال به مقصدها =====================
def send_to_destinations(
    text: str,
    file_path: str = None,
    file_type: str = None,
    skip_tg: bool = False,
    skip_bale: bool = False,
    skip_rubika: bool = False
):
    """ارسال پست به مقصدهایی که منبع نیستند — فایل موقت همیشه پاک می‌شود."""
    try:
        # ۱. تلگرام
        if not skip_tg:
            try:
                tg_bot = Bot(token=TELEGRAM_TOKEN)
                if file_type == "photo":
                    with open(file_path, "rb") as f:
                        tg_bot.send_photo(chat_id=TELEGRAM_CHANNEL, photo=f, caption=text)
                elif file_type == "video":
                    with open(file_path, "rb") as f:
                        tg_bot.send_video(chat_id=TELEGRAM_CHANNEL, video=f, caption=text)
                elif text:
                    tg_bot.send_message(chat_id=TELEGRAM_CHANNEL, text=text)
                log.info("✓ به تلگرام ارسال شد.")
            except Exception as e:
                log.error(f"✗ خطا در تلگرام: {e}")

        # ۲. بله
        if not skip_bale:
            try:
                url = f"https://api.bale.ai/bot{BALE_TOKEN}"
                if file_type == "photo":
                    with open(file_path, "rb") as f:
                        requests.post(
                            f"{url}/sendPhoto",
                            data={"chat_id": BALE_CHANNEL, "caption": text or ""},
                            files={"photo": f},
                            timeout=60
                        )
                elif file_type == "video":
                    with open(file_path, "rb") as f:
                        requests.post(
                            f"{url}/sendVideo",
                            data={"chat_id": BALE_CHANNEL, "caption": text or ""},
                            files={"video": f},
                            timeout=60
                        )
                elif text:
                    requests.post(
                        f"{url}/sendMessage",
                        json={"chat_id": BALE_CHANNEL, "text": text},
                        timeout=30
                    )
                log.info("✓ به بله ارسال شد.")
            except Exception as e:
                log.error(f"✗ خطا در بله: {e}")

        # ۳. روبیکا — یک client ثابت در کل برنامه (نه باز/بسته در هر بار)
        if not skip_rubika:
            try:
                with Client(session="sync_session", auth_token=RUBIKA_AUTH) as bot:
                    if file_type in ("photo", "video"):
                        bot.send_file(RUBIKA_CHANNEL, file_path, caption=text)
                    elif text:
                        bot.send_message(RUBIKA_CHANNEL, text)
                log.info("✓ به روبیکا ارسال شد.")
            except Exception as e:
                log.error(f"✗ خطا در روبیکا: {e}")

    finally:
        # حذف فایل موقت در هر صورت (موفق یا ناموفق)
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                log.warning(f"نتوانست فایل موقت را حذف کند: {e}")

# ===================== مانیتورینگ بله =====================
def listen_bale():
    offset = None
    log.info("📡 ربات روی کانال بله قفل شد. در حال مانیتورینگ...")
    bale_username = BALE_CHANNEL.replace("@", "")

    while True:
        try:
            res = requests.get(
                f"https://api.bale.ai/bot{BALE_TOKEN}/getUpdates",
                params={"timeout": 30, "offset": offset},
                timeout=40
            ).json()

            if not res.get("ok"):
                log.warning(f"پاسخ غیرمنتظره از بله: {res}")
                time.sleep(5)
                continue

            for update in res["result"]:
                offset = update["update_id"] + 1
                msg = update.get("channel_post")
                if not msg:
                    continue
                if str(msg.get("chat", {}).get("username")) != bale_username:
                    continue

                msg_id = f"bale_{msg.get('message_id')}"
                if is_msg_processed(msg_id):
                    continue

                media_group_id = msg.get("media_group_id")
                text = msg.get("caption") or msg.get("text")

                # جلوگیری از race condition: اول ذخیره، بعد ارسال کپشن
                caption_already_sent = media_group_id and is_media_group_processed(media_group_id)
                if caption_already_sent:
                    text = None

                file_id, file_type = None, None
                if "photo" in msg:
                    file_id  = msg["photo"][-1]["file_id"]
                    file_type = "photo"
                elif "video" in msg:
                    file_id  = msg["video"]["file_id"]
                    file_type = "video"

                # ذخیره قبل از ارسال تا race condition آلبوم حل شود
                save_msg(msg_id, media_group_id)

                if file_id:
                    f_path = download_from_bale(file_id)
                    if f_path:
                        send_to_destinations(text, f_path, file_type, skip_bale=True)
                elif text:
                    send_to_destinations(text, skip_bale=True)

        except requests.exceptions.RequestException as e:
            log.error(f"خطای شبکه در بله: {e}")
            time.sleep(5)
        except Exception as e:
            log.error(f"خطای ناشناخته در listen_bale: {e}")
            time.sleep(5)

# ===================== مانیتورینگ تلگرام =====================
def listen_telegram():
    log.info("📡 ربات روی کانال تلگرام قفل شد. در حال مانیتورینگ...")
    tg_bot = Bot(token=TELEGRAM_TOKEN)
    offset = None
    tg_username = TELEGRAM_CHANNEL.replace("@", "")

    while True:
        try:
            updates = tg_bot.get_updates(offset=offset, timeout=30)
            for u in updates:
                offset = u.update_id + 1
                msg = u.channel_post
                if not msg:
                    continue
                if str(msg.chat.username) != tg_username:
                    continue

                msg_id = f"tg_{msg.message_id}"
                if is_msg_processed(msg_id):
                    continue

                media_group_id = msg.media_group_id
                text = msg.caption or msg.text

                caption_already_sent = media_group_id and is_media_group_processed(media_group_id)
                if caption_already_sent:
                    text = None

                # ذخیره قبل از ارسال
                save_msg(msg_id, media_group_id)

                file_path, file_type = None, None
                if msg.photo:
                    tg_file = tg_bot.get_file(msg.photo[-1].file_id)
                    file_path = tg_file.download_to_drive()
                    file_type = "photo"
                elif msg.video:
                    tg_file = tg_bot.get_file(msg.video.file_id)
                    file_path = tg_file.download_to_drive()
                    file_type = "video"

                send_to_destinations(text, file_path, file_type, skip_tg=True)

        except Exception as e:
            log.error(f"خطا در listen_telegram: {e}")
            time.sleep(5)

# ===================== مانیتورینگ روبیکا =====================
def listen_rubika():
    log.info("📡 ربات روی کانال روبیکا قفل شد. در حال مانیتورینگ...")
    last_msg_id = None

    while True:
        try:
            with Client(session="sync_session", auth_token=RUBIKA_AUTH) as bot:
                messages = bot.get_messages(RUBIKA_CHANNEL)
                if not messages:
                    time.sleep(3)
                    continue

                latest = messages[0]

                # اولین بار فقط ID رو ذخیره می‌کنیم، پیامی نمی‌فرستیم
                if last_msg_id is None:
                    last_msg_id = latest.message_id
                    log.info(f"روبیکا: آخرین پیام موجود = {last_msg_id}")
                    time.sleep(3)
                    continue

                if latest.message_id <= last_msg_id:
                    time.sleep(3)
                    continue

                last_msg_id = latest.message_id
                msg_id = f"rubika_{latest.message_id}"

                if is_msg_processed(msg_id):
                    time.sleep(3)
                    continue

                text = latest.text
                file_path, file_type = None, None

                if latest.type == "Photo":
                    file_path = bot.download(latest.inline_link)
                    file_type = "photo"
                elif latest.type == "Video":
                    file_path = bot.download(latest.inline_link)
                    file_type = "video"

                # ذخیره قبل از ارسال
                save_msg(msg_id)
                send_to_destinations(text, file_path, file_type, skip_rubika=True)

        except Exception as e:
            log.error(f"خطا در listen_rubika: {e}")

        time.sleep(3)

# ===================== نقطه ورود =====================
if __name__ == "__main__":
    get_db()  # راه‌اندازی دیتابیس

    if SOURCE == "bale":
        listen_bale()
    elif SOURCE == "telegram":
        listen_telegram()
    elif SOURCE == "rubika":
        listen_rubika()
    else:
        log.error(f"SOURCE_CHANNEL نامعتبر است: '{SOURCE}'. باید bale، telegram یا rubika باشد.")
        exit(1)
