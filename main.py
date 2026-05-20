import os
import time
import sqlite3
import requests
from telegram import Bot
from rubpy import Client
from dotenv import load_dotenv

# بارگذاری تنظیمات
if not os.path.exists(".env"):
    print("❌ فایل .env پیدا نشد! ابتدا دستور python setup.py را اجرا کنید.")
    exit(1)

load_dotenv()

BALE_TOKEN = os.getenv("BALE_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
RUBIKA_AUTH = os.getenv("RUBIKA_AUTH")

BALE_CHANNEL = os.getenv("BALE_CHANNEL_ID")
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL_ID")
RUBIKA_CHANNEL = os.getenv("RUBIKA_CHANNEL_GUID")

SOURCE = os.getenv("SOURCE_CHANNEL")

# راه‌اندازی ربات‌ها
tg_bot = Bot(token=TELEGRAM_TOKEN)
rubika_client = Client(session="sync_session", auth_token=RUBIKA_AUTH)

# ----------------- بخش پایگاه داده (SQLite) -----------------
def init_db():
    """ساخت جدول دیتابیس در صورت عدم وجود"""
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_messages (
            id TEXT PRIMARY KEY,
            media_group_id TEXT
        )
    """)
    conn.commit()
    conn.close()

def is_msg_processed(msg_id):
    """بررسی تکراری نبودن پیام"""
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM processed_messages WHERE id = ?", (msg_id,))
    res = cursor.fetchone()
    conn.close()
    return res is not None

def is_media_group_processed(media_group_id):
    """بررسی اینکه آیا عکس اول این آلبوم قبلاً فرستاده شده یا نه"""
    if not media_group_id:
        return False
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM processed_messages WHERE media_group_id = ?", (media_group_id,))
    res = cursor.fetchone()
    conn.close()
    return res is not None

def save_msg(msg_id, media_group_id=None):
    """ذخیره پیام فرستاده شده در دیتابیس"""
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO processed_messages (id, media_group_id) VALUES (?, ?)", (msg_id, media_group_id))
    conn.commit()
    conn.close()
# -----------------------------------------------------------

def download_from_bale(file_id):
    res = requests.get(f"https://api.bale.ai/bot{BALE_TOKEN}/getFile", params={"file_id": file_id}).json()
    if res.get("ok"):
        file_path = res["result"]["file_path"]
        url = f"https://api.bale.ai/file/bot{BALE_TOKEN}/{file_path}"
        filename = file_path.split("/")[-1]
        with requests.get(url, stream=True) as r:
            with open(filename, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192): f.write(chunk)
        return filename
    return None

def send_to_destinations(text, file_path=None, file_type=None, skip_tg=False, skip_bale=False, skip_rubika=False):
    """ارسال هوشمند پست به مقصدهایی که منبع نیستند"""
    
    # ۱. ارسال به تلگرام
    if not skip_tg:
        try:
            if file_type == "photo":
                with open(file_path, 'rb') as f: tg_bot.send_photo(chat_id=TELEGRAM_CHANNEL, photo=f, caption=text)
            elif file_type == "video":
                with open(file_path, 'rb') as f: tg_bot.send_video(chat_id=TELEGRAM_CHANNEL, video=f, caption=text)
            elif text:
                tg_bot.send_message(chat_id=TELEGRAM_CHANNEL, text=text)
            print("✓ به تلگرام فرستاده شد.")
        except Exception as e: print(f"✗ خطا در تلگرام: {e}")

    # ۲. ارسال به بله
    if not skip_bale:
        try:
            url = f"https://api.bale.ai/bot{BALE_TOKEN}"
            if file_type == "photo":
                with open(file_path, 'rb') as f: requests.post(f"{url}/sendPhoto", data={"chat_id": BALE_CHANNEL, "caption": text}, files={"photo": f})
            elif file_type == "video":
                with open(file_path, 'rb') as f: requests.post(f"{url}/sendVideo", data={"chat_id": BALE_CHANNEL, "caption": text}, files={"video": f})
            elif text:
                requests.post(f"{url}/sendMessage", json={"chat_id": BALE_CHANNEL, "text": text})
            print("✓ به بله فرستاده شد.")
        except Exception as e: print(f"✗ خطا در بله: {e}")

    # ۳. ارسال به روبیکا
    if not skip_rubika:
        try:
            if file_type == "photo": rubika_client.send_photo(RUBIKA_CHANNEL, file_path, caption=text)
            elif file_type == "video": rubika_client.send_video(RUBIKA_CHANNEL, file_path, caption=text)
            elif text: rubika_client.send_message(RUBIKA_CHANNEL, text)
            print("✓ به روبیکا فرستاده شد.")
        except Exception as e: print(f"✗ خطا در روبیکا: {e}")

    # حذف فایل موقت
    if file_path and os.path.exists(file_path):
        os.remove(file_path)

# --- بخش مانیتورینگ کانال‌ها ---

def listen_bale():
    offset = None
    print("📡 ربات روی کانال بله قفل شد. در حال مانیتورینگ...")
    while True:
        try:
            res = requests.get(f"https://api.bale.ai/bot{BALE_TOKEN}/getUpdates", params={"timeout": 30, "offset": offset}).json()
            if res.get("ok"):
                for update in res["result"]:
                    offset = update["update_id"] + 1
                    msg = update.get("channel_post")
                    if not msg or str(msg.get("chat", {}).get("username")) != BALE_CHANNEL.replace("@", ""): continue
                    
                    msg_id = f"bale_{msg.get('message_id')}"
                    if is_msg_processed(msg_id): continue
                    
                    media_group_id = msg.get("media_group_id")
                    text = msg.get("caption") or msg.get("text")
                    
                    # مدیریت هوشمند آلبوم: اگر این آلبوم قبلاً دیده شده، کپشن را حذف کن
                    if media_group_id and is_media_group_processed(media_group_id):
                        text = None
                    
                    file_id, file_type = None, None
                    if "photo" in msg:
                        file_id, file_type = msg["photo"][-1]["file_id"], "photo"
                    elif "video" in msg:
                        file_id, file_type = msg["video"]["file_id"], "video"
                        
                    if file_id:
                        f_path = download_from_bale(file_id)
                        if f_path: send_to_destinations(text, f_path, file_type, skip_bale=True)
                    elif text:
                        send_to_destinations(text, skip_bale=True)
                        
                    save_msg(msg_id, media_group_id)
        except Exception as e: time.sleep(5)

def listen_telegram():
    print("📡 ربات روی کانال تلگرام قفل شد. در حال مانیتورینگ...")
    offset = None
    while True:
        try:
            updates = tg_bot.get_updates(offset=offset, timeout=30)
            for u in updates:
                offset = u.update_id + 1
                msg = u.channel_post
                if not msg or str(msg.chat.username) != TELEGRAM_CHANNEL.replace("@", ""): continue
                
                msg_id = f"tg_{msg.message_id}"
                if is_msg_processed(msg_id): continue
                
                media_group_id = msg.media_group_id
                text = msg.caption or msg.text
                
                if media_group_id and is_media_group_processed(media_group_id):
                    text = None
                
                file_path, file_type = None, None
                if msg.photo:
                    file = tg_bot.get_file(msg.photo[-1].file_id)
                    file_path = file.download_to_drive()
                    file_type = "photo"
                elif msg.video:
                    file = tg_bot.get_file(msg.video.file_id)
                    file_path = file.download_to_drive()
                    file_type = "video"
                    
                send_to_destinations(text, file_path, file_type, skip_tg=True)
                save_msg(msg_id, media_group_id)
        except Exception as e: time.sleep(5)

def listen_rubika():
    print("📡 ربات روی کانال روبیکا قفل شد. در حال مانیتورینگ...")
    last_msg_id = None
    while True:
        try:
            messages = rubika_client.get_messages(RUBIKA_CHANNEL)
            if messages:
                latest = messages[0]
                if last_msg_id is None:
                    last_msg_id = latest.message_id
                    continue
                
                if latest.message_id > last_msg_id:
                    last_msg_id = latest.message_id
                    msg_id = f"rubika_{latest.message_id}"
                    if is_msg_processed(msg_id): continue
                    
                    text = latest.text
                    file_path, file_type = None, None
                    
                    if latest.type == "Photo":
                        file_path = rubika_client.download(latest.inline_link)
                        file_type = "photo"
                    elif latest.type == "Video":
                        file_path = rubika_client.download(latest.inline_link)
                        file_type = "video"
                        
                    send_to_destinations(text, file_path, file_type, skip_rubika=True)
                    save_msg(msg_id)
        except Exception as e: pass
        time.sleep(3)

if __name__ == "__main__":
    init_db() # راه‌اندازی دیتابیس
    if SOURCE == "bale": listen_bale()
    elif SOURCE == "telegram": listen_telegram()
    elif SOURCE == "rubika": listen_rubika()
