# -*- coding: utf-8 -*-
"""گالری تصاویر مذهبی — رانفلر (پروژه: starter / سرویس: basic).

فاز ۲: گالری آنلاین + آپلود + دسته‌بندی + پنل مدیریت.
"""
import os
import json
import secrets
import shutil
import sqlite3
import functools
import uuid
from datetime import datetime

from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify, send_from_directory, abort)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image, ImageOps

import hmac

import config

app = Flask(__name__)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH

DATA_DIR = config.DATA_ROOT
SETTINGS_FILE = config.SETTINGS_FILE
UPLOAD_FOLDER = config.UPLOAD_FOLDER
THUMBNAIL_FOLDER = config.THUMBNAIL_FOLDER


def _ensure_secret_key():
    """SECRET_KEY پایدار: ذخیره در settings.json تا سشن و CSRF بین ریستارت‌ها معتبر بمانند."""
    s = {}
    try:
        with open(SETTINGS_FILE, encoding='utf-8') as f:
            s = json.load(f)
    except Exception:
        pass
    env_key = os.environ.get('SECRET_KEY')
    if env_key:
        app.secret_key = env_key
        return
    if not s.get('_secret_key'):
        s['_secret_key'] = secrets.token_hex(32)
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    app.secret_key = s['_secret_key']


# ─── helpers ───────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(config.DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def bootstrap():
    """ساختار کامل را در نقطه شروع می‌سازد. idempotent."""
    created = []
    for d in config.REQUIRED_DIRECTORIES:
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
            created.append('dir: ' + d)
    # settings.json
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(config.DEFAULT_SETTINGS, f, ensure_ascii=False, indent=2)
        created.append('file: ' + SETTINGS_FILE)
    # gallery.db + tables
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            slug TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            filename TEXT NOT NULL UNIQUE,
            thumbnail TEXT,
            category_id INTEGER,
            tags TEXT,
            views INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    conn.commit()
    conn.close()
    created.append('db: tables ensured')
    # password hash init
    s = load_settings()
    if not s.get('panel_password_hash'):
        s['panel_password_hash'] = generate_password_hash('admin123')
        save_settings(s)
        created.append('hash: panel_password_hash initialized')
    if created:
        print('[bootstrap] Created: ' + repr(created), flush=True)
    else:
        print('[bootstrap] Everything already exists, nothing to create.', flush=True)
    return created


def load_settings():
    merged = dict(config.DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, encoding='utf-8') as f:
            merged.update(json.load(f))
    except Exception:
        pass
    return merged


def save_settings(new):
    os.makedirs(DATA_DIR, exist_ok=True)
    new['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(new, f, ensure_ascii=False, indent=2)
    return new


def csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']


def validate_csrf():
    token = request.form.get('csrf_token', '')
    expected = session.get('csrf_token', '')
    if not token or not expected or not hmac.compare_digest(token, expected):
        abort(403)


app.jinja_env.globals['csrf_token'] = csrf_token


def panel_required(view):
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get('panel_ok'):
            return redirect(url_for('panel_login'))
        return view(*args, **kwargs)
    return wrapper


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in config.ALLOWED_EXTENSIONS


def make_slug(name):
    """ساخت slug ساده از نام فارسی (ترجمه نیست، فقط فاصله→خط‌تیره)."""
    import re
    slug = name.strip().replace(' ', '-').lower()
    slug = re.sub(r'[^a-z0-9\u0600-\u06FF\-]', '', slug)
    return slug or uuid.uuid4().hex[:8]


# ─── public routes ─────────────────────────────────────────────────────────

@app.route('/')
def index():
    s = load_settings()
    page = request.args.get('page', 1, type=int)
    category_slug = request.args.get('category', '')
    per_page = config.IMAGES_PER_PAGE

    conn = get_db()
    categories = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()

    if category_slug:
        count_q = """SELECT COUNT(*) FROM images i
                     JOIN categories c ON i.category_id = c.id
                     WHERE c.slug = ?"""
        img_q = """SELECT i.*, c.name as category_name FROM images i
                   JOIN categories c ON i.category_id = c.id
                   WHERE c.slug = ?
                   ORDER BY i.created_at DESC LIMIT ? OFFSET ?"""
        total = conn.execute(count_q, (category_slug,)).fetchone()[0]
        images = conn.execute(img_q, (category_slug, per_page, (page - 1) * per_page)).fetchall()
    else:
        total = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        img_q = """SELECT i.*, c.name as category_name FROM images i
                   LEFT JOIN categories c ON i.category_id = c.id
                   ORDER BY i.created_at DESC LIMIT ? OFFSET ?"""
        images = conn.execute(img_q, (per_page, (page - 1) * per_page)).fetchall()

    conn.close()
    total_pages = max(1, (total + per_page - 1) // per_page)
    return render_template('index.html', s=s, title=s['site_title'],
                           images=images, categories=categories,
                           page=page, total_pages=total_pages,
                           active_cat=category_slug)


@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    safe = os.path.basename(filename)
    return send_from_directory(UPLOAD_FOLDER, safe)


@app.route('/thumbnails/<path:filename>')
def serve_thumbnail(filename):
    safe = os.path.basename(filename)
    return send_from_directory(THUMBNAIL_FOLDER, safe)


@app.route('/health')
def health():
    return jsonify(ok=True, time=datetime.now().isoformat())


# ─── panel auth ────────────────────────────────────────────────────────────

@app.route('/panel')
def panel():
    if session.get('panel_ok'):
        return redirect(url_for('panel_dashboard'))
    return redirect(url_for('panel_login'))


@app.route('/panel/login', methods=['GET', 'POST'])
def panel_login():
    s = load_settings()
    if request.method == 'POST':
        password = request.form.get('password', '')
        stored_hash = s.get('panel_password_hash', '')
        if stored_hash and check_password_hash(stored_hash, password):
            session['panel_ok'] = True
            session['csrf_token'] = secrets.token_hex(32)
            return redirect(url_for('panel_dashboard'))
        flash('رمز عبور نادرست است', 'error')
    return render_template('panel_login.html', s=s, title='ورود به پنل')


@app.route('/panel/logout')
def panel_logout():
    session.clear()
    return redirect(url_for('index'))


@app.route('/panel/password', methods=['GET', 'POST'])
@panel_required
def panel_password():
    s = load_settings()
    if request.method == 'POST':
        validate_csrf()
        current = request.form.get('current_password', '')
        new = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        if not check_password_hash(s.get('panel_password_hash', ''), current):
            flash('رمز فعلی اشتباه است', 'error')
        elif len(new) < 8:
            flash('رمز جدید باید حداقل ۸ کاراکتر باشد', 'error')
        elif new != confirm:
            flash('رمزهای جدید یکسان نیستند', 'error')
        else:
            s['panel_password_hash'] = generate_password_hash(new)
            save_settings(s)
            session.clear()
            flash('رمز عبور با موفقیت تغییر کرد. لطفاً دوباره وارد شوید.', 'success')
            return redirect(url_for('panel_login'))
    return render_template('panel_password.html', s=s, title='تغییر رمز عبور')


# ─── panel dashboard ───────────────────────────────────────────────────────

@app.route('/panel/dashboard', methods=['GET', 'POST'])
@panel_required
def panel_dashboard():
    s = load_settings()
    if request.method == 'POST':
        validate_csrf()
        s['site_title'] = request.form.get('site_title', '').strip() or s['site_title']
        s['site_description'] = request.form.get('site_description', '').strip()
        s['contact_email'] = request.form.get('contact_email', '').strip()
        s['show_contact'] = 'show_contact' in request.form
        s['maintenance'] = 'maintenance' in request.form
        save_settings(s)
        flash('تنظیمات ذخیره شد', 'success')
        return redirect(url_for('panel_dashboard'))

    conn = get_db()
    image_count = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    category_count = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    total_views = conn.execute("SELECT COALESCE(SUM(views),0) FROM images").fetchone()[0]
    conn.close()
    return render_template('panel.html', s=s, title='داشبورد',
                           settings_file=SETTINGS_FILE,
                           data_dir_exists=os.path.isdir(DATA_DIR),
                           image_count=image_count,
                           category_count=category_count,
                           total_views=total_views)


# ─── panel gallery ─────────────────────────────────────────────────────────

@app.route('/panel/gallery')
@panel_required
def panel_gallery():
    s = load_settings()
    conn = get_db()
    images = conn.execute("""
        SELECT i.*, c.name as category_name FROM images i
        LEFT JOIN categories c ON i.category_id = c.id
        ORDER BY i.created_at DESC
    """).fetchall()
    conn.close()
    return render_template('panel_gallery.html', s=s, title='مدیریت تصاویر', images=images)


@app.route('/panel/gallery/upload', methods=['GET', 'POST'])
@panel_required
def panel_gallery_upload():
    s = load_settings()
    conn = get_db()
    categories = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()

    if request.method == 'POST':
        validate_csrf()
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        category_id = request.form.get('category_id', '') or None
        tags = request.form.get('tags', '').strip()

        if not title:
            flash('عنوان الزامی است', 'error')
            conn.close()
            return render_template('panel_gallery_upload.html', s=s,
                                   title='آپلود تصویر', categories=categories)

        files = request.files.getlist('files')
        if not files or all(f.filename == '' for f in files):
            flash('هیچ فایلی انتخاب نشده است', 'error')
            conn.close()
            return render_template('panel_gallery_upload.html', s=s,
                                   title='آپلود تصویر', categories=categories)

        uploaded = 0
        errors = []
        for f in files:
            if f.filename == '':
                continue
            if not allowed_file(f.filename):
                errors.append(f'«{f.filename}»: پسوند مجاز نیست (jpg, jpeg, png, webp)')
                continue

            unique_name = uuid.uuid4().hex + '.' + f.filename.rsplit('.', 1)[1].lower()
            save_path = os.path.join(UPLOAD_FOLDER, unique_name)
            thumb_path = os.path.join(THUMBNAIL_FOLDER, unique_name)

            try:
                # save temporarily
                f.save(save_path)
                # validate real image
                try:
                    img = Image.open(save_path)
                    img.verify()
                except Exception:
                    os.remove(save_path)
                    errors.append(f'«{f.filename}»: فایل تصویری معتبر نیست')
                    continue

                # re-open for processing (verify() invalidates the object)
                img = Image.open(save_path)
                img = ImageOps.exif_transpose(img)
                # resize if wider than MAX_WIDTH
                if img.width > config.MAX_WIDTH:
                    ratio = config.MAX_WIDTH / img.width
                    img = img.resize((config.MAX_WIDTH, int(img.height * ratio)), Image.LANCZOS)
                img.save(save_path, quality=85)

                # thumbnail
                thumb = img.copy()
                thumb.thumbnail((config.THUMBNAIL_SIZE, config.THUMBNAIL_SIZE), Image.LANCZOS)
                thumb.save(thumb_path, quality=80)

                # db record
                conn.execute(
                    "INSERT INTO images (title, description, filename, thumbnail, category_id, tags) VALUES (?,?,?,?,?,?)",
                    (title, description, unique_name, unique_name, category_id, tags))
                conn.commit()
                uploaded += 1
            except Exception as e:
                # cleanup orphan file
                if os.path.exists(save_path):
                    os.remove(save_path)
                if os.path.exists(thumb_path):
                    os.remove(thumb_path)
                errors.append(f'«{f.filename}»: خطا در پردازش — {e}')

        conn.close()
        if uploaded:
            flash(f'{uploaded} تصویر با موفقیت آپلود شد', 'success')
        for err in errors:
            flash(err, 'error')
        return redirect(url_for('panel_gallery'))

    conn.close()
    return render_template('panel_gallery_upload.html', s=s,
                           title='آپلود تصویر', categories=categories)


@app.route('/panel/gallery/<int:id>/delete', methods=['POST'])
@panel_required
def panel_gallery_delete(id):
    validate_csrf()
    conn = get_db()
    row = conn.execute("SELECT * FROM images WHERE id=?", (id,)).fetchone()
    if row:
        # delete physical files
        for path in (os.path.join(UPLOAD_FOLDER, row['filename']),
                     os.path.join(THUMBNAIL_FOLDER, row['thumbnail'] or row['filename'])):
            if os.path.exists(path):
                os.remove(path)
        conn.execute("DELETE FROM images WHERE id=?", (id,))
        conn.commit()
        flash('تصویر حذف شد', 'success')
    else:
        flash('تصویر یافت نشد', 'error')
    conn.close()
    return redirect(url_for('panel_gallery'))


# ─── panel gallery settings ────────────────────────────────────────────────

@app.route('/panel/gallery/settings')
@panel_required
def panel_gallery_settings():
    s = load_settings()
    conn = get_db()
    categories = conn.execute("""
        SELECT c.*, COUNT(i.id) as image_count
        FROM categories c LEFT JOIN images i ON i.category_id = c.id
        GROUP BY c.id ORDER BY c.name
    """).fetchall()
    conn.close()
    return render_template('panel_gallery_settings.html', s=s,
                           title='تنظیمات گالری', categories=categories)


@app.route('/panel/gallery/settings/category', methods=['POST'])
@panel_required
def panel_gallery_category_add():
    validate_csrf()
    name = request.form.get('name', '').strip()
    slug = request.form.get('slug', '').strip() or make_slug(name)
    if not name:
        flash('نام دسته الزامی است', 'error')
        return redirect(url_for('panel_gallery_settings'))
    conn = get_db()
    try:
        conn.execute("INSERT INTO categories (name, slug) VALUES (?,?)", (name, slug))
        conn.commit()
        flash(f'دسته «{name}» اضافه شد', 'success')
    except sqlite3.IntegrityError:
        flash('دسته‌ای با این نام یا آدرس قبلاً وجود دارد', 'error')
    conn.close()
    return redirect(url_for('panel_gallery_settings'))


@app.route('/panel/gallery/settings/category/<int:id>/delete', methods=['POST'])
@panel_required
def panel_gallery_category_delete(id):
    validate_csrf()
    conn = get_db()
    conn.execute("DELETE FROM categories WHERE id=?", (id,))
    conn.commit()
    conn.close()
    flash('دسته حذف شد. تصاویر آن بدون دسته شدند.', 'success')
    return redirect(url_for('panel_gallery_settings'))


@app.route('/panel/gallery/settings/save', methods=['POST'])
@panel_required
def panel_gallery_settings_save():
    validate_csrf()
    s = load_settings()
    s['site_title'] = request.form.get('site_title', '').strip() or s['site_title']
    s['site_description'] = request.form.get('site_description', '').strip()
    save_settings(s)
    flash('تنظیمات گالری ذخیره شد', 'success')
    return redirect(url_for('panel_gallery_settings'))


# ─── startup ───────────────────────────────────────────────────────────────

bootstrap()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8000'))
    app.run(host='0.0.0.0', port=port)
