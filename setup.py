import subprocess
import sys


def install_requirements():
    print("در حال نصب کتابخانه‌های مورد نیاز...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✅ کتابخانه‌ها نصب شدند.\n")
    except subprocess.CalledProcessError as e:
        print(f"❌ خطا در نصب کتابخانه‌ها: {e}")
        sys.exit(1)


def create_env():
    print("======= تنظیمات TBR Sync Bot =======\n")
    bale_token = input("توکن ربات بله: ").strip()
    telegram_token = input("توکن ربات تلگرام: ").strip()
    bale_channel_id = input("آیدی کانال بله با @: ").strip()
    telegram_channel_id = input("آیدی کانال تلگرام با @: ").strip()

    env_content = f"""bale_token={bale_token}
telegram_token={telegram_token}

bale_channel_id={bale_channel_id}
telegram_channel_id={telegram_channel_id}

bale_username_to_replace={bale_channel_id}
telegram_username_replacement={telegram_channel_id}

sync_old_messages=false
poll_timeout=25
"""
    with open(".env", "w", encoding="utf-8") as f:
        f.write(env_content)

    print("\n✅ فایل .env ساخته شد.")
    print("برای اجرا: python main.py")


if __name__ == "__main__":
    install_requirements()
    create_env()
