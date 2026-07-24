import logging
from flask import (Blueprint, render_template, redirect, url_for, request,
                   flash, abort, session, jsonify)
from flask_login import login_required, current_user

from app.models.product import Product
from app.models.notification import Notification
from app.security.file_validator import validate_and_save_image, delete_image
from app.security.profanity import has_banned_keyword, contains_profanity
from app.security.decorators import not_banned

products_bp = Blueprint('products', __name__)
logger = logging.getLogger(__name__)

CATEGORIES = ['전자기기', '의류', '도서', '가구', '스포츠', '식품', '뷰티', '기타']


def _log_product(event, product_id, user_id, detail=''):
    from app import get_db
    try:
        db = get_db()
        db.execute('INSERT INTO product_logs (event, product_id, user_id, detail) VALUES (?,?,?,?)',
                   (event, product_id, user_id, detail))
        db.commit()
    except Exception:
        pass


def _parse_location(form):
    """Parse lat/lng from form, return (lat, lng) or (None, None)."""
    try:
        lat = float(form.get('latitude', ''))
        lon = float(form.get('longitude', ''))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError
        return lat, lon
    except (TypeError, ValueError):
        return None, None


@products_bp.route('/new', methods=['GET', 'POST'])
@login_required
@not_banned
def create():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        price_str = request.form.get('price', '').strip()
        category = request.form.get('category', '').strip()
        region = request.form.get('region', '').strip()
        keywords = request.form.get('keywords', '').strip()
        stock_str = request.form.get('stock', '1').strip()
        image_file = request.files.get('image')

        if not all([title, description, price_str, category]):
            flash('필수 항목을 모두 입력해 주세요.', 'danger')
            return render_template('products/create.html', categories=CATEGORIES)

        try:
            price = int(price_str)
            if price < 0:
                raise ValueError
        except ValueError:
            flash('가격은 0 이상의 숫자여야 합니다.', 'danger')
            return render_template('products/create.html', categories=CATEGORIES)

        try:
            stock = int(stock_str)
            if stock < 1 or stock > 9999:
                raise ValueError
        except ValueError:
            flash('수량은 1~9999 사이여야 합니다.', 'danger')
            return render_template('products/create.html', categories=CATEGORIES)

        if category not in CATEGORIES:
            flash('유효한 카테고리를 선택해 주세요.', 'danger')
            return render_template('products/create.html', categories=CATEGORIES)

        if len(title) > 100:
            flash(f'상품명이 너무 깁니다. ({len(title)}/100자)', 'danger')
            return render_template('products/create.html', categories=CATEGORIES)
        if len(description) > 2000:
            flash(f'상품 설명이 너무 깁니다. ({len(description)}/2000자)', 'danger')
            return render_template('products/create.html', categories=CATEGORIES)
        if len(keywords) > 200:
            flash(f'키워드가 너무 깁니다. ({len(keywords)}/200자)', 'danger')
            return render_template('products/create.html', categories=CATEGORIES)
        if len(region) > 100:
            flash(f'지역명이 너무 깁니다. ({len(region)}/100자)', 'danger')
            return render_template('products/create.html', categories=CATEGORIES)

        status = 'pending' if has_banned_keyword(title + ' ' + description + ' ' + keywords) else 'active'

        image_path = None
        if image_file and image_file.filename:
            image_path, err = validate_and_save_image(image_file)
            if err:
                flash(f'이미지 오류: {err}', 'danger')
                return render_template('products/create.html', categories=CATEGORIES)

        lat, lon = _parse_location(request.form)

        product_id = Product.create(
            seller_id=current_user.id,
            title=title, description=description, price=price,
            category=category, region=region, image=image_path,
            keywords=keywords, status=status,
            latitude=lat, longitude=lon, stock=stock
        )
        _log_product('create', product_id, current_user.id)

        if status == 'pending':
            flash('금지 키워드가 감지되어 관리자 검토 후 게시됩니다.', 'warning')
        else:
            flash('상품이 등록되었습니다.', 'success')
        return redirect(url_for('products.detail', product_id=product_id))

    return render_template('products/create.html', categories=CATEGORIES)


@products_bp.route('/<int:product_id>')
def detail(product_id):
    product = Product.get_by_id(product_id)
    if not product or product['status'] == 'deleted':
        abort(404)

    if product['status'] == 'sold':
        # Sold product accessible only to seller/admin/buyer (for history)
        pass

    if product['status'] == 'pending' and (
        not current_user.is_authenticated or
        (current_user.id != product['seller_id'] and not current_user.is_admin)
    ):
        abort(404)

    # Dedup view counting
    from flask import make_response
    viewer_key = session.get('viewer_key')
    if not viewer_key:
        import uuid
        viewer_key = uuid.uuid4().hex
        session['viewer_key'] = viewer_key

    uid = current_user.id if current_user.is_authenticated else None
    Product.try_increment_views(product_id, user_id=uid, viewer_key=viewer_key if not uid else None)

    # Track recently viewed
    viewed = session.get('recently_viewed', [])
    if product_id in viewed:
        viewed.remove(product_id)
    viewed.insert(0, product_id)
    session['recently_viewed'] = viewed[:5]

    from app import get_db
    db = get_db()
    comments = db.execute(
        'SELECT c.*, u.nickname FROM comments c JOIN users u ON c.user_id=u.id '
        'WHERE c.product_id=? ORDER BY c.created_at ASC',
        (product_id,)
    ).fetchall()

    is_wished = False
    if current_user.is_authenticated:
        is_wished = bool(db.execute(
            'SELECT 1 FROM wishlist WHERE user_id=? AND product_id=?',
            (current_user.id, product_id)
        ).fetchone())

    return render_template('products/detail.html', product=product,
                           comments=comments, is_wished=is_wished)


@products_bp.route('/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
@not_banned
def edit(product_id):
    product = Product.get_by_id(product_id)
    if not product or product['status'] == 'deleted':
        abort(404)
    if product['seller_id'] != current_user.id and not current_user.is_admin:
        abort(403)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        price_str = request.form.get('price', '').strip()
        category = request.form.get('category', '').strip()
        region = request.form.get('region', '').strip()
        keywords = request.form.get('keywords', '').strip()
        stock_str = request.form.get('stock', '').strip()
        image_file = request.files.get('image')

        if not all([title, description, price_str, category]):
            flash('필수 항목을 모두 입력해 주세요.', 'danger')
            return render_template('products/edit.html', product=product, categories=CATEGORIES)

        try:
            price = int(price_str)
            if price < 0:
                raise ValueError
        except ValueError:
            flash('가격은 0 이상의 숫자여야 합니다.', 'danger')
            return render_template('products/edit.html', product=product, categories=CATEGORIES)

        stock = None
        if stock_str:
            try:
                stock = int(stock_str)
                if stock < 0 or stock > 9999:
                    raise ValueError
            except ValueError:
                flash('수량은 0~9999 사이여야 합니다.', 'danger')
                return render_template('products/edit.html', product=product, categories=CATEGORIES)

        if category not in CATEGORIES:
            abort(400)

        if len(title) > 100:
            flash(f'상품명이 너무 깁니다. ({len(title)}/100자)', 'danger')
            return render_template('products/edit.html', product=product, categories=CATEGORIES)
        if len(description) > 2000:
            flash(f'상품 설명이 너무 깁니다. ({len(description)}/2000자)', 'danger')
            return render_template('products/edit.html', product=product, categories=CATEGORIES)

        image_path = None
        if image_file and image_file.filename:
            image_path, err = validate_and_save_image(image_file)
            if err:
                flash(f'이미지 오류: {err}', 'danger')
                return render_template('products/edit.html', product=product, categories=CATEGORIES)
            if product['image']:
                delete_image(product['image'])

        lat, lon = _parse_location(request.form)
        Product.update(product_id, title, description, price, category, region,
                       image_path, keywords, lat, lon, stock)

        # If stock was set > 0 and product was sold, reactivate
        if stock and stock > 0 and product['status'] == 'sold':
            Product.set_status(product_id, 'active')

        _log_product('update', product_id, current_user.id)
        flash('상품이 수정되었습니다.', 'success')
        return redirect(url_for('products.detail', product_id=product_id))

    return render_template('products/edit.html', product=product, categories=CATEGORIES)


@products_bp.route('/<int:product_id>/delete', methods=['POST'])
@login_required
def delete(product_id):
    product = Product.get_by_id(product_id)
    if not product or product['status'] == 'deleted':
        abort(404)
    if product['seller_id'] != current_user.id and not current_user.is_admin:
        abort(403)

    if product['image']:
        delete_image(product['image'])
    Product.soft_delete(product_id)
    _log_product('delete', product_id, current_user.id)
    flash('상품이 삭제되었습니다.', 'success')
    return redirect(url_for('mypage.products'))


@products_bp.route('/<int:product_id>/wish', methods=['POST'])
@login_required
def toggle_wish(product_id):
    from app import get_db
    db = get_db()
    existing = db.execute(
        'SELECT id FROM wishlist WHERE user_id=? AND product_id=?',
        (current_user.id, product_id)
    ).fetchone()
    if existing:
        db.execute('DELETE FROM wishlist WHERE user_id=? AND product_id=?',
                   (current_user.id, product_id))
        wished = False
    else:
        db.execute('INSERT INTO wishlist (user_id, product_id) VALUES (?,?)',
                   (current_user.id, product_id))
        wished = True
        product = Product.get_by_id(product_id)
        if product and product['seller_id'] != current_user.id:
            Notification.create(
                product['seller_id'], 'wish',
                f'"{product["title"]}"을 {current_user.nickname}님이 찜했습니다.',
                url_for('products.detail', product_id=product_id)
            )
    db.commit()
    return jsonify({'wished': wished})


@products_bp.route('/<int:product_id>/comment', methods=['POST'])
@login_required
@not_banned
def add_comment(product_id):
    content = request.form.get('content', '').strip()
    parent_id = request.form.get('parent_id', type=int)

    if not content or len(content) > 500:
        flash('댓글 내용을 확인해 주세요. (1~500자)', 'danger')
        return redirect(url_for('products.detail', product_id=product_id) + '#comments')

    # Block profanity — do NOT register the comment
    if contains_profanity(content):
        return jsonify({
            'ok': False,
            'reason': '비속어가 포함되어 있습니다.'
        }), 400

    from app import get_db
    db = get_db()
    db.execute(
        'INSERT INTO comments (product_id, user_id, parent_id, content) VALUES (?,?,?,?)',
        (product_id, current_user.id, parent_id, content)
    )
    db.commit()

    # Support JSON or form submit
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'ok': True})
    return redirect(url_for('products.detail', product_id=product_id) + '#comments')


@products_bp.route('/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    from app import get_db
    db = get_db()
    comment = db.execute('SELECT * FROM comments WHERE id=?', (comment_id,)).fetchone()
    if not comment:
        abort(404)
    # Only comment author or admin can delete (NOT just the product seller)
    if comment['user_id'] != current_user.id and not current_user.is_admin:
        abort(403)
    by_admin = 1 if (current_user.is_admin and comment['user_id'] != current_user.id) else 0
    db.execute(
        'UPDATE comments SET is_deleted=1, deleted_by_admin=?, content="" WHERE id=?',
        (by_admin, comment_id)
    )
    db.commit()
    return redirect(request.referrer or url_for('main.index'))
