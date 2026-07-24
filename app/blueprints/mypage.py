from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, session
from flask_login import login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from app.models.user import User
from app.models.product import Product
from app.security.file_validator import validate_and_save_image, delete_image
from app.utils.helpers import validate_password_strength

mypage_bp = Blueprint('mypage', __name__)


def _db():
    from flask import g, current_app
    import sqlite3
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'], detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db


@mypage_bp.route('/')
@login_required
def index():
    user = User.get_by_id(current_user.id)
    return render_template('mypage/index.html', user=user)


@mypage_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        nickname = request.form.get('nickname', '').strip()
        bio = request.form.get('bio', '').strip()
        image_file = request.files.get('profile_image')

        if not nickname or len(nickname) > 30:
            flash('닉네임을 1~30자로 입력해 주세요.', 'danger')
            return render_template('mypage/profile.html', user=User.get_by_id(current_user.id))

        image_path = None
        if image_file and image_file.filename:
            image_path, img_err = validate_and_save_image(image_file)
            if img_err:
                flash(f'이미지 오류: {img_err}', 'danger')
                return render_template('mypage/profile.html', user=User.get_by_id(current_user.id))
            if current_user.profile_image:
                delete_image(current_user.profile_image)

        User.update_profile(current_user.id, nickname, bio[:200], image_path)
        flash('프로필이 업데이트되었습니다.', 'success')
        return redirect(url_for('mypage.profile'))

    return render_template('mypage/profile.html', user=User.get_by_id(current_user.id))


@mypage_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_pw = request.form.get('current_password', '')
        new_pw = request.form.get('new_password', '')
        confirm_pw = request.form.get('confirm_password', '')

        stored = User.get_password_hash(current_user.id)
        if not check_password_hash(stored, current_pw):
            flash('현재 비밀번호가 올바르지 않습니다.', 'danger')
            return render_template('mypage/change_password.html')

        err = validate_password_strength(new_pw)
        if err:
            flash(err, 'danger')
            return render_template('mypage/change_password.html')

        if new_pw != confirm_pw:
            flash('새 비밀번호가 일치하지 않습니다.', 'danger')
            return render_template('mypage/change_password.html')

        if check_password_hash(stored, new_pw):
            flash('새 비밀번호는 현재 비밀번호와 달라야 합니다.', 'danger')
            return render_template('mypage/change_password.html')

        User.update_password(current_user.id, generate_password_hash(new_pw))
        flash('비밀번호가 변경되었습니다.', 'success')
        return redirect(url_for('mypage.index'))

    return render_template('mypage/change_password.html')


@mypage_bp.route('/products')
@login_required
def products():
    my_products = Product.by_seller(current_user.id, include_pending=True)
    return render_template('mypage/products.html', products=my_products)


@mypage_bp.route('/wishlist')
@login_required
def wishlist():
    db = _db()
    rows = db.execute(
        'SELECT p.*, u.nickname as seller_name FROM wishlist w '
        'JOIN products p ON w.product_id=p.id '
        'JOIN users u ON p.seller_id=u.id '
        "WHERE w.user_id=? AND p.status != 'deleted' ORDER BY w.created_at DESC",
        (current_user.id,)
    ).fetchall()
    return render_template('mypage/wishlist.html', products=rows)


@mypage_bp.route('/purchase-history')
@login_required
def purchase_history():
    db = _db()
    rows = db.execute(
        'SELECT t.*, p.title, p.image, u.nickname as seller_name '
        'FROM transactions t JOIN products p ON t.product_id=p.id '
        'JOIN users u ON t.seller_id=u.id '
        'WHERE t.buyer_id=? ORDER BY t.created_at DESC',
        (current_user.id,)
    ).fetchall()
    return render_template('mypage/purchase_history.html', transactions=rows)


@mypage_bp.route('/sale-history')
@login_required
def sale_history():
    db = _db()
    rows = db.execute(
        'SELECT t.*, p.title, p.image, u.nickname as buyer_name '
        'FROM transactions t JOIN products p ON t.product_id=p.id '
        'JOIN users u ON t.buyer_id=u.id '
        'WHERE t.seller_id=? ORDER BY t.created_at DESC',
        (current_user.id,)
    ).fetchall()
    return render_template('mypage/sale_history.html', transactions=rows)


@mypage_bp.route('/recently-viewed')
@login_required
def recently_viewed():
    ids = session.get('recently_viewed', [])
    if not ids:
        return render_template('mypage/recently_viewed.html', products=[])
    from app.models.product import Product
    products = [Product.get_by_id(pid) for pid in ids if Product.get_by_id(pid)]
    return render_template('mypage/recently_viewed.html', products=products)
