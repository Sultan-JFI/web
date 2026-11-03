# -*- coding: utf-8 -*-
"""Entrypoint compatible with Runflare panel command: python manage.py

Delegates to safe_start supervisor (logs on disk, restart on crash, no bare crash).
"""
from safe_start import main

if __name__ == "__main__":
    raise SystemExit(main())
