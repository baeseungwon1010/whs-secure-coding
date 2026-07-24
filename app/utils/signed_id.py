"""
Signed integer tokens using itsdangerous.
Used to pass critical IDs (product_id etc.) in URLs without exposing raw integers.
"""
from itsdangerous import URLSafeSerializer, BadSignature
from flask import current_app


def _serializer(salt: str) -> URLSafeSerializer:
    return URLSafeSerializer(current_app.config['SECRET_KEY'], salt=salt)


def sign_id(value: int, salt: str = 'id') -> str:
    """Return a signed, URL-safe token representing the integer."""
    return _serializer(salt).dumps(value)


def unsign_id(token: str, salt: str = 'id') -> int | None:
    """Decode a signed token back to int. Returns None if invalid."""
    try:
        return int(_serializer(salt).loads(token))
    except (BadSignature, ValueError, TypeError):
        return None
