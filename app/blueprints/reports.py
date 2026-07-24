from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_required, current_user

from app.models.report import Report
from app.models.notification import Notification
from app.security.file_validator import validate_and_save_image
from app.security.decorators import not_banned

reports_bp = Blueprint('reports', __name__)

CATEGORIES = ['사기', '음란물', '불법 상품', '비방/욕설', '스팸', '개인정보 침해', '기타']


def _target_display(target_type: str, target_id: int) -> str:
    """Return a human-readable label for the report target."""
    from app import get_db
    db = get_db()
    if target_type == 'user':
        row = db.execute('SELECT nickname FROM users WHERE id=?', (target_id,)).fetchone()
        return f'사용자 "{row["nickname"]}"' if row else f'사용자 #{target_id}'
    if target_type == 'product':
        row = db.execute('SELECT title FROM products WHERE id=?', (target_id,)).fetchone()
        return f'상품 "{row["title"]}"' if row else f'상품 #{target_id}'
    if target_type == 'chat':
        return f'채팅방 #{target_id}'
    return f'{target_type} #{target_id}'


@reports_bp.route('/new', methods=['GET', 'POST'])
@login_required
@not_banned
def create():
    target_type = request.args.get('type', 'user')
    target_id = request.args.get('id', 0, type=int)
    target_display = _target_display(target_type, target_id)

    if request.method == 'POST':
        target_type = request.form.get('target_type', 'user')
        target_id = request.form.get('target_id', 0, type=int)
        title = request.form.get('title', '').strip()
        category = request.form.get('category', '').strip()
        detail = request.form.get('detail', '').strip()
        image_file = request.files.get('image')

        if not all([title, category, detail]) or target_id == 0:
            flash('모든 필수 항목을 입력해 주세요.', 'danger')
            return render_template('reports/create.html', categories=CATEGORIES,
                                   target_type=target_type, target_id=target_id)

        if len(detail) > 1000:
            flash('상세 내용은 1000자 이내로 입력해 주세요.', 'danger')
            return render_template('reports/create.html', categories=CATEGORIES,
                                   target_type=target_type, target_id=target_id)

        if category not in CATEGORIES:
            abort(400)

        image_path = None
        if image_file and image_file.filename:
            image_path, img_err = validate_and_save_image(image_file)
            if img_err:
                flash(f'이미지 오류: {img_err}', 'danger')
                return render_template('reports/create.html', categories=CATEGORIES,
                                       target_type=target_type, target_id=target_id,
                                       target_display=_target_display(target_type, target_id))

        report_id = Report.create(current_user.id, target_type, target_id, title, category, detail, image_path)

        # Auto-process: if target has many reports, flag for admin
        count = Report.count_by_target(target_type, target_id)
        if count >= 3:
            Notification.create(
                1, 'report',
                f'[자동감지] {target_type} ID {target_id}에 신고 {count}건 누적',
                url_for('admin.reports')
            )

        flash('신고가 접수되었습니다.', 'success')
        return redirect(url_for('main.index'))

    return render_template('reports/create.html', categories=CATEGORIES,
                           target_type=target_type, target_id=target_id,
                           target_display=target_display)


@reports_bp.route('/my')
@login_required
def my_reports():
    from app import get_db
    db = get_db()
    rows = db.execute(
        'SELECT * FROM reports WHERE reporter_id=? ORDER BY created_at DESC',
        (current_user.id,)
    ).fetchall()
    return render_template('reports/my_reports.html', reports=rows)
