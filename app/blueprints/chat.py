import logging
import sqlite3
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, jsonify, current_app
from flask_login import login_required, current_user
from flask_socketio import join_room, leave_room, emit

from app.security.profanity import contains_profanity, censor
from app.security.decorators import not_banned
from app.models.notification import Notification

chat_bp = Blueprint('chat', __name__)
logger = logging.getLogger(__name__)

# Per-user message rate: max 20 messages per 10 seconds
_msg_lock = threading.Lock()
_msg_times: dict[int, deque] = defaultdict(lambda: deque())
_MSG_WINDOW = 10   # seconds
_MSG_MAX    = 20   # max messages in window


def _is_rate_limited(user_id: int) -> bool:
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=_MSG_WINDOW)
    with _msg_lock:
        q = _msg_times[user_id]
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= _MSG_MAX:
            return True
        q.append(now)
        return False


def _direct_db():
    """Direct connection for use inside SocketIO event handlers."""
    conn = sqlite3.connect(current_app.config['DATABASE'], detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def _db():
    from flask import g
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'], detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db


@chat_bp.route('/start/<int:product_id>')
@login_required
@not_banned
def start(product_id):
    from app.models.product import Product
    product = Product.get_by_id(product_id)
    if not product or product['status'] == 'deleted':
        abort(404)
    if product['seller_id'] == current_user.id:
        flash('자신의 상품에는 채팅을 시작할 수 없습니다.', 'warning')
        return redirect(url_for('products.detail', product_id=product_id))

    db = _db()
    room = db.execute(
        'SELECT * FROM chat_rooms WHERE product_id=? AND buyer_id=?',
        (product_id, current_user.id)
    ).fetchone()
    if not room:
        db.execute(
            'INSERT INTO chat_rooms (product_id, buyer_id, seller_id) VALUES (?,?,?)',
            (product_id, current_user.id, product['seller_id'])
        )
        db.commit()
        room = db.execute(
            'SELECT * FROM chat_rooms WHERE product_id=? AND buyer_id=?',
            (product_id, current_user.id)
        ).fetchone()
    return redirect(url_for('chat.room', room_id=room['id']))


@chat_bp.route('/room/<int:room_id>')
@login_required
def room(room_id):
    db = _db()
    chat_room = db.execute('SELECT * FROM chat_rooms WHERE id=?', (room_id,)).fetchone()
    if not chat_room:
        abort(404)
    if current_user.id not in (chat_room['buyer_id'], chat_room['seller_id']):
        abort(403)

    partner_id = (chat_room['seller_id']
                  if current_user.id == chat_room['buyer_id']
                  else chat_room['buyer_id'])

    is_blocked = db.execute(
        'SELECT 1 FROM blocks WHERE (blocker_id=? AND blocked_id=?) OR (blocker_id=? AND blocked_id=?)',
        (current_user.id, partner_id, partner_id, current_user.id)
    ).fetchone()

    messages = db.execute(
        'SELECT m.*, u.nickname FROM chat_messages m JOIN users u ON m.sender_id=u.id '
        'WHERE m.room_id=? ORDER BY m.created_at ASC LIMIT 200',
        (room_id,)
    ).fetchall()

    # 채팅방 진입 시 해당 채팅 알림 삭제 (확인하면 사라지도록)
    from app.models.notification import Notification
    room_link = url_for('chat.room', room_id=room_id)
    Notification.delete_by_link(current_user.id, room_link)

    from app.models.product import Product
    product = Product.get_by_id(chat_room['product_id'])

    from app.models.user import User
    partner = User.get_by_id(partner_id)

    return render_template('chat/room.html', chat_room=chat_room, messages=messages,
                           product=product, partner=partner, is_blocked=bool(is_blocked))


@chat_bp.route('/my-rooms')
@login_required
def my_rooms():
    db = _db()
    rooms = db.execute(
        'SELECT cr.*, p.title as product_title, p.image as product_image, '
        'b.nickname as buyer_name, s.nickname as seller_name, '
        '(SELECT content FROM chat_messages WHERE room_id=cr.id ORDER BY created_at DESC LIMIT 1) as last_msg '
        'FROM chat_rooms cr '
        'JOIN products p ON cr.product_id=p.id '
        'JOIN users b ON cr.buyer_id=b.id '
        'JOIN users s ON cr.seller_id=s.id '
        'WHERE (cr.buyer_id=? OR cr.seller_id=?) AND cr.is_active=1 '
        'ORDER BY cr.last_activity DESC',
        (current_user.id, current_user.id)
    ).fetchall()
    return render_template('chat/rooms.html', rooms=rooms)


@chat_bp.route('/upload/<int:room_id>', methods=['POST'])
@login_required
@not_banned
def upload_image(room_id):
    db = _db()
    chat_room = db.execute('SELECT * FROM chat_rooms WHERE id=?', (room_id,)).fetchone()
    if not chat_room:
        abort(404)
    if current_user.id not in (chat_room['buyer_id'], chat_room['seller_id']):
        abort(403)

    file = request.files.get('file')
    if not file:
        return jsonify({'ok': False, 'error': '파일이 없습니다.'}), 400

    from app.security.file_validator import validate_and_save_image
    path, err = validate_and_save_image(file)
    if err:
        return jsonify({'ok': False, 'error': err}), 400
    if not path:
        return jsonify({'ok': False, 'error': '파일이 없습니다.'}), 400

    return jsonify({'ok': True, 'url': '/static/' + path})


@chat_bp.route('/block/<int:user_id>', methods=['POST'])
@login_required
def block_user(user_id):
    if user_id == current_user.id:
        abort(400)
    db = _db()
    db.execute('INSERT OR IGNORE INTO blocks (blocker_id, blocked_id) VALUES (?,?)',
               (current_user.id, user_id))
    db.commit()
    flash('차단되었습니다.', 'info')
    return redirect(request.referrer or url_for('main.index'))


@chat_bp.route('/unblock/<int:user_id>', methods=['POST'])
@login_required
def unblock_user(user_id):
    db = _db()
    db.execute('DELETE FROM blocks WHERE blocker_id=? AND blocked_id=?', (current_user.id, user_id))
    db.commit()
    flash('차단이 해제되었습니다.', 'info')
    return redirect(request.referrer or url_for('main.index'))


def register_events(sio):
    @sio.on('join')
    def on_join(data):
        room_id = data.get('room_id')
        if room_id:
            join_room(f'chat_{room_id}')

    @sio.on('leave')
    def on_leave(data):
        room_id = data.get('room_id')
        if room_id:
            leave_room(f'chat_{room_id}')

    @sio.on('send_message')
    def on_message(data):
        if not current_user.is_authenticated or current_user.is_banned:
            emit('error', {'msg': '권한이 없습니다.'})
            return

        if _is_rate_limited(current_user.id):
            emit('error', {'msg': '메시지 전송이 너무 빠릅니다. 잠시 후 다시 시도해 주세요.'})
            return

        room_id = data.get('room_id')
        message_type = data.get('message_type', 'text')
        if message_type not in ('text', 'image'):
            message_type = 'text'
        content = (data.get('content') or '').strip()
        if not content or not room_id:
            return
        if message_type == 'text' and len(content) > 1000:
            return

        conn = _direct_db()
        try:
            chat_room = conn.execute('SELECT * FROM chat_rooms WHERE id=?', (room_id,)).fetchone()
            if not chat_room:
                return
            if current_user.id not in (chat_room['buyer_id'], chat_room['seller_id']):
                return

            partner_id = (chat_room['seller_id']
                          if current_user.id == chat_room['buyer_id']
                          else chat_room['buyer_id'])

            # Check if partner blocked the sender
            is_blocked = conn.execute(
                'SELECT 1 FROM blocks WHERE blocker_id=? AND blocked_id=?',
                (partner_id, current_user.id)
            ).fetchone()
            if is_blocked:
                emit('error', {'msg': '상대방이 당신을 차단했습니다.'})
                return

            # Check own user banned
            sender = conn.execute('SELECT is_banned FROM users WHERE id=?', (current_user.id,)).fetchone()
            if sender and sender['is_banned']:
                emit('error', {'msg': '계정이 정지되어 채팅할 수 없습니다.'})
                return

            # Censor profanity with * (text only — don't process image URLs)
            censored = False
            if message_type == 'text' and contains_profanity(content):
                content = censor(content)
                censored = True

            conn.execute(
                'INSERT INTO chat_messages (room_id, sender_id, content, message_type, has_profanity) '
                'VALUES (?,?,?,?,?)',
                (room_id, current_user.id, content, message_type, int(censored))
            )
            conn.execute('UPDATE chat_rooms SET last_activity=CURRENT_TIMESTAMP WHERE id=?', (room_id,))
            conn.commit()

            # 채팅 알림: "X님으로부터 N건의 채팅이 와있습니다." 형식으로 누적
            partner = conn.execute('SELECT notify_chat FROM users WHERE id=?', (partner_id,)).fetchone()
            if partner and partner['notify_chat']:
                import re as _re
                room_link = url_for('chat.room', room_id=room_id)
                existing = conn.execute(
                    'SELECT id, content FROM notifications WHERE user_id=? AND type=? AND link=? AND is_read=0',
                    (partner_id, 'chat', room_link)
                ).fetchone()
                if existing:
                    m = _re.search(r'(\d+)건', existing['content'])
                    cnt = int(m.group(1)) + 1 if m else 2
                    conn.execute(
                        'UPDATE notifications SET content=?, created_at=CURRENT_TIMESTAMP WHERE id=?',
                        (f'{current_user.nickname}님으로부터 {cnt}건의 채팅이 와있습니다.', existing['id'])
                    )
                else:
                    conn.execute(
                        'INSERT INTO notifications (user_id, type, content, link) VALUES (?,?,?,?)',
                        (partner_id, 'chat',
                         f'{current_user.nickname}님으로부터 1건의 채팅이 와있습니다.',
                         room_link)
                    )
                conn.commit()

            sio.emit('new_message', {
                'sender': current_user.nickname,
                'sender_id': current_user.id,
                'content': content,
                'message_type': message_type,
                'censored': censored,
                'time': datetime.now().strftime('%H:%M'),
            }, room=f'chat_{room_id}')
        finally:
            conn.close()

    @sio.on('typing')
    def on_typing(data):
        if not current_user.is_authenticated:
            return
        room_id = data.get('room_id')
        if room_id:
            sio.emit('user_typing', {'nickname': current_user.nickname},
                     room=f'chat_{room_id}', include_self=False)
