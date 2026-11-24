import os
import sqlite3
import subprocess
import shutil
import threading
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, session
from werkzeug.utils import secure_filename
from datetime import datetime
from dotenv import load_dotenv

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads')
app.config['DATABASE'] = os.path.join(BASE_DIR, 'diary.db')
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

def get_or_create_secret_key():
    """Get secret key from environment or generate and persist one"""
    env_key = os.environ.get('SECRET_KEY')
    if env_key:
        return env_key
    
    # Try to read from file
    secret_file = os.path.join(BASE_DIR, '.secret_key')
    try:
        with open(secret_file, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        pass
    
    # Generate new key and save it
    new_key = os.urandom(32).hex()
    try:
        with open(secret_file, 'w') as f:
            f.write(new_key)
        os.chmod(secret_file, 0o600)  # Only owner can read/write
    except Exception:
        pass
    return new_key

app.secret_key = get_or_create_secret_key()

# Session configuration
from datetime import timedelta
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection

# Configure logging
log_file = os.path.join(BASE_DIR, 'app.log')
file_handler = RotatingFileHandler(
    log_file, 
    maxBytes=1024 * 1024,  # 1MB
    backupCount=10
)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
file_handler.setLevel(logging.INFO)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
app.logger.info('Child Diary startup')

# CSRF protection
def generate_csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = os.urandom(24).hex()
    return session['csrf_token']

app.jinja_env.globals['csrf_token'] = generate_csrf_token

def validate_csrf():
    """Validate CSRF token for POST/PUT/DELETE requests"""
    if request.method in ('POST', 'PUT', 'DELETE'):
        token = session.get('csrf_token')
        if not token:
            return False
        
        # Check form data, JSON, or header
        request_token = None
        
        # Check form data
        if request.form:
            request_token = request.form.get('csrf_token')
        
        # Check JSON body
        if not request_token and request.is_json:
            request_token = request.json.get('csrf_token')
        
        # Check header
        if not request_token:
            request_token = request.headers.get('X-CSRF-Token')
        
        return request_token == token
    return True

# Rate limiting for login attempts
from collections import defaultdict
import time
login_attempts = defaultdict(list)  # IP -> list of attempt timestamps
MAX_LOGIN_ATTEMPTS = 5
LOGIN_BLOCK_TIME = 300  # 5 minutes

# Password hashing (use werkzeug.security)
from werkzeug.security import generate_password_hash, check_password_hash

# Admin password hash. No default password is shipped — it must be provided via
# ADMIN_PASSWORD_HASH (in .env or the environment). If it is missing, admin login
# is disabled until configured.
ADMIN_PASSWORD_HASH = os.environ.get('ADMIN_PASSWORD_HASH')
if not ADMIN_PASSWORD_HASH:
    ADMIN_PASSWORD_HASH = generate_password_hash(os.urandom(32).hex())
    app.logger.warning('ADMIN_PASSWORD_HASH is not set; admin login is disabled until configured.')

ALLOWED_EXT = {'png','jpg','jpeg','gif','mp4','webm','mov','heic','heif'}
VIDEO_EXT = {'mp4','webm','mov'}

# Magic bytes for file type validation
FILE_SIGNATURES = {
    'image/png': [b'\x89PNG\r\n\x1a\n'],
    'image/jpeg': [b'\xff\xd8\xff'],
    'image/gif': [b'GIF87a', b'GIF89a'],
    'image/heic': [b'\x00\x00\x00'],  # HEIC files start with ftyp box
    'video/mp4': [b'\x00\x00\x00', b'ftyp'],  # MP4/MOV files
    'video/webm': [b'\x1a\x45\xdf\xa3'],  # WebM/MKV
}

def allowed_file(fn):
    return '.' in fn and fn.rsplit('.',1)[1].lower() in ALLOWED_EXT

def validate_file_content(file_data, expected_ext):
    """Validate file content matches expected type using magic bytes"""
    if not file_data or len(file_data) < 8:
        return False
    
    # Check magic bytes based on extension
    if expected_ext in ('png',):
        return file_data.startswith(b'\x89PNG')
    elif expected_ext in ('jpg', 'jpeg'):
        return file_data.startswith(b'\xff\xd8\xff')
    elif expected_ext in ('gif',):
        return file_data.startswith(b'GIF87a') or file_data.startswith(b'GIF89a')
    elif expected_ext in ('mp4', 'mov', 'heic', 'heif'):
        # These files start with an ftyp box (size + 'ftyp')
        return len(file_data) > 8 and b'ftyp' in file_data[:20]
    elif expected_ext in ('webm',):
        return file_data.startswith(b'\x1a\x45\xdf\xa3')
    
    # Unknown extension, allow by default
    return True

def sanitize_content(content):
    """Basic content sanitization to prevent XSS"""
    # Remove potentially dangerous HTML tags
    import re
    # Allow basic formatting tags but remove script/event handlers
    content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL | re.IGNORECASE)
    content = re.sub(r'<iframe[^>]*>.*?</iframe>', '', content, flags=re.DOTALL | re.IGNORECASE)
    content = re.sub(r'<object[^>]*>.*?</object>', '', content, flags=re.DOTALL | re.IGNORECASE)
    content = re.sub(r'<embed[^>]*>.*?</embed>', '', content, flags=re.DOTALL | re.IGNORECASE)
    content = re.sub(r'on\w+\s*=\s*["\'][^"\'>]*["\']', '', content, flags=re.IGNORECASE)
    content = re.sub(r'on\w+\s*=\s*[^\s>]+', '', content, flags=re.IGNORECASE)
    return content

def extract_image_date(file_path):
    """Extract capture date from image EXIF data"""
    if not HAS_PIL:
        return None
    
    try:
        img = Image.open(file_path)
        
        # Try to get EXIF data
        exif_data = img._getexif()
        if exif_data:
            # EXIF tag 36867 is DateTimeOriginal (capture time)
            # EXIF tag 306 is DateTime
            for tag_id in [36867, 306, 36868]:
                if tag_id in exif_data:
                    date_str = exif_data[tag_id]
                    # Parse date format: 'YYYY:MM:DD HH:MM:SS'
                    try:
                        dt = datetime.strptime(date_str, '%Y:%m:%d %H:%M:%S')
                        return dt.strftime('%Y-%m-%d')
                    except ValueError:
                        continue
        
        # Fallback: try to get from filename if it contains date pattern
        filename = os.path.basename(file_path)
        import re
        
        # Look for patterns like IMG_20240101_123456 or 20240101_123456
        date_match = re.search(r'(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])', filename)
        if date_match:
            year, month, day = date_match.groups()
            return f'{year}-{month}-{day}'
        
        # Look for timestamp patterns like 155746885575_IMG_8430.jpg
        # This could be a Unix timestamp in various formats
        timestamp_match = re.match(r'(\d{10,13})_', filename)
        if timestamp_match:
            try:
                ts_str = timestamp_match.group(1)
                ts = int(ts_str)
                
                # Try different interpretations
                for divisor in [1, 1000, 1000000]:
                    try:
                        dt = datetime.fromtimestamp(ts / divisor)
                        # Only return if the date is reasonable (2000-2100)
                        if 2000 <= dt.year <= 2100:
                            return dt.strftime('%Y-%m-%d')
                    except (ValueError, OSError, OverflowError):
                        continue
            except (ValueError, OSError):
                pass
        
        # Final fallback: use file creation date
        try:
            # Get file creation date (birth time on macOS, change time on Linux)
            stat = os.stat(file_path)
            
            # Try to get birth time (creation time)
            creation_time = None
            
            # On macOS, st_birthtime is available
            if hasattr(stat, 'st_birthtime'):
                creation_time = stat.st_birthtime
            else:
                # On Linux, we need to use a different approach
                # Try to get birth time from file system
                try:
                    import subprocess
                    result = subprocess.run(
                        ['stat', '-c', '%W', file_path],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0 and result.stdout.strip().isdigit():
                        creation_time = int(result.stdout.strip())
                except Exception:
                    pass
                
                # Fall back to change time
                if creation_time is None:
                    creation_time = stat.st_ctime
            
            dt = datetime.fromtimestamp(creation_time)
            # Only return if the date is reasonable (after 2020)
            if dt.year >= 2020:
                return dt.strftime('%Y-%m-%d')
        except Exception:
            pass
        
        return None
    except Exception as e:
        app.logger.error(f'Error extracting image date: {e}')
        return None

def extract_video_date(file_path):
    """Extract creation date from video metadata using ffprobe"""
    try:
        # Use ffprobe to get video metadata
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', file_path],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            import json
            metadata = json.loads(result.stdout)
            
            # Try to get creation_time from format tags
            if 'format' in metadata and 'tags' in metadata['format']:
                tags = metadata['format']['tags']
                
                # Try different tag names
                for tag_name in ['creation_time', 'date', 'date_time']:
                    if tag_name in tags:
                        date_str = tags[tag_name]
                        try:
                            # Try ISO format: 2024-01-01T12:34:56.000000Z
                            if 'T' in date_str:
                                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                                return dt.strftime('%Y-%m-%d')
                            # Try other formats
                            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S', '%Y-%m-%d']:
                                try:
                                    dt = datetime.strptime(date_str[:19], fmt)
                                    return dt.strftime('%Y-%m-%d')
                                except ValueError:
                                    continue
                        except Exception:
                            continue
        
        # Fallback: try to get from filename
        filename = os.path.basename(file_path)
        import re
        date_match = re.search(r'(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])', filename)
        if date_match:
            year, month, day = date_match.groups()
            return f'{year}-{month}-{day}'
        
        return None
    except Exception as e:
        app.logger.error(f'Error extracting video date: {e}')
        return None

def extract_media_date(file_path, file_ext):
    """Extract date from media file (image or video)"""
    if file_ext in {'jpg', 'jpeg', 'png', 'gif', 'heic', 'heif'}:
        return extract_image_date(file_path)
    elif file_ext in {'mp4', 'mov', 'webm'}:
        return extract_video_date(file_path)
    return None

def compress_image(src_path, max_size=1200, quality=80):
    """Compress image on server side for faster loading, preserving EXIF data"""
    if not HAS_PIL:
        return src_path
    
    try:
        img = Image.open(src_path)
        
        # Preserve EXIF data
        exif_data = img.info.get('exif')
        
        # Convert RGBA to RGB if needed
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        
        # Resize if larger than max_size
        width, height = img.size
        if width > max_size or height > max_size:
            ratio = min(max_size / width, max_size / height)
            new_size = (int(width * ratio), int(height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # Save compressed version with EXIF data preserved
        save_kwargs = {'quality': quality, 'optimize': True}
        if exif_data:
            save_kwargs['exif'] = exif_data
        img.save(src_path, 'JPEG', **save_kwargs)
        app.logger.info(f'Compressed image: {os.path.basename(src_path)} ({width}x{height} -> {img.size[0]}x{img.size[1]})')
        return src_path
    except Exception as e:
        app.logger.error(f'Image compression failed: {e}')
        return src_path

def generate_thumbnail(src_path, thumb_path, size=400):
    """Generate thumbnail for faster timeline loading"""
    if not HAS_PIL:
        return None
    
    try:
        img = Image.open(src_path)
        
        # Convert RGBA to RGB if needed
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        
        # Create thumbnail
        img.thumbnail((size, size), Image.Resampling.LANCZOS)
        img.save(thumb_path, 'JPEG', quality=75, optimize=True)
        app.logger.info(f'Generated thumbnail: {os.path.basename(thumb_path)}')
        return thumb_path
    except Exception as e:
        app.logger.error(f'Thumbnail generation failed: {e}')
        return None

def get_db():
    db = sqlite3.connect(app.config['DATABASE'])
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.execute('''CREATE TABLE IF NOT EXISTS entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL, content TEXT NOT NULL,
        entry_date TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS media (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entry_id INTEGER NOT NULL, filename TEXT NOT NULL,
        filepath TEXT NOT NULL, media_type TEXT NOT NULL,
        poster TEXT DEFAULT '',
        FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
    )''')
    
    # Add indexes for better performance
    db.execute('CREATE INDEX IF NOT EXISTS idx_entries_entry_date ON entries(entry_date)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_media_entry_id ON media(entry_id)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_media_filepath ON media(filepath)')
    
    db.commit(); db.close()

def convert_heic(src_path):
    jpg_path = src_path.rsplit('.',1)[0] + '.jpg'
    if HAS_PIL:
        try:
            img = Image.open(src_path)
            img.save(jpg_path, 'JPEG', quality=90)
            os.remove(src_path)
            return jpg_path
        except Exception:
            pass
    try:
        r = subprocess.run(['convert', src_path, '-quality', '90', jpg_path], capture_output=True, timeout=30)
        if r.returncode == 0 and os.path.exists(jpg_path):
            os.remove(src_path)
            return jpg_path
    except Exception:
        pass
    return None

def convert_video(src_path, mp4_path):
    try:
        r = subprocess.run([
            'ffmpeg', '-i', src_path,
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
            '-vf', 'scale=min(1920\\,iw):min(1080\\,ih):force_original_aspect_ratio=decrease',
            '-c:a', 'aac', '-b:a', '128k',
            '-movflags', '+faststart',
            '-y', mp4_path
        ], capture_output=True, timeout=600)
        if r.returncode == 0 and os.path.exists(mp4_path):
            os.remove(src_path)
            return True
    except Exception as e:
        app.logger.warning(f'Video convert failed: {e}')
    return False

def generate_thumb(video_path, thumb_path):
    try:
        r = subprocess.run(['ffmpeg', '-i', video_path, '-ss', '00:00:01', '-vframes', '1', '-q:v', '2', '-y', thumb_path],
                          capture_output=True, timeout=30)
        return r.returncode == 0 and os.path.exists(thumb_path)
    except:
        return False

def extract_thumb_async(video_path):
    """Generate thumbnail for video files (non-MOV)"""
    try:
        # Generate thumbnail path
        base, ext = os.path.splitext(video_path)
        thumb_path = base + '_thumb.jpg'
        
        if generate_thumb(video_path, thumb_path):
            # Update database with poster path
            edir = os.path.dirname(video_path)
            eid = os.path.basename(edir)
            thumb_fn = os.path.basename(thumb_path)
            poster = f'{eid}/{thumb_fn}'
            
            # Find the media record by filepath
            video_fn = os.path.basename(video_path)
            db = sqlite3.connect(app.config['DATABASE'])
            db.execute('UPDATE media SET poster=? WHERE filepath=?',
                       (poster, f'{eid}/{video_fn}'))
            db.commit()
            db.close()
    except Exception as e:
        app.logger.error(f'Error extracting thumbnail: {e}')

def convert_video_async(src_path, mp4_path, db_path, media_id):
    success = convert_video(src_path, mp4_path)
    if success:
        mp4_fn = os.path.basename(mp4_path)
        edir = os.path.dirname(mp4_path)
        eid = os.path.basename(edir)
        thumb_fn = mp4_fn.rsplit('.', 1)[0] + '_thumb.jpg'
        thumb_path = os.path.join(edir, thumb_fn)
        poster = ''
        if generate_thumb(mp4_path, thumb_path):
            poster = f'{eid}/{thumb_fn}'
        db = sqlite3.connect(db_path)
        db.execute('UPDATE media SET filepath=?, media_type=?, poster=? WHERE id=?',
                   (f'{eid}/{mp4_fn}', 'video', poster, media_id))
        db.commit(); db.close()

def save_uploaded_files(eid, files):
    edir = os.path.join(app.config['UPLOAD_FOLDER'], str(eid))
    os.makedirs(edir, exist_ok=True)
    db = get_db()
    count = 0
    extracted_dates = []  # Store dates extracted from files
    
    for f in files:
        if not f or not f.filename or not allowed_file(f.filename):
            continue
        fn = secure_filename(f.filename)
        if not fn:
            fn = 'upload.jpg'
        ext = fn.rsplit('.',1)[1].lower()
        ts = datetime.now().strftime('%H%M%S%f')
        new_fn = f"{ts}_{fn}"
        fpath = os.path.join(edir, new_fn)
        f.save(fpath)
        
        # Extract date from media file
        media_date = extract_media_date(fpath, ext)
        if media_date:
            extracted_dates.append(media_date)
            app.logger.info(f'Extracted date from {fn}: {media_date}')
        
        # Validate file content matches extension
        try:
            with open(fpath, 'rb') as file_check:
                file_header = file_check.read(32)
                if not validate_file_content(file_header, ext):
                    app.logger.warning(f'File content mismatch: {fn} (ext: {ext})')
                    os.remove(fpath)
                    continue
        except Exception as e:
            app.logger.error(f'File validation error: {e}')
            # Continue processing if validation fails
        
        if ext in {'heic','heif'}:
            result = convert_heic(fpath)
            if result:
                fpath = result
                new_fn = new_fn.rsplit('.',1)[0] + '.jpg'
                ext = 'jpg'
        if ext == 'mov':
            mp4_fn = new_fn.rsplit('.',1)[0] + '.mp4'
            mp4_path = os.path.join(edir, mp4_fn)
            cur = db.execute('INSERT INTO media (entry_id,filename,filepath,media_type,poster) VALUES (?,?,?,?,?)',
                             (eid, fn, f'{eid}/{new_fn}', 'video', ''))
            mid = cur.lastrowid
            db.commit()
            thread = threading.Thread(target=convert_video_async,
                                      args=(fpath, mp4_path, app.config['DATABASE'], mid),
                                      daemon=True)
            thread.start()
        else:
            mtype = 'video' if ext in VIDEO_EXT else 'image'
            
            # Compress image and generate thumbnail
            thumb_path = None
            if mtype == 'image' and ext in {'jpg', 'jpeg', 'png', 'gif'}:
                # Compress the original image
                compress_image(fpath, max_size=1200, quality=80)
                
                # Generate thumbnail
                thumb_fn = new_fn.rsplit('.', 1)[0] + '_thumb.jpg'
                thumb_path = os.path.join(edir, thumb_fn)
                generate_thumbnail(fpath, thumb_path, size=400)
            
            poster = f'{eid}/{os.path.basename(thumb_path)}' if thumb_path and os.path.exists(thumb_path) else ''
            
            db.execute('INSERT INTO media (entry_id,filename,filepath,media_type,poster) VALUES (?,?,?,?,?)',
                       (eid, fn, f'{eid}/{new_fn}', mtype, poster))
            if mtype == 'video':
                threading.Thread(target=extract_thumb_async, args=(fpath,), daemon=True).start()
        count += 1
    db.commit(); db.close()
    
    # Return the earliest date found, or None
    if extracted_dates:
        return count, min(extracted_dates)
    return count, None

@app.route('/')
def timeline():
    db = get_db()
    entries = db.execute('SELECT * FROM entries ORDER BY entry_date ASC, id ASC').fetchall()
    result = []
    for e in entries:
        media = db.execute('SELECT * FROM media WHERE entry_id=?', (e['id'],)).fetchall()
        result.append({'entry': e, 'media': media})
    db.close()
    return render_template('timeline.html', entries=result, logged_in=session.get('auth'))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        # Rate limiting
        ip = request.remote_addr
        now = time.time()
        # Clean old attempts
        login_attempts[ip] = [t for t in login_attempts[ip] if now - t < LOGIN_BLOCK_TIME]
        
        if len(login_attempts[ip]) >= MAX_LOGIN_ATTEMPTS:
            app.logger.warning(f'Rate limited login attempt from {ip}')
            return render_template('login.html', error='登录尝试过多，请稍后再试')
        
        # CSRF validation - skip for login page if session doesn't have token yet
        session_token = session.get('csrf_token')
        form_token = request.form.get('csrf_token')
        
        # Debug logging
        app.logger.info(f'Login attempt - Session token: {session_token[:20] if session_token else None}..., Form token: {form_token[:20] if form_token else None}...')
        
        if session_token and form_token and session_token != form_token:
            app.logger.warning(f'CSRF token mismatch from {ip}')
            return render_template('login.html', error='CSRF token 无效，请刷新页面重试')
        
        password = request.form.get('password', '')
        if check_password_hash(ADMIN_PASSWORD_HASH, password):
            # Successful login - clear attempts
            login_attempts.pop(ip, None)
            session['auth'] = True
            session.permanent = True  # Session expires after 30 days by default
            app.logger.info(f'Successful login from {ip}')
            return redirect('/admin')
        
        # Failed login - record attempt
        login_attempts[ip].append(now)
        app.logger.warning(f'Failed login attempt from {ip}')
        return render_template('login.html', error='密码错误')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('auth', None)
    return redirect('/')

@app.route('/admin')
def admin():
    if not session.get('auth'):
        return redirect('/login')
    return render_template('admin.html')

@app.route('/edit/<int:eid>')
def edit_page(eid):
    if not session.get('auth'):
        return redirect('/login')
    db = get_db()
    entry = db.execute('SELECT * FROM entries WHERE id=?', (eid,)).fetchone()
    if not entry:
        db.close()
        return redirect('/')
    media = db.execute('SELECT * FROM media WHERE entry_id=?', (eid,)).fetchall()
    db.close()
    return render_template('edit.html', entry=entry, media=media)

@app.route('/api/entries', methods=['POST'])
def create_entry():
    if not session.get('auth'):
        return jsonify({'error':'unauthorized'}), 401
    
    # CSRF validation
    if not validate_csrf():
        return jsonify({'error':'CSRF token 无效'}), 403
    
    title = request.form.get('title','').strip()
    content = request.form.get('content','').strip()
    entry_date = request.form.get('entry_date','').strip()
    
    # Input validation
    if not title or not content:
        return jsonify({'error':'缺少必填项'}), 400
    
    if len(title) > 200:
        return jsonify({'error':'标题过长（最多200字）'}), 400
    
    # Save files first to extract dates
    files = request.files.getlist('media')
    
    # If no date provided, try to extract from files
    if not entry_date and files:
        # Create a temporary entry to save files
        db = get_db()
        try:
            cur = db.execute('INSERT INTO entries (title,content,entry_date) VALUES (?,?,?)',
                             (title, content, '2000-01-01'))  # Temporary date
            eid = cur.lastrowid
            db.commit()
        except Exception as e:
            db.close()
            app.logger.error(f'Database error creating entry: {e}')
            return jsonify({'error':'数据库错误'}), 500
        finally:
            db.close()
        
        # Save files and extract dates
        count, extracted_date = save_uploaded_files(eid, files)
        
        # Use extracted date if available, otherwise use today
        if extracted_date:
            entry_date = extracted_date
            app.logger.info(f'Using extracted date: {extracted_date}')
        else:
            entry_date = datetime.now().strftime('%Y-%m-%d')
        
        # Update the entry with the correct date
        db = get_db()
        try:
            db.execute('UPDATE entries SET entry_date=? WHERE id=?', (entry_date, eid))
            db.commit()
        except Exception as e:
            app.logger.error(f'Database error updating entry date: {e}')
        finally:
            db.close()
        
        return jsonify({'id':eid, 'success':True, 'entry_date':entry_date})
    
    # If date provided or no files, proceed normally
    if not entry_date:
        entry_date = datetime.now().strftime('%Y-%m-%d')
    
    # Validate date format
    try:
        datetime.strptime(entry_date, '%Y-%m-%d')
    except ValueError:
        return jsonify({'error':'日期格式无效'}), 400
    
    # Sanitize content
    title = sanitize_content(title)
    content = sanitize_content(content)
    
    db = get_db()
    try:
        cur = db.execute('INSERT INTO entries (title,content,entry_date) VALUES (?,?,?)',
                         (title, content, entry_date))
        eid = cur.lastrowid
        db.commit()
    except Exception as e:
        db.close()
        app.logger.error(f'Database error creating entry: {e}')
        return jsonify({'error':'数据库错误'}), 500
    finally:
        db.close()
    
    count, extracted_date = save_uploaded_files(eid, files)
    return jsonify({'id':eid, 'success':True, 'entry_date':entry_date})

@app.route('/api/extract-date', methods=['POST'])
def extract_date_from_files():
    """Extract dates from uploaded files without creating an entry"""
    if not session.get('auth'):
        return jsonify({'error':'unauthorized'}), 401
    
    # CSRF validation
    if not validate_csrf():
        return jsonify({'error':'CSRF token 无效'}), 403
    
    files = request.files.getlist('media')
    if not files:
        return jsonify({'dates':[]})
    
    extracted_dates = []
    for f in files:
        if not f or not f.filename or not allowed_file(f.filename):
            continue
        
        fn = secure_filename(f.filename)
        if not fn:
            continue
        
        ext = fn.rsplit('.',1)[1].lower() if '.' in fn else ''
        
        # Save file temporarily
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}') as tmp:
            f.save(tmp.name)
            tmp_path = tmp.name
        
        try:
            # Extract date
            media_date = extract_media_date(tmp_path, ext)
            if media_date:
                extracted_dates.append({
                    'filename': f.filename,
                    'date': media_date
                })
        finally:
            # Clean up temp file
            try:
                os.remove(tmp_path)
            except:
                pass
    
    # Return the earliest date if available
    if extracted_dates:
        earliest_date = min(d['date'] for d in extracted_dates)
        return jsonify({
            'dates': extracted_dates,
            'suggested_date': earliest_date
        })
    
    return jsonify({'dates':[], 'suggested_date': None})

@app.route('/api/entries/<int:eid>', methods=['PUT'])
def update_entry(eid):
    if not session.get('auth'):
        return jsonify({'error':'unauthorized'}), 401
    
    # CSRF validation
    if not validate_csrf():
        return jsonify({'error':'CSRF token 无效'}), 403
    
    data = request.get_json()
    title = (data.get('title') or '').strip()
    content = (data.get('content') or '').strip()
    entry_date = (data.get('entry_date') or '').strip()
    
    if not title or not content or not entry_date:
        return jsonify({'error':'缺少必填项'}), 400
    
    # Input validation
    if len(title) > 200:
        return jsonify({'error':'标题过长（最多200字）'}), 400
    
    # Validate date format
    try:
        datetime.strptime(entry_date, '%Y-%m-%d')
    except ValueError:
        return jsonify({'error':'日期格式无效'}), 400
    
    # Sanitize content
    title = sanitize_content(title)
    content = sanitize_content(content)
    
    db = get_db()
    try:
        db.execute('UPDATE entries SET title=?, content=?, entry_date=? WHERE id=?',
                   (title, content, entry_date, eid))
        db.commit()
    except Exception as e:
        db.close()
        app.logger.error(f'Database error updating entry {eid}: {e}')
        return jsonify({'error':'数据库错误'}), 500
    finally:
        db.close()
    
    return jsonify({'success':True})

@app.route('/api/entries/<int:eid>/media', methods=['POST'])
def upload_media(eid):
    if not session.get('auth'):
        return jsonify({'error':'unauthorized'}), 401
    # CSRF validation
    if not validate_csrf():
        return jsonify({'error':'CSRF token 无效'}), 403
    count = save_uploaded_files(eid, request.files.getlist('media'))
    return jsonify({'success':True, 'uploaded':count})

@app.route('/api/media/<int:mid>', methods=['DELETE'])
def delete_media(mid):
    if not session.get('auth'):
        return jsonify({'error':'unauthorized'}), 401
    
    # CSRF validation
    if not validate_csrf():
        return jsonify({'error':'CSRF token 无效'}), 403
    
    db = get_db()
    try:
        m = db.execute('SELECT * FROM media WHERE id=?', (mid,)).fetchone()
        if m:
            fpath = os.path.join(app.config['UPLOAD_FOLDER'], m['filepath'])
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except Exception as e:
                    app.logger.error(f'Error deleting file {fpath}: {e}')
            db.execute('DELETE FROM media WHERE id=?', (mid,))
            db.commit()
    except Exception as e:
        db.close()
        app.logger.error(f'Database error deleting media {mid}: {e}')
        return jsonify({'error':'数据库错误'}), 500
    finally:
        db.close()
    
    return jsonify({'success':True})

@app.route('/api/entries/<int:eid>', methods=['DELETE'])
def delete_entry(eid):
    if not session.get('auth'):
        return jsonify({'error':'unauthorized'}), 401
    
    # CSRF validation
    if not validate_csrf():
        return jsonify({'error':'CSRF token 无效'}), 403
    
    db = get_db()
    try:
        # Check if entry exists
        entry = db.execute('SELECT * FROM entries WHERE id=?', (eid,)).fetchone()
        if not entry:
            return jsonify({'error':'日记不存在'}), 404
        
        # Delete files
        edir = os.path.join(app.config['UPLOAD_FOLDER'], str(eid))
        if os.path.isdir(edir):
            try:
                shutil.rmtree(edir, ignore_errors=True)
            except Exception as e:
                app.logger.error(f'Error deleting directory {edir}: {e}')
        
        # Delete from database
        db.execute('DELETE FROM media WHERE entry_id=?', (eid,))
        db.execute('DELETE FROM entries WHERE id=?', (eid,))
        db.commit()
    except Exception as e:
        db.close()
        app.logger.error(f'Database error deleting entry {eid}: {e}')
        return jsonify({'error':'数据库错误'}), 500
    finally:
        db.close()
    
    return jsonify({'success':True})

@app.route('/uploads/<path:fn>')
def serve_upload(fn):
    return send_from_directory(app.config['UPLOAD_FOLDER'], fn)

@app.after_request
def add_security_headers(response):
    # Security headers
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    # Content Security Policy
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "media-src 'self' blob:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'self'"
    )
    response.headers['Content-Security-Policy'] = csp
    
    # HSTS - enforce HTTPS (only if request is secure)
    if request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    
    # Disable caching for API endpoints
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    
    # Add caching for images and static files (7 days)
    if request.path.startswith('/uploads/') or request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'public, max-age=604800'
    
    return response

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=False)
