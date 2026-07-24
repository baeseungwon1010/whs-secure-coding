from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, jsonify
from flask_login import login_required, current_user

from app.models.product import Product
from app.models.user import User
from app.models.report import Report
from app.models.notification import Notification
from app.security.decorators import admin_required
from app.security.file_validator import delete_image

admin_bp = Blueprint('admin', __name__)


def _audit(action: str, target: str = ''):
    """관리자 작업 Audit Log 기록."""
    try:
        db = _db()
        admin_id = current_user.id if current_user.is_authenticated else 0
        import re
        clean = lambda s: re.sub(r'[\r\n\t]', ' ', str(s))
        db.execute(
            'INSERT INTO audit_logs (admin_id, action, target, ip) VALUES (?,?,?,?)',
            (admin_id, clean(action), clean(target), clean(request.remote_addr)),
        )
        db.commit()
    except Exception:
        pass


def _db():
    from flask import g, current_app
    import sqlite3
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'], detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db


@admin_bp.route('/')
@login_required
@admin_required
def dashboard():
    db = _db()
    stats = {
        'users': db.execute('SELECT COUNT(*) FROM users').fetchone()[0],
        'products': db.execute("SELECT COUNT(*) FROM products WHERE status != 'deleted'").fetchone()[0],
        'transactions': db.execute('SELECT COUNT(*) FROM transactions').fetchone()[0],
        'reports': db.execute("SELECT COUNT(*) FROM reports WHERE status='pending'").fetchone()[0],
        'revenue': db.execute('SELECT COALESCE(SUM(amount),0) FROM transactions').fetchone()[0],
    }
    recent_reports = Report.all_reports(page=1, per_page=5)[0]
    recent_users = db.execute('SELECT * FROM users ORDER BY created_at DESC LIMIT 5').fetchall()
    return render_template('admin/dashboard.html', stats=stats,
                           recent_reports=recent_reports, recent_users=recent_users)


@admin_bp.route('/products')
@login_required
@admin_required
def products():
    page = max(1, request.args.get('page', 1, type=int))
    rows, total = Product.all_for_admin(page=page)
    pending = Product.pending_products()
    pages = (total + 29) // 30
    return render_template('admin/products.html', products=rows, pending=pending,
                           page=page, pages=pages, total=total)


@admin_bp.route('/products/<int:product_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_product(product_id):
    product = Product.get_by_id(product_id)
    if not product:
        abort(404)
    Product.set_status(product_id, 'active')
    Notification.create(product['seller_id'], 'admin',
                        f'상품 "{product["title"]}"이 승인되었습니다.',
                        url_for('products.detail', product_id=product_id))
    flash('상품이 승인되었습니다.', 'success')
    return redirect(url_for('admin.products'))


@admin_bp.route('/products/<int:product_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_product(product_id):
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash('삭제 사유를 입력해 주세요.', 'danger')
        return redirect(url_for('admin.products'))

    product = Product.get_by_id(product_id)
    if not product:
        abort(404)

    if product['image']:
        delete_image(product['image'])
    Product.soft_delete(product_id)
    Notification.create(product['seller_id'], 'admin',
                        f'상품 "{product["title"]}"이 관리자에 의해 삭제되었습니다. 사유: {reason}',
                        None)
    _audit('delete_product', f'product_id={product_id} reason={reason}')
    flash('상품이 삭제되었습니다.', 'success')
    return redirect(url_for('admin.products'))


@admin_bp.route('/users')
@login_required
@admin_required
def users():
    page = max(1, request.args.get('page', 1, type=int))
    user_list, total = User.all_users(page=page)
    pages = (total + 29) // 30
    return render_template('admin/users.html', users=user_list, page=page, pages=pages, total=total)


@admin_bp.route('/users/<int:user_id>/ban', methods=['POST'])
@login_required
@admin_required
def ban_user(user_id):
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash('정지 사유를 입력해 주세요.', 'danger')
        return redirect(url_for('admin.users'))
    if user_id == current_user.id:
        flash('자신을 정지할 수 없습니다.', 'danger')
        return redirect(url_for('admin.users'))
    User.ban(user_id, reason)
    Notification.create(user_id, 'admin', f'계정이 정지되었습니다. 사유: {reason}', None)
    _audit('ban_user', f'user_id={user_id} reason={reason}')
    flash('사용자가 정지되었습니다.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/unban', methods=['POST'])
@login_required
@admin_required
def unban_user(user_id):
    User.unban(user_id)
    Notification.create(user_id, 'admin', '계정 정지가 해제되었습니다.', None)
    _audit('unban_user', f'user_id={user_id}')
    flash('정지가 해제되었습니다.', 'success')
    return redirect(url_for('admin.users'))


# ── 신고 목록 (간략 표시) ──

@admin_bp.route('/reports')
@login_required
@admin_required
def reports():
    status = request.args.get('status')
    page = max(1, request.args.get('page', 1, type=int))
    rows, total = Report.all_reports(status=status or None, page=page)
    pages = (total + 19) // 20
    return render_template('admin/reports.html', reports=rows, status=status,
                           page=page, pages=pages, total=total)


# ── 신고 상세 페이지 ──

@admin_bp.route('/reports/<int:report_id>')
@login_required
@admin_required
def report_detail(report_id):
    report = Report.get_by_id(report_id)
    if not report:
        abort(404)
    db = _db()

    product = None
    chat_messages = None
    chat_room = None

    if report['target_type'] == 'product':
        product = Product.get_by_id(report['target_id'])
    elif report['target_type'] == 'chat':
        chat_messages = db.execute(
            'SELECT m.*, u.nickname FROM chat_messages m JOIN users u ON m.sender_id=u.id '
            'WHERE m.room_id=? ORDER BY m.created_at ASC',
            (report['target_id'],)
        ).fetchall()
        chat_room = db.execute('SELECT * FROM chat_rooms WHERE id=?',
                               (report['target_id'],)).fetchone()

    return render_template('admin/report_detail.html',
                           report=report, product=product,
                           chat_messages=chat_messages, chat_room=chat_room)


@admin_bp.route('/reports/<int:report_id>/respond', methods=['POST'])
@login_required
@admin_required
def respond_report(report_id):
    response = request.form.get('response', '').strip()
    status = request.form.get('status', 'resolved')
    if status not in ('resolved', 'dismissed', 'processing'):
        abort(400)
    Report.update_status(report_id, status, response)
    report = Report.get_by_id(report_id)
    if report:
        Notification.create(report['reporter_id'], 'report',
                            f'신고 "{report["title"]}" 처리 결과: {status}',
                            url_for('reports.my_reports'))
    _audit('respond_report', f'report_id={report_id} status={status}')
    flash('답변이 전송되었습니다.', 'success')
    return redirect(url_for('admin.reports'))


# ── 공지사항 ──

@admin_bp.route('/notices', methods=['GET', 'POST'])
@login_required
@admin_required
def notices():
    db = _db()
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        if not title or not content:
            flash('제목과 내용을 입력해 주세요.', 'danger')
        else:
            cur = db.execute('INSERT INTO notices (admin_id, title, content) VALUES (?,?,?)',
                             (current_user.id, title, content))
            db.commit()
            notice_id = cur.lastrowid
            all_ids = db.execute('SELECT id FROM users WHERE is_admin=0').fetchall()
            for row in all_ids:
                Notification.create(row['id'], 'notice', f'[공지] {title}',
                                    url_for('admin.notice_view', notice_id=notice_id))
            flash('공지가 등록되었습니다.', 'success')
    notice_list = db.execute(
        'SELECT n.*, u.nickname FROM notices n JOIN users u ON n.admin_id=u.id '
        'ORDER BY n.created_at DESC LIMIT 30'
    ).fetchall()
    return render_template('admin/notices.html', notices=notice_list)


@admin_bp.route('/notices/<int:notice_id>/view')
@login_required
def notice_view(notice_id):
    """공지 내용 조회 — 관리자 권한 불필요, 일반 사용자도 접근 가능."""
    db = _db()
    notice = db.execute(
        'SELECT id, title, content, created_at FROM notices WHERE id=?', (notice_id,)
    ).fetchone()
    if not notice:
        abort(404)
    return jsonify({
        'id': notice['id'],
        'title': notice['title'],
        'content': notice['content'],
        'created_at': str(notice['created_at']),
    })


@admin_bp.route('/logs')
@login_required
@admin_required
def logs():
    db = _db()
    auth_logs = db.execute('SELECT * FROM auth_logs ORDER BY created_at DESC LIMIT 100').fetchall()
    product_logs = db.execute('SELECT * FROM product_logs ORDER BY created_at DESC LIMIT 100').fetchall()
    return render_template('admin/logs.html', auth_logs=auth_logs, product_logs=product_logs)


@admin_bp.route('/chat-inspect/<int:room_id>')
@login_required
@admin_required
def chat_inspect(room_id):
    db = _db()
    # 신고된 채팅방의 전체 메시지를 보여줌 (비속어만이 아닌)
    messages = db.execute(
        'SELECT m.*, u.nickname FROM chat_messages m JOIN users u ON m.sender_id=u.id '
        'WHERE m.room_id=? ORDER BY m.created_at ASC LIMIT 500',
        (room_id,)
    ).fetchall()
    room = db.execute('SELECT cr.*, p.title as product_title, '
                      'b.nickname as buyer_name, s.nickname as seller_name '
                      'FROM chat_rooms cr '
                      'JOIN products p ON cr.product_id=p.id '
                      'JOIN users b ON cr.buyer_id=b.id '
                      'JOIN users s ON cr.seller_id=s.id '
                      'WHERE cr.id=?', (room_id,)).fetchone()
    return render_template('admin/chat_inspect.html', messages=messages, room=room)
