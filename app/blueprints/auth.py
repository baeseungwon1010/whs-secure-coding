import os
import re
import glob
import secrets
import logging
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, request, flash, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from app.models.user import User
from app.utils.email import send_email
from app.utils.helpers import generate_temp_password, validate_password_strength
from app import limiter

auth_bp = Blueprint('auth', __name__)
logger = logging.getLogger(__name__)

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'logs')
_MAX_DB_RECORDS = 100
_MAX_FILE_LINES = 10000


def _rotate_if_needed(db):
    """DB가 _MAX_DB_RECORDS에 도달하면 로그 파일로 flush하고 DB를 비운다."""
    count = db.execute('SELECT COUNT(*) FROM auth_logs').fetchone()[0]
    if count < _MAX_DB_RECORDS:
        return
    rows = db.execute('SELECT * FROM auth_logs ORDER BY created_at ASC').fetchall()
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        target = None
        for fpath in sorted(glob.glob(os.path.join(_LOG_DIR, '*_auth_log.txt'))):
            try:
                with open(fpath, 'r', encoding='utf-8') as fp:
                    if sum(1 for _ in fp) < _MAX_FILE_LINES:
                        target = fpath
                        break
            except Exception:
                pass
        if not target:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            target = os.path.join(_LOG_DIR, f'{ts}_auth_log.txt')
        with open(target, 'a', encoding='utf-8') as fp:
            for r in rows:
                qt = (r['query_text'] or '').replace('\n', ' ')
                fp.write(f"{r['created_at']} | {r['event']} | {r['username']} | {r['ip']} | {qt}\n")
        db.execute('DELETE FROM auth_logs')
        db.commit()
    except Exception as exc:
        logger.error('Auth log rotation failed: %s', exc)


def _sanitize_log(value: str) -> str:
    """Log Injection 방지: 개행문자 제거."""
    if not value:
        return ''
    return re.sub(r'[\r\n\t]', ' ', str(value))


def _check_brute_force(username: str) -> tuple[bool, int]:
    """실패 횟수 확인. (잠금 여부, 남은 초)"""
    key_attempts = f'lf_attempts_{username}'
    key_until = f'lf_until_{username}'
    until = session.get(key_until)
    if until:
        remaining = (until - datetime.utcnow()).total_seconds()
        if remaining > 0:
            return True, int(remaining)
        session.pop(key_until, None)
        session.pop(key_attempts, None)
    return False, 0


def _record_fail(username: str):
    max_attempts = current_app.config.get('LOGIN_MAX_ATTEMPTS', 5)
    lockout = current_app.config.get('LOGIN_LOCKOUT_SECONDS', 300)
    key_attempts = f'lf_attempts_{username}'
    key_until = f'lf_until_{username}'
    attempts = session.get(key_attempts, 0) + 1
    session[key_attempts] = attempts
    if attempts >= max_attempts:
        session[key_until] = datetime.utcnow() + timedelta(seconds=lockout)
        session[key_attempts] = 0


def _clear_fail(username: str):
    session.pop(f'lf_attempts_{username}', None)
    session.pop(f'lf_until_{username}', None)


def _log_auth(event: str, username: str, request_obj, query_text: str = None):
    from app import get_db
    try:
        db = get_db()
        ip = request_obj.remote_addr
        db.execute(
            'INSERT INTO auth_logs (event, username, ip, query_text) VALUES (?,?,?,?)',
            (_sanitize_log(event), _sanitize_log(username), _sanitize_log(ip), _sanitize_log(query_text))
        )
        db.commit()
        _rotate_if_needed(db)
    except Exception:
        pass


@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit('10 per hour', methods=['POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')
        nickname = request.form.get('nickname', '').strip()
        email = request.form.get('email', '').strip().lower()

        if not all([username, password, confirm, nickname, email]):
            flash('모든 항목을 입력해 주세요.', 'danger')
            return render_template('auth/register.html')

        if len(username) < 4 or len(username) > 20:
            flash('아이디는 4~20자여야 합니다.', 'danger')
            return render_template('auth/register.html')

        if len(nickname) < 1 or len(nickname) > 20:
            flash('닉네임은 1~20자여야 합니다.', 'danger')
            return render_template('auth/register.html')

        if len(email) > 100:
            flash('이메일이 너무 깁니다. (최대 100자)', 'danger')
            return render_template('auth/register.html')

        err = validate_password_strength(password)
        if err:
            flash(err, 'danger')
            return render_template('auth/register.html')

        if password != confirm:
            flash('비밀번호가 일치하지 않습니다.', 'danger')
            return render_template('auth/register.html')

        if User.get_by_username(username):
            flash('이미 사용 중인 아이디입니다.', 'danger')
            return render_template('auth/register.html')

        if User.get_by_email(email):
            flash('이미 사용 중인 이메일입니다.', 'danger')
            return render_template('auth/register.html')

        from app import get_db
        if get_db().execute('SELECT 1 FROM users WHERE nickname=?', (nickname,)).fetchone():
            flash('이미 사용 중인 닉네임입니다.', 'danger')
            return render_template('auth/register.html')

        pw_hash = generate_password_hash(password)
        code = ''.join(secrets.choice('0123456789') for _ in range(7))
        session['pending_register'] = {
            'username': username,
            'password_hash': pw_hash,
            'nickname': nickname,
            'email': email,
            'code': code,
            'expires_at': (datetime.utcnow() + timedelta(minutes=3)).isoformat(),
        }
        body = (
            f'하늘마켓 이메일 인증 코드입니다.\n\n'
            f'인증 코드: {code}\n\n'
            f'이 코드는 3분간 유효합니다.\n'
            f'본인이 요청하지 않았다면 이 메일을 무시하세요.'
        )
        sent = send_email(email, '[하늘마켓] 이메일 인증 코드', body)
        if not sent:
            session.pop('pending_register', None)
            flash('이메일 전송에 실패했습니다. SMTP 설정을 확인해 주세요.', 'danger')
            return render_template('auth/register.html')
        flash(f'{email}로 인증 코드를 전송했습니다. 3분 내에 입력해 주세요.', 'info')
        return redirect(url_for('auth.verify_email'))

    return render_template('auth/register.html')


@auth_bp.route('/verify-email', methods=['GET', 'POST'])
@limiter.limit('10 per minute', methods=['POST'])
def verify_email():
    pending = session.get('pending_register')
    if not pending:
        flash('회원가입을 먼저 진행해 주세요.', 'warning')
        return redirect(url_for('auth.register'))

    if request.method == 'POST':
        code_input = request.form.get('code', '').strip()
        expires_at = datetime.fromisoformat(pending['expires_at'])
        if datetime.utcnow() > expires_at:
            session.pop('pending_register', None)
            flash('인증 코드가 만료되었습니다. 다시 회원가입해 주세요.', 'danger')
            return redirect(url_for('auth.register'))
        if not secrets.compare_digest(code_input, pending['code']):
            flash('인증 코드가 올바르지 않습니다.', 'danger')
            return render_template('auth/verify_email.html', email=pending['email'],
                                   expires_at=pending['expires_at'])
        try:
            User.create(pending['username'], pending['password_hash'],
                        pending['nickname'], pending['email'])
            _log_auth('register', pending['username'], request)
        except Exception:
            session.pop('pending_register', None)
            flash('이미 사용 중인 정보입니다. 다시 회원가입해 주세요.', 'danger')
            return redirect(url_for('auth.register'))
        session.pop('pending_register', None)
        flash('회원가입이 완료되었습니다. 로그인해 주세요.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/verify_email.html', email=pending['email'],
                           expires_at=pending['expires_at'])


@auth_bp.route('/check-username')
def check_username():
    from flask import jsonify
    username = request.args.get('username', '').strip()
    exists = bool(User.get_by_username(username)) if username else False
    return jsonify({'exists': exists})


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('30 per minute', methods=['POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = bool(request.form.get('remember'))

        # 브루트포스 잠금 확인
        locked, remaining = _check_brute_force(username)
        if locked:
            flash(f'로그인 시도가 너무 많습니다. {remaining}초 후 다시 시도해 주세요.', 'danger')
            return render_template('auth/login.html')

        login_query = f"SELECT id,password_hash FROM users WHERE username='{username}'"
        user = User.get_by_username(username)
        if not user or not check_password_hash(User.get_password_hash(user.id), password):
            _record_fail(username)
            _log_auth('login_fail', username, request, login_query)
            flash('아이디 또는 비밀번호가 올바르지 않습니다.', 'danger')
            return render_template('auth/login.html')

        if user.is_banned:
            flash(f'계정이 정지되었습니다. 사유: {user.ban_reason}', 'danger')
            return render_template('auth/login.html')

        _clear_fail(username)
        session.permanent = True  # PERMANENT_SESSION_LIFETIME 적용
        login_user(user, remember=remember)
        _log_auth('login', username, request, login_query)
        next_page = request.args.get('next')
        if next_page and not next_page.startswith('/'):
            next_page = None  # Open Redirect 방지
        return redirect(next_page or url_for('main.index'))

    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('로그아웃 되었습니다.', 'info')
    return redirect(url_for('main.index'))


@auth_bp.route('/find-id', methods=['GET', 'POST'])
def find_id():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = User.get_by_email(email)
        _log_auth('find_id', email, request)
        if user:
            send_email(email, '[마켓] 아이디 찾기',
                       f'회원님의 아이디는 [{user.username}] 입니다.')
        flash('이메일이 등록되어 있으면 아이디를 발송했습니다.', 'info')
        return redirect(url_for('auth.login'))
    return render_template('auth/find_id.html')


@auth_bp.route('/find-password', methods=['GET', 'POST'])
def find_password():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        user = User.get_by_username(username)
        _log_auth('find_pw', username, request)
        if user and user.email == email:
            temp_pw = generate_temp_password()
            User.update_password(user.id, generate_password_hash(temp_pw))
            send_email(email, '[마켓] 임시 비밀번호',
                       f'임시 비밀번호: {temp_pw}\n로그인 후 즉시 변경해 주세요.')
        flash('아이디와 이메일이 일치하면 임시 비밀번호를 발송했습니다.', 'info')
        return redirect(url_for('auth.login'))
    return render_template('auth/find_password.html')
