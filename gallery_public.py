# -*- coding: utf-8 -*-
"""گالری مذهبی — فاز ۳: CSRF fix, image detail, QR, ProxyFix."""
import os, json, secrets, sqlite3, functools, uuid, io, hmac
from datetime import datetime
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify, send_from_directory, abort, make_response)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from PIL import Image, ImageOps
try:
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M
except ImportError:
    qrcode = None
import config

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', '1') == '1'
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH
app.config['PREFERRED_URL_SCHEME'] = 'https'
DATA_DIR, SETTINGS_FILE = config.DATA_ROOT, config.SETTINGS_FILE
UPLOAD_FOLDER, THUMBNAIL_FOLDER = config.UPLOAD_FOLDER, config.THUMBNAIL_FOLDER

def _ensure_secret_key():
    s = {}
    try:
        with open(SETTINGS_FILE, encoding='utf-8') as f: s = json.load(f)
    except Exception: pass
    env_key = os.environ.get('SECRET_KEY')
    if env_key:
        app.secret_key = env_key; return
    if not s.get('_secret_key'):
        s['_secret_key'] = secrets.token_hex(32)
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    app.secret_key = s['_secret_key']

def get_db():
    conn = sqlite3.connect(config.DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def load_settings():
    merged = dict(config.DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, encoding='utf-8') as f: merged.update(json.load(f))
    except Exception: pass
    return merged

def save_settings(new):
    os.makedirs(DATA_DIR, exist_ok=True)
    new['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(new, f, ensure_ascii=False, indent=2)
    return new

def bootstrap():
    created = []
    for d in config.REQUIRED_DIRECTORIES:
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True); created.append('dir:'+d)
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(config.DEFAULT_SETTINGS, f, ensure_ascii=False, indent=2)
        created.append('file:'+SETTINGS_FILE)
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE, slug TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            description TEXT, filename TEXT NOT NULL UNIQUE, thumbnail TEXT,
            category_id INTEGER, tags TEXT, views INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL);
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    conn.commit(); conn.close(); created.append('db')
    s = load_settings()
    if not s.get('panel_password_hash'):
        s['panel_password_hash'] = generate_password_hash('admin123')
        save_settings(s); created.append('hash')
    print('[bootstrap]', created or 'ok', 'DATA_ROOT='+DATA_DIR, flush=True)

def csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32); session.modified = True
    return session['csrf_token']

def validate_csrf():
    token = request.form.get('csrf_token', '') or request.headers.get('X-CSRF-Token', '')
    expected = session.get('csrf_token', '')
    if not expected:
        session['csrf_token'] = secrets.token_hex(32); session.modified = True
        flash('نشست منقضی شده. دوباره وارد شوید و فرم را ارسال کنید.', 'error'); abort(403)
    if not token or not hmac.compare_digest(token, expected):
        flash('توکن امنیتی نامعتبر. صفحه را رفرش کنید.', 'error'); abort(403)

app.jinja_env.globals['csrf_token'] = csrf_token

def panel_required(view):
    @functools.wraps(view)
    def wrapper(*a, **k):
        if not session.get('panel_ok'): return redirect(url_for('panel_login'))
        return view(*a, **k)
    return wrapper

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in config.ALLOWED_EXTENSIONS

def make_slug(name):
    import re
    slug = name.strip().replace(' ', '-').lower()
    slug = re.sub(r'[^a-z0-9\u0600-\u06FF\-]', '', slug)
    return slug or uuid.uuid4().hex[:8]

def public_base_url():
    if config.PUBLIC_BASE_URL: return config.PUBLIC_BASE_URL
    return request.url_root.rstrip('/')

def image_public_url(image_id):
    return public_base_url() + url_for('image_detail', id=image_id)

@app.route('/')
def index():
    s = load_settings()
    page = request.args.get('page', 1, type=int)
    category_slug = request.args.get('category', '')
    per_page = config.IMAGES_PER_PAGE
    conn = get_db()
    categories = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()
    if category_slug:
        total = conn.execute("""SELECT COUNT(*) FROM images i JOIN categories c ON i.category_id=c.id WHERE c.slug=?""", (category_slug,)).fetchone()[0]
        images = conn.execute("""SELECT i.*, c.name as category_name FROM images i JOIN categories c ON i.category_id=c.id WHERE c.slug=? ORDER BY i.created_at DESC LIMIT ? OFFSET ?""", (category_slug, per_page, (page-1)*per_page)).fetchall()
    else:
        total = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        images = conn.execute("""SELECT i.*, c.name as category_name FROM images i LEFT JOIN categories c ON i.category_id=c.id ORDER BY i.created_at DESC LIMIT ? OFFSET ?""", (per_page, (page-1)*per_page)).fetchall()
    conn.close()
    total_pages = max(1, (total + per_page - 1) // per_page)
    return render_template('index.html', s=s, title=s['site_title'], images=images, categories=categories, page=page, total_pages=total_pages, active_cat=category_slug)

@app.route('/image/<int:id>')
def image_detail(id):
    s = load_settings()
    conn = get_db()
    row = conn.execute("""SELECT i.*, c.name as category_name, c.slug as category_slug FROM images i LEFT JOIN categories c ON i.category_id=c.id WHERE i.id=?""", (id,)).fetchone()
    if not row: conn.close(); abort(404)
    conn.execute("UPDATE images SET views=views+1 WHERE id=?", (id,)); conn.commit()
    row = conn.execute("""SELECT i.*, c.name as category_name, c.slug as category_slug FROM images i LEFT JOIN categories c ON i.category_id=c.id WHERE i.id=?""", (id,)).fetchone()
    conn.close()
    return render_template('image_detail.html', s=s, title=row['title'], img=row, image_url=image_public_url(id))

@app.route('/image/<int:id>/qr.png')
def image_qr(id):
    if qrcode is None: abort(500)
    conn = get_db()
    row = conn.execute("SELECT id, title FROM images WHERE id=?", (id,)).fetchone(); conn.close()
    if not row: abort(404)
    qr = qrcode.QRCode(version=None, error_correction=ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(image_public_url(id)); qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buf = io.BytesIO(); img.save(buf, format='PNG'); buf.seek(0)
    resp = make_response(buf.read())
    resp.headers['Content-Type'] = 'image/png'
    safe = ''.join(c if c.isalnum() or c in '-_' else '_' for c in (row['title'] or 'image'))[:40]
    resp.headers['Content-Disposition'] = f'attachment; filename="qr-{id}-{safe}.png"'
    resp.headers['Cache-Control'] = 'public, max-age=3600'
    return resp

@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(UPLOAD_FOLDER, os.path.basename(filename))

@app.route('/thumbnails/<path:filename>')
def serve_thumbnail(filename):
    return send_from_directory(THUMBNAIL_FOLDER, os.path.basename(filename))

@app.route('/health')
def health():
    return jsonify(ok=True, time=datetime.now().isoformat(), data_root=DATA_DIR,
                   disk_writable=os.path.isdir(DATA_DIR) and os.access(DATA_DIR, os.W_OK),
                   qrcode_available=qrcode is not None)

