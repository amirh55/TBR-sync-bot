import os
import subprocess
import sys


def install_requirements():
    print("🔄 در حال نصب کتابخانه‌های مورد نیاز...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]
        )
        print("✅ تمام کتابخانه‌ها با موفقیت نصب شدند.\n")
    except subprocess.CalledProcessError as e:
        print(f"❌ خطا در نصب کتابخانه‌ها: {e}")
        sys.exit(1)


def get_user_inputs():
    print("======= تنظیمات ربات سینک‌کننده کانال‌ها =======\n")

    bale_token  = input("🔑 توکن ربات بله (Bale Bot Token): ").strip()
    tg_token    = input("🔑 توکن ربات تلگرام (Telegram Bot Token): ").strip()
    rubika_auth = input("🔑 توکن اکانت روبیکا (Rubika Auth Token): ").strip()

    print("\n======= آیدی کانال‌ها =======")
    print("(کانال‌های تلگرام و بله را با @ وارد کنید؛ برای روبیکا GUID کانال را بزنید)\n")

    bale_chat   = input("📢 آیدی کانال بله: ").strip()
    tg_chat     = input("📢 آیدی کانال تلگرام: ").strip()
    rubika_chat = input("📢 GUID کانال روبیکا: ").strip()

    print("\n======= تعیین کانال منبع (Source) =======")
    print("ربات پیام‌ها را از کدام کانال بردارد و در بقیه کپی کند?")
    print("  1) بله (Bale)")
    print("  2) تلگرام (Telegram)")
    print("  3) روبیکا (Rubika)")

    while True:
        choice = input("👉 عدد گزینه را وارد کنید (1 / 2 / 3): ").strip()
        if choice in ("1", "2", "3"):
            break
        print("⚠️  لطفاً فقط 1، 2 یا 3 وارد کنید.")

    source_map = {"1": "bale", "2": "telegram", "3": "rubika"}
    source_channel = source_map[choice]

    env_content = (
        f"BALE_TOKEN={bale_token}\n"
        f"TELEGRAM_TOKEN={tg_token}\n"
        f"RUBIKA_AUTH={rubika_auth}\n"
        f"BALE_CHANNEL_ID={bale_chat}\n"
        f"TELEGRAM_CHANNEL_ID={tg_chat}\n"
        f"RUBIKA_CHANNEL_GUID={rubika_chat}\n"
        f"SOURCE_CHANNEL={source_channel}\n"
    )

    with open(".env", "w", encoding="utf-8") as f:
        f.write(env_content)

    print("\n✅ فایل تنظیمات (.env) با موفقیت ساخته شد!")


if __name__ == "__main__":
    install_requirements()
    get_user_inputs()
    print("\n🚀 تنظیمات تمام شد. ربات را با دستور زیر اجرا کنید:")
    print("   python main.py")
