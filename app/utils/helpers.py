import re
import secrets
import string
from datetime import datetime, timezone


def generate_temp_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits + '!@#$'
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def time_ago(dt) -> str:
    if dt is None:
        return ''
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return dt
    now = datetime.now()
    diff = now - dt.replace(tzinfo=None) if dt.tzinfo else now - dt
    seconds = int(diff.total_seconds())
    if seconds < 60:
        return '방금 전'
    if seconds < 3600:
        return f'{seconds // 60}분 전'
    if seconds < 86400:
        return f'{seconds // 3600}시간 전'
    if seconds < 2592000:
        return f'{seconds // 86400}일 전'
    return dt.strftime('%Y-%m-%d')


def validate_password_strength(pw: str) -> str | None:
    """Return error message or None if valid."""
    if len(pw) < 8:
        return '비밀번호는 8자 이상이어야 합니다.'
    if not re.search(r'[A-Za-z]', pw):
        return '영문자를 포함해야 합니다.'
    if not re.search(r'\d', pw):
        return '숫자를 포함해야 합니다.'
    return None
