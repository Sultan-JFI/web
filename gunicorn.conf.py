# Gunicorn production config — suitable for Runflare free tier + SQLite
# Docs: https://docs.gunicorn.org/en/stable/settings.html
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# One process + threads: safe for SQLite, concurrent requests without multi-process DB locks
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
worker_class = "gthread"

# Avoid hung workers taking down the whole site
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))
graceful_timeout = 20
keepalive = 5

# Recycle workers periodically (memory leak protection)
max_requests = 200
max_requests_jitter = 40

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")

# Trust proxy headers from Runflare edge
forwarded_allow_ips = "*"
