# -*- coding: utf-8 -*-
from gallery_public import *

@app.route('/panel')
def panel():
    return redirect(url_for('panel_dashboard' if session.get('panel_ok') else 'panel_login'))

@app.route('/panel/login', methods=['GET', 'POST'])
def panel_login():
    s = load_settings()
    if request.method == 'POST':
        password = request.form.get('password', '')
        if s.get('panel_password_hash') and check_password_hash(s['panel_password_hash'], password):
            session.clear(); session['panel_ok'] = True
            session['csrf_token'] = secrets.token_hex(32); session.modified = True
            return redirect(url_for('panel_dashboard'))
        flash('رمز عبور نادرست است', 'error')
    return render_template('panel_login.html', s=s, title='ورود به پنل')

@app.route('/panel/logout')
def panel_logout():
    session.clear(); return redirect(url_for('index'))

@app.route('/panel/password', methods=['GET', 'POST'])
@panel_required
def panel_password():
    s = load_settings()
    if request.method == 'POST':
        validate_csrf()
        current, new, confirm = request.form.get('current_password',''), request.form.get('new_password',''), request.form.get('confirm_password','')
        if not check_password_hash(s.get('panel_password_hash',''), current):
            flash('رمز فعلی اشتباه است', 'error')
        elif len(new) < 8: flash('رمز جدید باید حداقل ۸ کاراکتر باشد', 'error')
        elif new != confirm: flash('رمزهای جدید یکسان نیستند', 'error')
        else:
            s['panel_password_hash'] = generate_password_hash(new); save_settings(s); session.clear()
            flash('رمز تغییر کرد. دوباره وارد شوید.', 'success'); return redirect(url_for('panel_login'))
    return render_template('panel_password.html', s=s, title='تغییر رمز عبور')

@app.route('/panel/dashboard', methods=['GET', 'POST'])
@panel_required
def panel_dashboard():
    s = load_settings()
    if request.method == 'POST':
        validate_csrf()
        s['site_title'] = request.form.get('site_title','').strip() or s['site_title']
        s['site_description'] = request.form.get('site_description','').strip()
        s['contact_email'] = request.form.get('contact_email','').strip()
        s['show_contact'] = 'show_contact' in request.form
        s['maintenance'] = 'maintenance' in request.form
        save_settings(s); flash('تنظیمات ذخیره شد', 'success'); return redirect(url_for('panel_dashboard'))
    conn = get_db()
    image_count = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    category_count = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    total_views = conn.execute("SELECT COALESCE(SUM(views),0) FROM images").fetchone()[0]
    conn.close()
    return render_template('panel.html', s=s, title='داشبورد', settings_file=SETTINGS_FILE,
                           data_dir_exists=os.path.isdir(DATA_DIR), data_root=DATA_DIR,
                           image_count=image_count, category_count=category_count, total_views=total_views)

@app.route('/panel/gallery')
@panel_required
def panel_gallery():
    s = load_settings(); conn = get_db()
    images = conn.execute("""SELECT i.*, c.name as category_name FROM images i LEFT JOIN categories c ON i.category_id=c.id ORDER BY i.created_at DESC""").fetchall()
    conn.close()
    return render_template('panel_gallery.html', s=s, title='مدیریت تصاویر', images=images)

@app.route('/panel/gallery/upload', methods=['GET', 'POST'])
@panel_required
def panel_gallery_upload():
    s = load_settings(); conn = get_db()
    categories = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()
    if request.method == 'POST':
        validate_csrf()
        title = request.form.get('title','').strip()
        description = request.form.get('description','').strip()
        category_id = request.form.get('category_id','') or None
        tags = request.form.get('tags','').strip()
        if not title:
            flash('عنوان الزامی است', 'error'); conn.close()
            return render_template('panel_gallery_upload.html', s=s, title='آپلود تصویر', categories=categories)
        files = request.files.getlist('files')
        if not files or all(f.filename == '' for f in files):
            flash('هیچ فایلی انتخاب نشده است', 'error'); conn.close()
            return render_template('panel_gallery_upload.html', s=s, title='آپلود تصویر', categories=categories)
        os.makedirs(UPLOAD_FOLDER, exist_ok=True); os.makedirs(THUMBNAIL_FOLDER, exist_ok=True)
        uploaded, errors = 0, []
        for f in files:
            if f.filename == '': continue
            if not allowed_file(f.filename):
                errors.append(f'«{f.filename}»: پسوند مجاز نیست'); continue
            unique_name = uuid.uuid4().hex + '.' + f.filename.rsplit('.', 1)[1].lower()
            save_path = os.path.join(UPLOAD_FOLDER, unique_name)
            thumb_path = os.path.join(THUMBNAIL_FOLDER, unique_name)
            try:
                f.save(save_path)
                try:
                    img = Image.open(save_path); img.verify()
                except Exception:
                    if os.path.exists(save_path): os.remove(save_path)
                    errors.append(f'«{f.filename}»: فایل تصویری معتبر نیست'); continue
                img = Image.open(save_path); img = ImageOps.exif_transpose(img)
                if img.mode in ('RGBA', 'P'): img = img.convert('RGB')
                if img.width > config.MAX_WIDTH:
                    ratio = config.MAX_WIDTH / img.width
                    img = img.resize((config.MAX_WIDTH, int(img.height * ratio)), Image.LANCZOS)
                img.save(save_path, quality=85)
                thumb = img.copy(); thumb.thumbnail((config.THUMBNAIL_SIZE, config.THUMBNAIL_SIZE), Image.LANCZOS)
                thumb.save(thumb_path, quality=80)
                conn.execute("INSERT INTO images (title, description, filename, thumbnail, category_id, tags) VALUES (?,?,?,?,?,?)",
                             (title, description, unique_name, unique_name, category_id, tags))
                conn.commit(); uploaded += 1
            except Exception as e:
                if os.path.exists(save_path): os.remove(save_path)
                if os.path.exists(thumb_path): os.remove(thumb_path)
                errors.append(f'«{f.filename}»: {e}')
        conn.close()
        if uploaded: flash(f'{uploaded} تصویر با موفقیت آپلود شد', 'success')
        for err in errors: flash(err, 'error')
        return redirect(url_for('panel_gallery'))
    conn.close()
    return render_template('panel_gallery_upload.html', s=s, title='آپلود تصویر', categories=categories)

@app.route('/panel/gallery/<int:id>/delete', methods=['POST'])
@panel_required
def panel_gallery_delete(id):
    validate_csrf(); conn = get_db()
    row = conn.execute("SELECT * FROM images WHERE id=?", (id,)).fetchone()
    if row:
        for path in (os.path.join(UPLOAD_FOLDER, row['filename']), os.path.join(THUMBNAIL_FOLDER, row['thumbnail'] or row['filename'])):
            if os.path.exists(path): os.remove(path)
        conn.execute("DELETE FROM images WHERE id=?", (id,)); conn.commit()
        flash('تصویر حذف شد', 'success')
    else: flash('تصویر یافت نشد', 'error')
    conn.close(); return redirect(url_for('panel_gallery'))

@app.route('/panel/gallery/settings')
@panel_required
def panel_gallery_settings():
    s = load_settings(); conn = get_db()
    categories = conn.execute("""SELECT c.*, COUNT(i.id) as image_count FROM categories c LEFT JOIN images i ON i.category_id=c.id GROUP BY c.id ORDER BY c.name""").fetchall()
    conn.close()
    return render_template('panel_gallery_settings.html', s=s, title='تنظیمات گالری', categories=categories)

@app.route('/panel/gallery/settings/category', methods=['POST'])
@panel_required
def panel_gallery_category_add():
    validate_csrf()
    name = request.form.get('name','').strip()
    slug = request.form.get('slug','').strip() or make_slug(name)
    if not name: flash('نام دسته الزامی است', 'error'); return redirect(url_for('panel_gallery_settings'))
    conn = get_db()
    try:
        conn.execute("INSERT INTO categories (name, slug) VALUES (?,?)", (name, slug)); conn.commit()
        flash(f'دسته «{name}» اضافه شد', 'success')
    except sqlite3.IntegrityError:
        flash('دسته‌ای با این نام یا آدرس قبلاً وجود دارد', 'error')
    conn.close(); return redirect(url_for('panel_gallery_settings'))

@app.route('/panel/gallery/settings/category/<int:id>/delete', methods=['POST'])
@panel_required
def panel_gallery_category_delete(id):
    validate_csrf(); conn = get_db()
    conn.execute("DELETE FROM categories WHERE id=?", (id,)); conn.commit(); conn.close()
    flash('دسته حذف شد. تصاویر آن بدون دسته شدند.', 'success')
    return redirect(url_for('panel_gallery_settings'))

@app.route('/panel/gallery/settings/save', methods=['POST'])
@panel_required
def panel_gallery_settings_save():
    validate_csrf(); s = load_settings()
    s['site_title'] = request.form.get('site_title','').strip() or s['site_title']
    s['site_description'] = request.form.get('site_description','').strip()
    save_settings(s); flash('تنظیمات گالری ذخیره شد', 'success')
    return redirect(url_for('panel_gallery_settings'))

@app.errorhandler(403)
def forbidden(e):
    if session.get('panel_ok'): return redirect(request.referrer or url_for('panel_gallery'))
    return redirect(url_for('panel_login'))
