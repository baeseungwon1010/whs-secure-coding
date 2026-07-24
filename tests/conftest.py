"""pytest fixtures — 테스트용 앱/DB/클라이언트"""
import io
import os
import struct
import tempfile

import pytest
from werkzeug.security import generate_password_hash

# 환경변수를 테스트용으로 강제 설정 (import 전에)
os.environ.setdefault('SECRET_KEY', 'test-secret-key')
os.environ.setdefault('WTF_CSRF_ENABLED', 'false')

from app import create_app


@pytest.fixture(scope='session')
def app():
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    os.environ['DATABASE'] = db_path

    flask_app = create_app()
    flask_app.config.update({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'DATABASE': db_path,
        'SMTP_HOST': '',        # 이메일 실제 전송 비활성화
        'SERVER_NAME': None,
    })

    yield flask_app

    os.close(db_fd)
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(app):
    """로그인된 일반 사용자 클라이언트"""
    with app.app_context():
        from app import get_db
        db = get_db()
        db.execute(
            'INSERT OR IGNORE INTO users (username, password_hash, nickname, email, balance) '
            'VALUES (?,?,?,?,?)',
            ('testuser', generate_password_hash('Test@1234'), '테스터', 'test@example.com', 10000)
        )
        db.commit()

    c = app.test_client()
    c.post('/auth/login', data={'username': 'testuser', 'password': 'Test@1234'})
    return c


@pytest.fixture
def auth_client2(app):
    """두 번째 일반 사용자 (IDOR 테스트용)"""
    with app.app_context():
        from app import get_db
        db = get_db()
        db.execute(
            'INSERT OR IGNORE INTO users (username, password_hash, nickname, email) '
            'VALUES (?,?,?,?)',
            ('otheruser', generate_password_hash('Other@5678'), '다른사람', 'other@example.com')
        )
        db.commit()

    c = app.test_client()
    c.post('/auth/login', data={'username': 'otheruser', 'password': 'Other@5678'})
    return c


@pytest.fixture
def admin_client(app):
    """관리자 클라이언트"""
    c = app.test_client()
    c.post('/auth/login', data={
        'username': app.config['ADMIN_USERNAME'],
        'password': app.config.get('ADMIN_PASSWORD') or 'Admin@Market1',
    })
    return c


def make_jpeg(w=100, h=100) -> bytes:
    """최소 유효 JPEG 바이트 생성"""
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (w, h), color=(100, 150, 200)).save(buf, format='JPEG')
    return buf.getvalue()


def make_png(w=100, h=100) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (w, h), color=(100, 150, 200)).save(buf, format='PNG')
    return buf.getvalue()
