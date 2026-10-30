# -*- coding: utf-8 -*-
"""پیکربندی مرکزی مسیرهای ذخیره‌سازی.

هر دایرکتوری یا فایل پیش‌فرض جدید: فقط یک خط به همین فایل اضافه شود.
مسیر پایه از متغیر محیطی DATA_ROOT خوانده می‌شود (پنل رانفلر: متغیر محیطی)؛
اگر مسیر mount دیسک عوض شد، فقط همان متغیر تغییر می‌کند، نه کد.
"""
import os


def _detect_data_root():
    """تشخیص مسیر دیسک پایدار: اولویت با متغیر محیطی، سپس نامزدهای موجود.

    دیسک‌های رانفلر (CephFS) به‌صورت پیش‌فرض زیر / یا /data مانت می‌شوند.
    /app/data روی لایه موقت کانتینر است و با ریستارت پاک می‌شود، پس آخرین
    گزینه است (فقط وقتی هیچ دیسکی تعریف نشده باشد).
    """
    env = os.environ.get("DATA_ROOT")
    if env:
        return env
    candidates = ["/data", "/app/data"]
    for path in candidates:
        if os.path.isdir(path):
            return path
    return "/app/data"


DATA_ROOT = _detect_data_root()

# ساختار مرکزی دایرکتوری‌ها — هر دایرکتوری آینده فقط یک خط اینجا اضافه شود
REQUIRED_DIRECTORIES = [
    DATA_ROOT,
    os.path.join(DATA_ROOT, "uploads"),
    os.path.join(DATA_ROOT, "uploads", "thumbnails"),
    os.path.join(DATA_ROOT, "backups"),
    os.path.join(DATA_ROOT, "logs"),
]

# تنظیمات پیش‌فرض — در اولین اجرا به settings.json نوشته می‌شود
# (فایل موجود هرگز بازنویسی نمی‌شود؛ فقط کلیدهای گم‌شده هنگام خواندن ادغام می‌شوند)
DEFAULT_SETTINGS = {
    "site_title": "گالری مذهبی",
    "site_description": "",
    "contact_email": "",
    "show_contact": True,
    "maintenance": False,
    "panel_password_hash": None,  # در اولین اجرا ساخته می‌شود
    "updated_at": None,
}

# مسیر فایل‌های مهم
SETTINGS_FILE = os.path.join(DATA_ROOT, "settings.json")
DATABASE_FILE = os.path.join(DATA_ROOT, "gallery.db")

# === گالری ===
UPLOAD_FOLDER = os.path.join(DATA_ROOT, "uploads")
THUMBNAIL_FOLDER = os.path.join(UPLOAD_FOLDER, "thumbnails")
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB
IMAGES_PER_PAGE = 12
MAX_WIDTH = 1600
THUMBNAIL_SIZE = 400