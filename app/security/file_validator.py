import os
import uuid
from flask import current_app
from werkzeug.utils import secure_filename
from PIL import Image

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png'}
MAGIC_BYTES = {
    b'\xff\xd8\xff': 'jpeg',
    b'\x89PNG\r\n\x1a\n': 'png',
}
MAX_ASPECT_RATIO = 10.0  # 1:10 이상이면 거부


def _check_magic(stream) -> bool:
    header = stream.read(8)
    stream.seek(0)
    for magic in MAGIC_BYTES:
        if header[:len(magic)] == magic:
            return True
    return False


def _check_aspect_ratio(stream) -> bool:
    """True if ratio is within limit, False if too extreme."""
    try:
        img = Image.open(stream)
        w, h = img.size
        if min(w, h) == 0:
            return False
        ratio = max(w, h) / min(w, h)
        return ratio <= MAX_ASPECT_RATIO
    except Exception:
        return False
    finally:
        stream.seek(0)


def validate_and_save_image(file_storage) -> tuple[str | None, str | None]:
    """
    Returns (relative_path, None) on success,
            (None, error_message) on failure.
    """
    if not file_storage or file_storage.filename == '':
        return None, None  # no file provided — not an error

    filename = secure_filename(file_storage.filename)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

    if ext not in ALLOWED_EXTENSIONS:
        return None, f'허용된 이미지 형식은 jpg/jpeg/png 입니다.'

    if not _check_magic(file_storage.stream):
        return None, '파일 내용이 이미지가 아닙니다.'

    if not _check_aspect_ratio(file_storage.stream):
        return None, f'이미지 가로세로 비율이 1:{int(MAX_ASPECT_RATIO)}을 초과합니다.'

    safe_name = uuid.uuid4().hex + '.' + ext
    upload_dir = current_app.config['UPLOAD_FOLDER']
    dest = os.path.join(upload_dir, safe_name)
    dest = os.path.realpath(dest)
    if not dest.startswith(os.path.realpath(upload_dir)):
        return None, '경로 오류.'

    file_storage.stream.seek(0)
    file_storage.save(dest)
    return 'uploads/' + safe_name, None


def delete_image(relative_path: str):
    if not relative_path:
        return
    upload_dir = current_app.config['UPLOAD_FOLDER']
    abs_path = os.path.realpath(os.path.join(os.path.dirname(upload_dir), relative_path))
    if abs_path.startswith(os.path.realpath(upload_dir)) and os.path.isfile(abs_path):
        os.remove(abs_path)
