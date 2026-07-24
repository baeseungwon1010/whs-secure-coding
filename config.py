import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production')
    DATABASE = os.environ.get('DATABASE', 'instance/market.db')
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_UPLOAD_MB', 5)) * 1024 * 1024

    # 세션 만료 (2시간)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)

    # HTTPS 환경에서만 Secure 쿠키 활성화
    SESSION_COOKIE_SECURE = os.environ.get('HTTPS', 'false').lower() == 'true'

    # 로그인 실패 횟수 제한
    LOGIN_MAX_ATTEMPTS = 5       # 최대 실패 횟수
    LOGIN_LOCKOUT_SECONDS = 300  # 잠금 시간 (5분)

    SMTP_HOST = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
    SMTP_USER = os.environ.get('SMTP_USER', '')
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
    MAIL_FROM = os.environ.get('MAIL_FROM', '')

    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@example.com')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '')

    KAKAO_MAP_KEY = os.environ.get('KAKAO_MAP_KEY', '')

    TOSS_CLIENT_KEY = os.environ.get('TOSS_CLIENT_KEY', '')
    TOSS_SECRET_KEY = os.environ.get('TOSS_SECRET_KEY', '')

    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'app', 'static', 'uploads')
    ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png'}
    ALLOWED_MAGIC_BYTES = {
        b'\xff\xd8\xff',           # JPEG
        b'\x89PNG\r\n\x1a\n',     # PNG
    }

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    WTF_CSRF_ENABLED = True
