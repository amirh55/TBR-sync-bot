# TBR Sync Bot — نقشه پروژه و گزارش بررسی

> منبع: `github.com/amirh55/TBR-sync-bot` — بررسی‌شده در ۱۴۰۵/۰۵/۲۰ (2026-08-11) روی نسخهٔ `14.0.0`
> این فایل حافظهٔ کاری من روی این پروژه است: معماری واقعی کد + فهرست اولویت‌بندی‌شدهٔ مشکلات.

## وضعیت اصلاحات (نسخهٔ `15.0.0`)

| اولویت | مورد | وضعیت |
|---|---|---|
| P0 | ۱. `setup.py` ویزارد نبود | ✅ `setup_env.py` ساخته شد + `.env.example` |
| P0 | ۲. حلقهٔ بی‌نهایت روی آپدیت خراب | ✅ try/except به‌ازای هر آپدیت + offset در `finally` |
| P0 | ۳. offset فقط در حافظه | ✅ در جدول `bot_state` دیتابیس ذخیره می‌شود |
| P0 | ۴. آلبوم >۱۰ آیتم | ✅ `_album_batches` — همیشه ۲..۱۰ در هر دسته |
| P0 | ۵. بدون مدیریت `RetryAfter` | ✅ `TelegramSender._retry` با backoff |
| P1 | ۶. فایل کامل در RAM | ✅ دانلود استریمی chunk به chunk |
| P1 | ۷. بدون سقف حجم فایل | ✅ `max_file_mb` (پیش‌فرض ۴۵) + پیام جایگزین |
| P1 | ۸. برش متن روی HTML | ✅ `split_plain_text` — برش روی متن خام |
| P1 | ۱۰. ارسال تکراری | ✅ چک `store.get()` قبل از ارسال |
| P1 | ۱۱. تسک flush بی‌صدا | ✅ done-callback + نگه‌داشتن رفرنس + flush هنگام خاموشی |
| P1 | ۱۲. تطبیق کانال فقط با username | ✅ `getChat` در startup، تطبیق با id و username |
| P2 | ۱۳–۱۴. `__pycache__` و `.gitignore` | ✅ پاک شد / بازنویسی شد |
| P2 | ۱۵–۱۷. import مرده، README نادرست | ✅ اصلاح شد |
| P2 | ۱۸. مسیر hardcode لاگ | ✅ `unsupported_log` قابل تنظیم |
| P2 | ۱۹. بدون تست | ✅ ۹۳ تست pytest در `tests/` |
| P2 | ۲۰. خطای مبهم `.env` | ✅ پیام واضح با نام کلید |
| P2 | ۲۲. بدون graceful shutdown | ✅ SIGTERM/SIGINT + flush آلبوم‌های در انتظار |
| P2 | ۲۳. بدون سرویس‌گذاری | ✅ `install.sh` + systemd + `tbrctl` |

**باقی‌مانده (عمداً انجام نشد):**
- مورد ۹ — تبدیل `entities` بله به HTML به‌جای پارسر ستاره. تغییر پرریسکی است چون رفتار فعلی روی کانال شما کار می‌کند و بدون دادهٔ واقعی بله قابل تأیید نیست. برش متن اصلاح شد، ولی `2*3` هنوز بولد تفسیر می‌شود.
- مورد ۲۱ — فراخوانی همگام SQLite در event loop. زیر بار فعلی مشکلی ایجاد نمی‌کند.
- دوطرفه کردن و روبیکا — نیاز به لایهٔ انتزاعی `Source`/`Sink` دارد؛ کار جداگانه‌ای است.

---

---

## ۱. پروژه واقعاً چه کار می‌کند

یک پل **یک‌طرفه** از **بله → تلگرام** است:

- از Bale با **Bot API خام** (`https://tapi.bale.ai/bot<token>`) و **long-polling** آپدیت می‌گیرد — کتابخانهٔ `python-bale-bot` استفاده **نمی‌شود** (برخلاف چیزی که README می‌گوید).
- فایل‌ها را دانلود می‌کند → روی دیسک موقت می‌نویسد → با `python-telegram-bot` v20.8 دوباره **آپلود** می‌کند (forward نمی‌کند).
- نگاشت `(bale_chat_id, bale_message_id) → [telegram_message_ids]` را در SQLite نگه می‌دارد تا edit / delete / reply قابل انتقال باشد.

**مهم:** نه دوطرفه است، نه Rubika دارد. نام و README هر دو بیش از آنچه هست وعده می‌دهند.

### جریان داده

```
Bale getUpdates (long-poll 25s)
        │
        ▼
Syncer.handle_update ──► message / channel_post / post ──► handle_new_message
        │                edited_* ──► handle_edited_message
        │                deleted_* ──► handle_deleted_message  (Bale چنین آپدیتی ندارد — کد دفاعی است)
        ▼
 فیلتر: _is_source_channel + رد کردن پیام ربات‌ها
        ▼
 اگر media_group_id دارد ──► بافر ۱.۲ ثانیه‌ای (pending_groups) ──► flush یکجا
 وگرنه ──► _send_message_now
        ▼
 extract_media ──► download_file ──► تشخیص نوع از magic bytes ──► TelegramSender
        ▼
 MappingStore.save  (SQLite)
```

### نقشهٔ فایل‌ها

| فایل | مسئولیت | نکته |
|---|---|---|
| `main.py` | entrypoint، ۱۹ خط | تمیز |
| `tbr_sync/config.py` | خواندن `.env`، dataclass فریز شده، ۱۸ کلید | نام‌های lower/UPPER هر دو پشتیبانی می‌شود |
| `tbr_sync/bale_api.py` | کلاینت HTTP خام بله (httpx) | دانلود فایل تماماً در RAM |
| `tbr_sync/telegram_api.py` | ارسال متن/مدیا/آلبوم/تماس/موقعیت + edit/delete | بزرگ‌ترین بخش ریسک |
| `tbr_sync/media.py` | استخراج مدیا از JSON خام + تشخیص پسوند/نوع | بخش خوب کد؛ magic-byte detection هوشمندانه است |
| `tbr_sync/syncer.py` | حلقهٔ اصلی، بافر آلبوم، منطق edit/delete | حلقهٔ اصلی نقطهٔ ضعف دارد |
| `tbr_sync/store.py` | SQLite mapping | فقط mapping — offset ذخیره نمی‌شود |
| `tbr_sync/text.py` | تبدیل `*bold*` بله به HTML تلگرام | پارسر ستاره شکننده است |
| `tbr_sync/logger.py` | logging + خفه کردن لاگ httpx (جلوگیری از لو رفتن توکن) | خوب |

---

## ۲. باگ‌ها و ریسک‌های واقعی (به ترتیب اولویت)

### 🔴 P0 — چیزهایی که همین الان در پروداکشن آسیب می‌زنند

**۱. `setup.py` اصلاً کاری که README می‌گوید نمی‌کند**
`README.md:47-52` می‌گوید `python3 setup.py` توکن‌ها را تعاملی می‌پرسد و `.env` می‌سازد. اما [setup.py](setup.py) یک اسکریپت **setuptools بسته‌بندی** است. هر کاربر جدید اینجا گیر می‌کند. `.env.example` هم وجود ندارد → هیچ‌کس نمی‌داند ۱۸ کلید تنظیمات چیست.

**۲. حلقهٔ بی‌نهایت روی یک آپدیت خراب** — [syncer.py:135-142](tbr_sync/syncer.py:135)
```python
for update in updates:
    update_id = update.get("update_id")
    await self.handle_update(bale, telegram, update)   # اگر اینجا exception بدهد...
    if isinstance(update_id, int):
        offset = update_id + 1                          # ...این هرگز اجرا نمی‌شود
```
هر خطا (فایل >۵۰MB، flood control، caption بد) باعث می‌شود offset جلو نرود، همان آپدیت هر ۵ ثانیه دوباره پردازش شود و **ربات برای همیشه گیر کند**. اگر ارسال جزئی موفق شده باشد، کانال تلگرام هم اسپم می‌شود. این جدی‌ترین باگ پروژه است.
**راه‌حل:** `try/except` دور هر آپدیت، لاگ خطا، و جلو بردن offset در `finally`.

**۳. offset فقط در حافظه است → پیام‌های زمان خاموشی گم می‌شوند** — [bale_api.py:58](tbr_sync/bale_api.py:58)
با `sync_old_messages=false` (پیش‌فرض)، هر ری‌استارت تمام صف pending را دور می‌ریزد. یعنی هر `pm2 restart` = از دست رفتن پیام‌ها.
**راه‌حل:** offset را در همان SQLite ذخیره کن و موقع بالا آمدن از آنجا ادامه بده.

**۴. آلبوم بیش از ۱۰ آیتم = خطا** — [telegram_api.py:159](tbr_sync/telegram_api.py:159)
تلگرام حداکثر ۱۰ آیتم در `sendMediaGroup` می‌پذیرد. بافر آلبوم هیچ سقفی ندارد. یک پست ۱۲ عکسی در بله → `BadRequest` → باگ شمارهٔ ۲ فعال می‌شود.
**راه‌حل:** آلبوم را به دسته‌های ۱۰تایی بشکن.

**۵. هیچ مدیریتی برای `RetryAfter` (flood control) نیست**
تلگرام روی کانال با ترافیک بالا `RetryAfter` می‌دهد. کد هیچ‌جا آن را نمی‌گیرد → exception → باگ ۲.
**راه‌حل:** wrapper با retry + `asyncio.sleep(exc.retry_after)`.

---

### 🟠 P1 — خرابی‌های قابل پیش‌بینی

**۶. فایل کامل در RAM بارگذاری می‌شود** — [bale_api.py:87-89](tbr_sync/bale_api.py:87)
`response.content` + `write_bytes` یعنی یک ویدیوی ۲۰۰MB → ۲۰۰MB رم. روی VPS کوچک OOM.
**راه‌حل:** `client.stream()` و نوشتن chunk به chunk.

**۷. هیچ چک اندازهٔ فایلی وجود ندارد**
سقف آپلود ربات تلگرام ۵۰MB است؛ بله سقف دیگری دارد. فایل بزرگ‌تر → خطا → باگ ۲. باید قبل از دانلود از `getFile.file_size` چک شود و در صورت بزرگ بودن، پیام متنی جایگزین بفرستد.

**۸. برش متن HTML را می‌شکند** — [telegram_api.py:49](tbr_sync/telegram_api.py:49)
`html_text[start:start+4096]` روی رشتهٔ **HTML** برش می‌زند. اگر برش وسط `<b>` یا `&amp;` بیفتد → `can't parse entities` → کل پیام گم می‌شود.
**راه‌حل:** روی متن خام برش بزن، بعد هر تکه را جداگانه رندر کن.

**۹. پارسر ستاره متن را خراب می‌کند** — [text.py:37-50](tbr_sync/text.py:37)
هر `*` یک toggle بولد است. پس `2*3=6` یا لیست `* آیتم` تگ‌های نامتوازن می‌سازد. ضمناً `entities` پیام بله کاملاً نادیده گرفته می‌شود — یعنی لینک، ایتالیک، کد، و mention همه از بین می‌روند.
**راه‌حل درست:** به‌جای پارس markdown، از `message.entities` بله → HTML تلگرام تبدیل کن.

**۱۰. پیام تکراری موقع re-delivery** — [syncer.py:287](tbr_sync/syncer.py:287)
`handle_new_message` قبل از ارسال، `store.get()` را چک نمی‌کند. اگر بله همان آپدیت را دوباره بدهد (crash وسط batch، یا `sync_old_messages=true`) پیام دوباره در تلگرام پست می‌شود.
**راه‌حل:** اگر mapping موجود بود، skip.

**۱۱. تسک flush آلبوم fire-and-forget است** — [syncer.py:316](tbr_sync/syncer.py:316)
`asyncio.create_task` بدون `add_done_callback`. خطا داخلش بی‌صدا بلعیده می‌شود ("Task exception was never retrieved") و آن آلبوم برای همیشه گم می‌شود. ضمناً اگر پروسه در آن ۱.۲ ثانیه بمیرد، آلبوم از دست می‌رود و offset هم قبلاً جلو رفته.

**۱۲. کانال با `@username` فقط با username تطبیق داده می‌شود** — [syncer.py:50-54](tbr_sync/syncer.py:50)
اگر بله در `channel_post` فیلد `username` را نفرستد، پیام بی‌صدا رد می‌شود و کاربر فکر می‌کند ربات خراب است.
**راه‌حل:** یک بار موقع startup با `getChat` آیدی عددی را resolve کن و هر دو را قبول کن.

---

### 🟡 P2 — بهداشت کد و مخزن

| # | مورد | محل |
|---|---|---|
| ۱۳ | `__pycache__/main.cpython-313.pyc` در گیت کامیت شده (با اینکه در `.gitignore` هست) | `git rm -r --cached __pycache__` |
| ۱۴ | `.gitignore` ناقص: `*.db`، `.tbr_sync.db`، `temp_downloads/`، `unsupported_updates.log`، `.env.*` نیست | [.gitignore](.gitignore) |
| ۱۵ | import بلااستفاده `TelegramError` | [syncer.py:12](tbr_sync/syncer.py:12) |
| ۱۶ | README ادعای `python-bale-bot` و `aiohttp` دارد — هیچ‌کدام استفاده نمی‌شوند | [README.md:11](README.md:11) |
| ۱۷ | README می‌گوید «دوطرفه» و اسم پروژه Rubika دارد — هیچ‌کدام پیاده نشده | [README.md:9](README.md:9) |
| ۱۸ | `unsupported_updates.log` با مسیر hardcode در ریشه، حاوی JSON کامل پیام (داده شخصی) | [syncer.py:261](tbr_sync/syncer.py:261) |
| ۱۹ | صفر تست، صفر CI، بدون lint/type-check (دو بات دیگر در فولدر لوکال تست دارند، این ندارد) | — |
| ۲۰ | خطای `int()`/`float()` روی مقدار بد `.env` traceback خام می‌دهد نه پیام واضح | [config.py:78-80](tbr_sync/config.py:78) |
| ۲۱ | فراخوانی‌های SQLite همگام داخل event loop (الان کوچک، ولی زیر بار کند می‌شود) | [store.py](tbr_sync/store.py) |
| ۲۲ | بدون graceful shutdown (SIGTERM) — `pm2 restart` آلبوم‌های در حال بافر را می‌کشد | [syncer.py:114](tbr_sync/syncer.py:114) |
| ۲۳ | بدون Dockerfile / systemd unit؛ PM2 برای اپ پایتونی انتخاب عجیبی است | — |

---

## ۳. نقاط قوت (خراب نکن)

- جداسازی ماژول‌ها تمیز است — `config` / `api` / `media` / `store` / `text` هرکدام یک کار می‌کنند.
- تشخیص نوع فایل از **magic bytes** ([media.py:132](tbr_sync/media.py:132)) هوشمندانه است و مشکل واقعی «فایل بدون پسوند در تلگرام» را حل می‌کند.
- منطق حذف document تکراری وقتی بله هم `photo` هم `document` می‌فرستد ([media.py:125](tbr_sync/media.py:125)) — نشان می‌دهد این کد با تجربهٔ میدانی نوشته شده.
- خفه کردن لاگر `httpx` برای جلوگیری از چاپ توکن در لاگ ([logger.py:14](tbr_sync/logger.py:14)) — رعایت امنیتی خوب.
- پشتیبانی از هر دو نام `snake_case` و `UPPER_CASE` در `.env` — سازگاری با نسخه‌های قدیمی.

---

## ۴. برنامهٔ پیشنهادی بهبود

**فاز ۰ — پایداری (نیم روز، بیشترین اثر)**
1. try/except دور هر آپدیت + جلو بردن offset در `finally`  ← باگ ۲
2. ذخیرهٔ offset در SQLite  ← باگ ۳
3. wrapper مشترک برای `RetryAfter` روی تمام فراخوانی‌های تلگرام  ← باگ ۵
4. شکستن آلبوم به دسته‌های ۱۰تایی  ← باگ ۴
5. چک `store.get()` قبل از ارسال (ضد تکرار)  ← باگ ۱۰

**فاز ۱ — درستی محتوا (یک روز)**
6. دانلود stream + سقف اندازهٔ فایل  ← باگ ۶ و ۷
7. برش امن متن (روی متن خام، نه HTML)  ← باگ ۸
8. تبدیل `entities` بله → HTML به‌جای پارسر ستاره  ← باگ ۹
9. resolve آیدی عددی کانال در startup  ← باگ ۱۲

**فاز ۲ — قابل ارائه شدن پروژه (نیم روز)**
10. نوشتن `setup_env.py` واقعی (تعاملی) یا حذف ادعا از README + افزودن `.env.example`
11. بازنویسی README مطابق واقعیت (یک‌طرفه بله→تلگرام، httpx، بدون Rubika)
12. اصلاح `.gitignore` + پاک کردن `__pycache__` از گیت
13. `Dockerfile` + `docker-compose.yml` یا systemd unit به‌عنوان جایگزین PM2

**فاز ۳ — کیفیت بلندمدت**
14. تست‌های pytest روی `text.py`، `media.py`، `store.py` (خالص و بدون I/O — راحت‌ترین جای شروع)
15. GitHub Actions: ruff + mypy + pytest
16. graceful shutdown با flush آلبوم‌های در انتظار
17. اگر واقعاً «دوطرفه» می‌خواهی: لایهٔ انتزاعی `Source`/`Sink` تا تلگرام→بله و Rubika هم اضافه شود

---

## ۵. سؤالات باز (منتظر جواب کاربر)

- تغییرات موردنظرت روی کدام بخش است؟ (دوطرفه کردن / Rubika / پایداری / پنل مدیریت؟)
- حجم ترافیک کانال چقدر است؟ (تعیین می‌کند سراغ webhook برویم یا polling کافی است)
- الان روی سرور با PM2 در حال اجراست یا هنوز محلی است؟
