# -*- coding: utf-8 -*-
"""Temporary entry — full gallery code being deployed in next commits."""
import os
from flask import Flask, jsonify
from datetime import datetime

app = Flask(__name__)

@app.route('/health')
def health():
    return jsonify(ok=True, time=datetime.now().isoformat(), note='deploying phase3')

@app.route('/')
def index():
    return '<h1>در حال به‌روزرسانی…</h1><p>فاز ۳ در حال استقرار است. چند دقیقه دیگر برگردید.</p>', 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8000'))
    app.run(host='0.0.0.0', port=port)
