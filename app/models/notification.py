import sqlite3
from flask import current_app, g


def _db():
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'], detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db


class Notification:
    @staticmethod
    def create(user_id, ntype, content, link=None):
        db = _db()
        db.execute('INSERT INTO notifications (user_id, type, content, link) VALUES (?,?,?,?)',
                   (user_id, ntype, content, link))
        db.commit()

    @staticmethod
    def for_user(user_id, limit=50):
        return _db().execute(
            'SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT ?',
            (user_id, limit)
        ).fetchall()

    @staticmethod
    def unread_count(user_id):
        return _db().execute(
            'SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0',
            (user_id,)
        ).fetchone()[0]

    @staticmethod
    def mark_read(notif_id, user_id):
        db = _db()
        db.execute('UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?', (notif_id, user_id))
        db.commit()

    @staticmethod
    def mark_all_read(user_id):
        db = _db()
        db.execute('UPDATE notifications SET is_read=1 WHERE user_id=?', (user_id,))
        db.commit()

    @staticmethod
    def delete(notif_id, user_id):
        db = _db()
        db.execute('DELETE FROM notifications WHERE id=? AND user_id=?', (notif_id, user_id))
        db.commit()

    @staticmethod
    def delete_by_link(user_id, link):
        """채팅방 접속 시 해당 채팅 알림 삭제용."""
        db = _db()
        db.execute('DELETE FROM notifications WHERE user_id=? AND link=?', (user_id, link))
        db.commit()
