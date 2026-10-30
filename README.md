# گالری مذهبی — Flask + Gunicorn + رانفلر

## علت ۵۰۲های قبلی

سرور توسعهٔ Flask (`app.run`) برای پروداکشن مناسب نیست (تک‌نخی / ناپایدار).
الان ورود با **Gunicorn** (`gthread`، چند درخواست هم‌زمان) انجام می‌شود.

## دستور اجرا (پنل رانفلر)

```
python manage.py
```

این دستور Gunicorn را با `gunicorn.conf.py` بالا می‌آورد.

## دیسک پایدار

مسیر پیشنهادی: `/data` + متغیر:

```
DATA_ROOT=/data
PUBLIC_BASE_URL=https://sultan-kdns.ir
SECRET_KEY=<رشته‌ی ثابت تصادفی>
```

## متغیرهای اختیاری Gunicorn

| متغیر | پیش‌فرض | توضیح |
|--------|---------|--------|
| `PORT` | 8000 | پورت |
| `WEB_CONCURRENCY` | 1 | تعداد worker (با SQLite روی ۱ بمانید) |
| `GUNICORN_THREADS` | 4 | threadهای هر worker |
| `GUNICORN_TIMEOUT` | 60 | ثانیه |

## صفحه‌ها

| مسیر | نقش |
|------|-----|
| `/` | گالری |
| `/image/<id>` | صفحه تصویر + QR سمت مرورگر |
| `/panel` | پنل |
| `/health` | سلامت |.
