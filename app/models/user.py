from flask import current_app, g
from flask_login import UserMixin
import sqlite3


def _db():
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'], detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db


class User(UserMixin):
    def __init__(self, row):
        self.id = row['id']
        self.username = row['username']
        self.nickname = row['nickname']
        self.email = row['email']
        self.profile_image = row['profile_image']
        self.bio = row['bio']
        self.balance = row['balance']
        self.is_admin = bool(row['is_admin'])
        self.is_banned = bool(row['is_banned'])
        self.ban_reason = row['ban_reason']
        self.notify_chat = bool(row['notify_chat'])
        self.notify_sale = bool(row['notify_sale'])
        self.notify_wish = bool(row['notify_wish'])
        self.notify_quiet_start = row['notify_quiet_start'] if 'notify_quiet_start' in row.keys() else '22:00'
        self.notify_quiet_end = row['notify_quiet_end'] if 'notify_quiet_end' in row.keys() else '07:00'
        self.created_at = row['created_at']

    def get_id(self):
        return str(self.id)

    @staticmethod
    def get_by_id(user_id: int):
        row = _db().execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        return User(row) if row else None

    @staticmethod
    def get_by_username(username: str):
        row = _db().execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        return User(row) if row else None

    @staticmethod
    def get_by_email(email: str):
        row = _db().execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        return User(row) if row else None

    @staticmethod
    def create(username, password_hash, nickname, email):
        db = _db()
        db.execute(
            'INSERT INTO users (username, password_hash, nickname, email) VALUES (?,?,?,?)',
            (username, password_hash, nickname, email)
        )
        db.commit()

    @staticmethod
    def update_password(user_id: int, password_hash: str):
        db = _db()
        db.execute('UPDATE users SET password_hash=? WHERE id=?', (password_hash, user_id))
        db.commit()

    @staticmethod
    def update_profile(user_id: int, nickname: str, bio: str, profile_image=None):
        db = _db()
        if profile_image:
            db.execute('UPDATE users SET nickname=?, bio=?, profile_image=? WHERE id=?',
                       (nickname, bio, profile_image, user_id))
        else:
            db.execute('UPDATE users SET nickname=?, bio=? WHERE id=?', (nickname, bio, user_id))
        db.commit()

    @staticmethod
    def get_password_hash(user_id: int) -> str:
        row = _db().execute('SELECT password_hash FROM users WHERE id=?', (user_id,)).fetchone()
        return row['password_hash'] if row else ''

    @staticmethod
    def all_users(page=1, per_page=30):
        offset = (page - 1) * per_page
        rows = _db().execute('SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?',
                             (per_page, offset)).fetchall()
        total = _db().execute('SELECT COUNT(*) FROM users').fetchone()[0]
        return [User(r) for r in rows], total

    @staticmethod
    def ban(user_id: int, reason: str):
        db = _db()
        db.execute('UPDATE users SET is_banned=1, ban_reason=? WHERE id=?', (reason, user_id))
        db.commit()

    @staticmethod
    def unban(user_id: int):
        db = _db()
        db.execute('UPDATE users SET is_banned=0, ban_reason=NULL WHERE id=?', (user_id,))
        db.commit()

    @staticmethod
    def adjust_balance(user_id: int, delta: int):
        db = _db()
        db.execute('UPDATE users SET balance=balance+? WHERE id=?', (delta, user_id))
        db.commit()

    @staticmethod
    def update_notify(user_id: int, chat: int, sale: int, wish: int,
                      quiet_start: str = '22:00', quiet_end: str = '07:00'):
        db = _db()
        db.execute(
            'UPDATE users SET notify_chat=?, notify_sale=?, notify_wish=?, '
            'notify_quiet_start=?, notify_quiet_end=? WHERE id=?',
            (chat, sale, wish, quiet_start, quiet_end, user_id)
        )
        db.commit()
