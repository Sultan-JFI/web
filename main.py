# -*- coding: utf-8 -*-
"""Entry point."""
from gallery import app

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
