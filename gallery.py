# -*- coding: utf-8 -*-
"""Application package entry: public + panel routes."""
from gallery_public import app, _ensure_secret_key, bootstrap
import gallery_panel  # noqa: F401  registers routes on app

_ensure_secret_key()
bootstrap()
