# ------------------- تابع اصلی (ناهمگام) -------------------

async def main():
    log.info("🚀 ربات همگام‌سازی راه‌اندازی شد.")
    log.info(f"👀 در حال گوش‌دادن به کانال بله: {BALE_CHANNEL}")

    # تست اتصال به بله با دریافت اطلاعات ربات
    try:
        me = await bale_bot.get_me()
        log.info(f"✅ اتصال به بله برقرار شد. ربات: @{me.username}")
    except Exception as e:
        log.error(f"❌ اتصال به بله ناموفق: {e}")
        return

    last_processed_id = None

    while True:
        try:
            # دریافت پیام‌های جدید با await
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
                    # photo – آخرین (بزرگ‌ترین) عکس در لیست است
                    file_id   = msg.photo[-1].file_id
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
                        file_type = None  # از ارسال فایل صرف‌نظر کن

                # ارسال به مقصدها
                send_to_destinations(text, file_path, file_type)

                # به‌روزرسانی last_processed_id
                last_processed_id = update.update_id + 1

        except Exception as e:
            log.error(f"❌ خطا در حلقه اصلی: {e}")
            await asyncio.sleep(5)  # در صورت خطا، ۵ ثانیه صبر کن
