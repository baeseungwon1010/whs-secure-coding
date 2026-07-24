import sqlite3
from flask import current_app, g


def _db():
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'], detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db


class Report:
    @staticmethod
    def create(reporter_id, target_type, target_id, title, category, detail, image=None):
        db = _db()
        cur = db.execute(
            'INSERT INTO reports (reporter_id, target_type, target_id, title, category, detail, image) '
            'VALUES (?,?,?,?,?,?,?)',
            (reporter_id, target_type, target_id, title, category, detail, image)
        )
        db.commit()
        return cur.lastrowid

    @staticmethod
    def get_by_id(report_id):
        return _db().execute(
            'SELECT r.*, u.nickname as reporter_name FROM reports r '
            'JOIN users u ON r.reporter_id=u.id WHERE r.id=?',
            (report_id,)
        ).fetchone()

    @staticmethod
    def all_reports(status=None, page=1, per_page=20):
        offset = (page - 1) * per_page
        if status:
            rows = _db().execute(
                'SELECT r.*, u.nickname as reporter_name FROM reports r JOIN users u ON r.reporter_id=u.id '
                'WHERE r.status=? ORDER BY r.created_at DESC LIMIT ? OFFSET ?',
                (status, per_page, offset)
            ).fetchall()
            total = _db().execute('SELECT COUNT(*) FROM reports WHERE status=?', (status,)).fetchone()[0]
        else:
            rows = _db().execute(
                'SELECT r.*, u.nickname as reporter_name FROM reports r JOIN users u ON r.reporter_id=u.id '
                'ORDER BY r.created_at DESC LIMIT ? OFFSET ?',
                (per_page, offset)
            ).fetchall()
            total = _db().execute('SELECT COUNT(*) FROM reports').fetchone()[0]
        return rows, total

    @staticmethod
    def update_status(report_id, status, response=None):
        db = _db()
        db.execute(
            'UPDATE reports SET status=?, admin_response=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
            (status, response, report_id)
        )
        db.commit()

    @staticmethod
    def count_by_target(target_type, target_id):
        return _db().execute(
            'SELECT COUNT(*) FROM reports WHERE target_type=? AND target_id=?',
            (target_type, target_id)
        ).fetchone()[0]
