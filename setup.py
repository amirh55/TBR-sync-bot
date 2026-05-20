import os
import subprocess
import sys

def install_requirements():
    print("🔄 در حال نصب کتابخانه‌های مورد نیاز...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✅ تمام کتابخانه‌ها با موفقیت نصب شدند.\n")
    except Exception as e:
        print(f"❌ خطا در نصب کتابخانه‌ها: {e}")
        sys.exit(1)

def get_user_inputs():
    print("======= تنظیمات ربات سینک‌کننده کانال‌ها =======")
    
    # دریافت توکن‌ها
    bale_token = input("🔑 توکن ربات بله (Bale Bot Token) را وارد کنید: ").strip()
    tg_token = input("🔑 توکن ربات تلگرام (Telegram Bot Token) را وارد کنید: ").strip()
    rubika_auth = input("🔑 توکن اکانت روبیکا (Rubika Auth Token) را وارد کنید: ").strip()
    
    print("\n======= تنظیمات آیدی کانال‌ها =======")
    print("(نکته: آیدی کانال‌های تلگرام و بله را با @ وارد کنید، برای روبیکا GUID کانال را بزنید)")
    bale_chat = input("📢 آیدی کانال بله: ").strip()
    tg_chat = input("📢 آیدی کانال تلگرام: ").strip()
    rubika_chat = input("📢 جی‌یو‌آی (GUID) کانال روبیکا: ").strip()
    
    print("\n======= تعیین کانال منبع (Source) =======")
    print("ربات پیام‌ها را از کدام کانال بردارد و در بقیه کپی کند؟")
    print("1) بله (Bale)")
    print("2) تلگرام (Telegram)")
    print("3) روبیکا (Rubika)")
    
    source_choice = input("👉 عدد گزینه مورد نظر را انتخاب کنید (1 یا 2 یا 3): ").strip()
    
    source_channel = "bale"
    if source_choice == "2":
        source_channel = "telegram"
    elif source_choice == "3":
        source_channel = "rubika"
        
    # ساخت فایل .env
    env_content = f"""BALE_TOKEN={bale_token}
TELEGRAM_TOKEN={tg_token}
RUBIKA_AUTH={rubika_auth}

BALE_CHANNEL_ID={bale_chat}
TELEGRAM_CHANNEL_ID={tg_chat}
RUBIKA_CHANNEL_GUID={rubika_chat}

SOURCE_CHANNEL={source_channel}
"""
    
    with open(".env", "w", encoding="utf-8") as f:
        f.write(env_content)
        
    print("\n✅ فایل تنظیمات (.env) با موفقیت ساخته شد!")

if __name__ == "__main__":
    # ۱. نصب پیش‌نیازها
    install_requirements()
    # ۲. دریافت اطلاعات و ساخت کانفیگ
    get_user_inputs()
    
    print("\n🚀 تنظیمات تمام شد. اکنون می‌توانید ربات را با دستور زیر اجرا کنید:")
    print("python main.py")
