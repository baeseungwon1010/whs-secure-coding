from flask import Blueprint, render_template, redirect, url_for, request, jsonify
from flask_login import login_required, current_user
from app.models.notification import Notification
from app.models.user import User

notifications_bp = Blueprint('notifications', __name__)


@notifications_bp.route('/')
@login_required
def index():
    notifs = Notification.for_user(current_user.id, limit=50)
    Notification.mark_all_read(current_user.id)
    return render_template('notifications/index.html', notifs=notifs)


@notifications_bp.route('/read/<int:notif_id>', methods=['POST'])
@login_required
def mark_read(notif_id):
    Notification.mark_read(notif_id, current_user.id)
    return jsonify({'ok': True})


@notifications_bp.route('/delete/<int:notif_id>', methods=['POST'])
@login_required
def delete(notif_id):
    """공지를 제외한 알림: 확인 시 완전 삭제."""
    Notification.delete(notif_id, current_user.id)
    return jsonify({'ok': True})


@notifications_bp.route('/count')
@login_required
def count():
    n = Notification.unread_count(current_user.id)
    return jsonify({'count': n})


def _valid_time(t: str) -> str:
    """Validate HH:MM format; return default if invalid."""
    try:
        h, m = t.split(':')
        if 0 <= int(h) <= 23 and 0 <= int(m) <= 59:
            return f'{int(h):02d}:{int(m):02d}'
    except Exception:
        pass
    return '22:00'


@notifications_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        chat = int(bool(request.form.get('notify_chat')))
        sale = int(bool(request.form.get('notify_sale')))
        wish = int(bool(request.form.get('notify_wish')))
        quiet_start = _valid_time(request.form.get('quiet_start', '22:00'))
        quiet_end = _valid_time(request.form.get('quiet_end', '07:00'))
        User.update_notify(current_user.id, chat, sale, wish, quiet_start, quiet_end)
        from flask import flash
        flash('알림 설정이 저장되었습니다.', 'success')
        return redirect(url_for('notifications.settings'))
    return render_template('notifications/settings.html')
