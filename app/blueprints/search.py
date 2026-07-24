import re
from flask import Blueprint, render_template, request, session, jsonify
from flask_login import current_user
from app.models.product import Product
from app import limiter

search_bp = Blueprint('search', __name__)
MAX_RECENT = 5


def _extract_district(region: str) -> str:
    """구/군 단위 지역명 추출 (예: '서울 강남구' → '강남구')."""
    if not region:
        return ''
    m = re.search(r'(\S+(?:구|군))', region)
    if m:
        return m.group(1)
    return region.strip()


def _save_search(query: str):
    """Save query to DB for logged-in user, keep last MAX_RECENT."""
    if not current_user.is_authenticated or not query:
        return
    from app import get_db
    db = get_db()
    # Remove duplicate
    db.execute('DELETE FROM recent_searches WHERE user_id=? AND query=?',
               (current_user.id, query))
    db.execute('INSERT INTO recent_searches (user_id, query) VALUES (?,?)',
               (current_user.id, query))
    # Keep only latest MAX_RECENT
    db.execute(
        'DELETE FROM recent_searches WHERE user_id=? AND id NOT IN '
        '(SELECT id FROM recent_searches WHERE user_id=? ORDER BY searched_at DESC LIMIT ?)',
        (current_user.id, current_user.id, MAX_RECENT)
    )
    db.commit()


def _load_searches() -> list[str]:
    """Load recent searches from DB (logged-in) or session (guest)."""
    if current_user.is_authenticated:
        from app import get_db
        rows = get_db().execute(
            'SELECT query FROM recent_searches WHERE user_id=? ORDER BY searched_at DESC LIMIT ?',
            (current_user.id, MAX_RECENT)
        ).fetchall()
        return [r['query'] for r in rows]
    return session.get('recent_searches', [])


@search_bp.route('/')
@limiter.limit('60 per minute')
def search():
    query = request.args.get('q', '').strip()[:100]  # 검색어 길이 제한
    sort = request.args.get('sort', 'latest')
    page = max(1, min(request.args.get('page', 1, type=int), 1000))

    # 세션에서 사용자 위치 로드 (URL 파라미터 사용 금지)
    user_loc = session.get('user_location', {})
    region_filter = _extract_district(user_loc.get('region', ''))

    if query:
        _save_search(query)
        products, total = Product.search(
            query, sort=sort, page=page, region_filter=region_filter
        )
    else:
        products, total = Product.list_active(
            page=page, per_page=20, sort=sort, region_filter=region_filter
        )

    pages = (total + 19) // 20
    recent = _load_searches()
    return render_template('search/results.html', products=products, query=query,
                           sort=sort, page=page, pages=pages, total=total,
                           recent_searches=recent, user_location=user_loc)


@search_bp.route('/set-location', methods=['POST'])
def set_location():
    """위치를 세션에 저장 (POST로만 — URL에 위치 파라미터 노출 금지)."""
    data = request.get_json(silent=True) or request.form
    region = (data.get('region') or '').strip()[:100]
    try:
        lat = float(data.get('lat') or 0) or None
        lon = float(data.get('lon') or 0) or None
    except (TypeError, ValueError):
        lat = lon = None

    if region:
        session['user_location'] = {'region': region, 'lat': lat, 'lon': lon}
    else:
        session.pop('user_location', None)
    return jsonify({'ok': True, 'region': region})


@search_bp.route('/clear-location', methods=['POST'])
def clear_location():
    session.pop('user_location', None)
    return jsonify({'ok': True})


@search_bp.route('/recent')
def get_recent():
    """AJAX endpoint: return recent searches as JSON."""
    return jsonify({'searches': _load_searches()})


@search_bp.route('/clear-history', methods=['POST'])
def clear_history():
    if current_user.is_authenticated:
        from app import get_db
        db = get_db()
        db.execute('DELETE FROM recent_searches WHERE user_id=?', (current_user.id,))
        db.commit()
    session.pop('recent_searches', None)
    return jsonify({'ok': True})


@search_bp.route('/delete-one', methods=['POST'])
def delete_one():
    """AJAX: delete a single recent search item."""
    query = request.get_json(silent=True, force=True)
    if not query:
        query = request.form
    q = (query.get('q') or '').strip()
    if not q:
        return jsonify({'ok': False}), 400
    if current_user.is_authenticated:
        from app import get_db
        db = get_db()
        db.execute('DELETE FROM recent_searches WHERE user_id=? AND query=?',
                   (current_user.id, q))
        db.commit()
    else:
        searches = session.get('recent_searches', [])
        session['recent_searches'] = [s for s in searches if s != q]
    return jsonify({'ok': True})
