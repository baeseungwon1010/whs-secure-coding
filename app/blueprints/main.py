from flask import Blueprint, render_template, request, session
from app.models.product import Product

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    sort = request.args.get('sort', 'latest')
    page = max(1, request.args.get('page', 1, type=int))

    user_loc = session.get('user_location', {})
    from app.blueprints.search import _extract_district
    region_filter = _extract_district(user_loc.get('region', ''))

    products, total = Product.list_active(page=page, per_page=20, sort=sort, region_filter=region_filter)
    hot = Product.hot_products(days=7, limit=5)
    pages = (total + 19) // 20
    return render_template('index.html', products=products, hot=hot,
                           sort=sort, page=page, pages=pages, total=total,
                           user_location=user_loc)
