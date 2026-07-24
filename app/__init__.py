import os
import sqlite3
from flask import Flask, g
from flask_wtf.csrf import CSRFProtect
from flask_socketio import SocketIO
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash

csrf = CSRFProtect()
socketio = SocketIO()
login_manager = LoginManager()
limiter = Limiter(key_func=get_remote_address, default_limits=[], storage_uri='memory://')

_DEFAULT_ADMIN_PW = 'Admin@Market1'


def create_app():
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object('config.Config')

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs('instance', exist_ok=True)

    csrf.init_app(app)
    socketio.init_app(app, cors_allowed_origins='*', async_mode='threading')
    login_manager.init_app(app)
    limiter.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = '로그인이 필요합니다.'
    login_manager.login_message_category = 'warning'

    _init_db(app)
    _migrate_db(app)
    _seed_admin(app)

    from app.blueprints.auth import auth_bp
    from app.blueprints.products import products_bp
    from app.blueprints.search import search_bp
    from app.blueprints.chat import chat_bp
    from app.blueprints.payment import payment_bp
    from app.blueprints.notifications import notifications_bp
    from app.blueprints.reports import reports_bp
    from app.blueprints.admin import admin_bp
    from app.blueprints.mypage import mypage_bp
    from app.blueprints.main import main_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(products_bp, url_prefix='/products')
    app.register_blueprint(search_bp, url_prefix='/search')
    app.register_blueprint(chat_bp, url_prefix='/chat')
    app.register_blueprint(payment_bp, url_prefix='/payment')
    app.register_blueprint(notifications_bp, url_prefix='/notifications')
    app.register_blueprint(reports_bp, url_prefix='/reports')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(mypage_bp, url_prefix='/mypage')

    from app.blueprints import chat as chat_mod
    chat_mod.register_events(socketio)

    from flask_login import current_user
    from app.models.notification import Notification

    @app.template_filter('hhmm')
    def hhmm_filter(dt):
        if hasattr(dt, 'strftime'):
            return dt.strftime('%H:%M')
        s = str(dt or '')
        return s[11:16] if len(s) >= 16 else s

    @app.context_processor
    def inject_globals():
        count = 0
        if current_user.is_authenticated:
            count = Notification.unread_count(current_user.id)
        from app.utils.signed_id import sign_id
        return {
            'unread_count': count,
            'config': app.config,
            'sign_id': sign_id,
        }

    # ── 보안 헤더 ──────────────────────────────────────────────────────────
    @app.after_request
    def set_security_headers(response):
        # CSP: 인라인 스크립트 허용(기존 코드 유지), 외부 리소스 제한
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.socket.io https://unpkg.com https://js.tosspayments.com https://dapi.kakao.com https://t1.daumcdn.net; "
            "style-src 'self' 'unsafe-inline' https://unpkg.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' wss: ws: https://nominatim.openstreetmap.org https://*.tosspayments.com https://js.tosspayments.com; "
            "frame-src https://tosspayments.com https://*.tosspayments.com https://toss.im https://*.toss.im;"
        )
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(self), camera=(), microphone=()'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        return response

    # ── 에러 핸들러 ────────────────────────────────────────────────────────
    @app.errorhandler(403)
    def forbidden(e):
        from flask import render_template as rt
        return rt('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        from flask import render_template as rt
        return rt('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        from flask import render_template as rt
        return rt('errors/500.html'), 500

    @app.errorhandler(429)
    def too_many_requests(e):
        from flask import render_template as rt, request as req
        if req.accept_mimetypes.best == 'application/json':
            from flask import jsonify as fj
            return fj({'error': '요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.'}), 429
        return rt('errors/429.html'), 429

    @app.teardown_appcontext
    def close_db(error):
        db = g.pop('db', None)
        if db is not None:
            db.close()

    return app


def get_db():
    from flask import current_app
    if 'db' not in g:
        g.db = sqlite3.connect(
            current_app.config['DATABASE'],
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA journal_mode=WAL')
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db


def _init_db(app):
    db_path = app.config['DATABASE']
    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA foreign_keys=ON')
    schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'schema.sql')
    with open(schema_path) as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


def _migrate_db(app):
    """Add columns that may be missing from older DB files."""
    db_path = app.config['DATABASE']
    conn = sqlite3.connect(db_path)
    migrations = [
        "ALTER TABLE users ADD COLUMN notify_quiet_start TEXT DEFAULT '22:00'",
        "ALTER TABLE users ADD COLUMN notify_quiet_end TEXT DEFAULT '07:00'",
        "ALTER TABLE products ADD COLUMN latitude REAL DEFAULT NULL",
        "ALTER TABLE products ADD COLUMN longitude REAL DEFAULT NULL",
        "ALTER TABLE products ADD COLUMN stock INTEGER DEFAULT 1",
        "ALTER TABLE transactions ADD COLUMN quantity INTEGER DEFAULT 1",
        "ALTER TABLE auth_logs ADD COLUMN query_text TEXT DEFAULT NULL",
        "ALTER TABLE comments ADD COLUMN deleted_by_admin INTEGER DEFAULT 0",
        "ALTER TABLE chat_messages ADD COLUMN message_type TEXT DEFAULT 'text'",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except Exception:
            pass
    conn.commit()
    conn.close()


def _seed_admin(app):
    db_path = app.config['DATABASE']
    password = app.config['ADMIN_PASSWORD'] or _DEFAULT_ADMIN_PW
    username = app.config['ADMIN_USERNAME']
    email = app.config['ADMIN_EMAIL']
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    existing = conn.execute('SELECT id FROM users WHERE is_admin=1').fetchone()
    if not existing:
        conn.execute(
            'INSERT OR IGNORE INTO users '
            '(username, password_hash, nickname, email, is_admin, balance) '
            'VALUES (?, ?, ?, ?, 1, 0)',
            (username, generate_password_hash(password), '관리자', email)
        )
        conn.commit()
    elif app.config['ADMIN_PASSWORD']:
        # Always sync configured password so admin can recover access via .env
        conn.execute('UPDATE users SET password_hash=? WHERE is_admin=1',
                     (generate_password_hash(app.config['ADMIN_PASSWORD']),))
        conn.commit()
    conn.close()


@login_manager.user_loader
def load_user(user_id):
    from app.models.user import User
    return User.get_by_id(int(user_id))
