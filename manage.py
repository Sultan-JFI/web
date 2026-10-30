# -*- coding: utf-8 -*-
"""نقطه ورود سازگار: دستور اجرای این سرویس روی رانفلر «python manage.py» است
(پیکربندی قبلی سرویس). این فایل اپ فلاسک را از main.py بالا می‌آورد.
اگر دستور اجرا در پنل به «python main.py» تغییر کرد، این فایل فقط اضافی است.
"""
import os

from main import app

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8000'))
    app.run(host='0.0.0.0', port=port)
