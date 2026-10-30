# -*- coding: utf-8 -*-
"""Production entrypoint for Runflare.

Start command (panel): python manage.py
Uses Gunicorn (gthread) — not Flask's development server.
"""
import os
import sys


def main():
    port = os.environ.get("PORT", "8000")
    # Prefer gunicorn; fall back only if missing (local quick test)
    try:
        from gunicorn.app.base import BaseApplication
    except ImportError:
        from main import app
        app.run(host="0.0.0.0", port=int(port))
        return

    class Application(BaseApplication):
        def __init__(self, app, options=None):
            self.application = app
            self.options = options or {}
            super().__init__()

        def load_config(self):
            config_path = os.path.join(os.path.dirname(__file__), "gunicorn.conf.py")
            if os.path.isfile(config_path):
                self.load_config_from_file(config_path)
            for key, value in self.options.items():
                if key in self.cfg.settings and value is not None:
                    self.cfg.set(key.lower(), value)

        def load(self):
            return self.application

    from main import app

    options = {
        "bind": f"0.0.0.0:{port}",
        "workers": int(os.environ.get("WEB_CONCURRENCY", "1")),
        "threads": int(os.environ.get("GUNICORN_THREADS", "4")),
        "worker_class": "gthread",
        "timeout": int(os.environ.get("GUNICORN_TIMEOUT", "60")),
        "graceful_timeout": 20,
        "keepalive": 5,
        "max_requests": 200,
        "max_requests_jitter": 40,
        "accesslog": "-",
        "errorlog": "-",
        "forwarded_allow_ips": "*",
    }
    Application(app, options).run()


if __name__ == "__main__":
    main()
