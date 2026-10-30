# -*- coding: utf-8 -*-
"""Production entrypoint for Runflare.

Start command in panel: python manage.py

Industry standard: Gunicorn WSGI server (not Flask development server).
See: https://flask.palletsprojects.com/en/stable/deploying/
"""
import os
import sys


def main():
    port = os.environ.get("PORT", "8000")
    root = os.path.dirname(os.path.abspath(__file__))
    conf = os.path.join(root, "gunicorn.conf.py")

    # Ensure app imports cleanly before replacing process
    try:
        import main as app_module  # noqa: F401
    except Exception as e:
        print("[manage] failed to import app:", e, flush=True)
        raise

    try:
        import gunicorn  # noqa: F401
    except ImportError:
        print("[manage] gunicorn not installed; falling back to Flask dev server", flush=True)
        from main import app
        app.run(host="0.0.0.0", port=int(port), threaded=True)
        return

    # Replace current process with Gunicorn (standard production pattern)
    args = [
        "gunicorn",
        "--config", conf,
        "main:app",
    ]
    print("[manage] starting:", " ".join(args), flush=True)
    os.execvp("gunicorn", args)


if __name__ == "__main__":
    main()
