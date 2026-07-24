import sqlite3
from flask import current_app, g
from app.utils.location import haversine_km, bounding_box


def _db():
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'], detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db


class Product:
    @staticmethod
    def create(seller_id, title, description, price, category, region,
               image, keywords, status='active', latitude=None, longitude=None, stock=1):
        db = _db()
        cur = db.execute(
            'INSERT INTO products '
            '(seller_id, title, description, price, category, region, image, keywords, status, latitude, longitude, stock) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (seller_id, title, description, price, category, region,
             image, keywords, status, latitude, longitude, stock)
        )
        db.commit()
        return cur.lastrowid

    @staticmethod
    def get_by_id(product_id):
        return _db().execute(
            'SELECT p.*, u.nickname as seller_name, u.profile_image as seller_img '
            'FROM products p JOIN users u ON p.seller_id=u.id WHERE p.id=?',
            (product_id,)
        ).fetchone()

    @staticmethod
    def try_increment_views(product_id, user_id=None, viewer_key=None) -> bool:
        """Returns True if this is a new view (not a duplicate)."""
        db = _db()
        if user_id:
            existing = db.execute(
                'SELECT id FROM product_views WHERE product_id=? AND user_id=?',
                (product_id, user_id)
            ).fetchone()
            if existing:
                return False
            db.execute('INSERT INTO product_views (product_id, user_id) VALUES (?,?)',
                       (product_id, user_id))
        else:
            if not viewer_key:
                return False
            existing = db.execute(
                'SELECT id FROM product_views WHERE product_id=? AND viewer_key=?',
                (product_id, viewer_key)
            ).fetchone()
            if existing:
                return False
            db.execute('INSERT INTO product_views (product_id, viewer_key) VALUES (?,?)',
                       (product_id, viewer_key))
        db.execute('UPDATE products SET views=views+1 WHERE id=?', (product_id,))
        db.commit()
        return True

    @staticmethod
    def update(product_id, title, description, price, category, region,
               image, keywords, latitude=None, longitude=None, stock=None):
        db = _db()
        if image and stock is not None:
            db.execute(
                'UPDATE products SET title=?,description=?,price=?,category=?,region=?,image=?,'
                'keywords=?,latitude=?,longitude=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                (title, description, price, category, region, image,
                 keywords, latitude, longitude, stock, product_id)
            )
        elif image:
            db.execute(
                'UPDATE products SET title=?,description=?,price=?,category=?,region=?,image=?,'
                'keywords=?,latitude=?,longitude=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                (title, description, price, category, region, image,
                 keywords, latitude, longitude, product_id)
            )
        elif stock is not None:
            db.execute(
                'UPDATE products SET title=?,description=?,price=?,category=?,region=?,'
                'keywords=?,latitude=?,longitude=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                (title, description, price, category, region,
                 keywords, latitude, longitude, stock, product_id)
            )
        else:
            db.execute(
                'UPDATE products SET title=?,description=?,price=?,category=?,region=?,'
                'keywords=?,latitude=?,longitude=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                (title, description, price, category, region,
                 keywords, latitude, longitude, product_id)
            )
        db.commit()

    @staticmethod
    def restock(product_id, additional: int):
        db = _db()
        db.execute(
            "UPDATE products SET stock=stock+?, "
            "status=CASE WHEN status='sold' OR status='active' THEN 'active' ELSE status END, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (additional, product_id)
        )
        db.commit()

    @staticmethod
    def decrement_stock(product_id, qty: int = 1):
        db = _db()
        db.execute('UPDATE products SET stock=MAX(0, stock-?) WHERE id=?', (qty, product_id))
        # Auto-close when stock hits 0
        db.execute(
            "UPDATE products SET status='sold' WHERE id=? AND stock<=0",
            (product_id,)
        )
        db.commit()

    @staticmethod
    def soft_delete(product_id):
        db = _db()
        db.execute("UPDATE products SET status='deleted' WHERE id=?", (product_id,))
        db.commit()

    @staticmethod
    def set_status(product_id, status):
        db = _db()
        db.execute('UPDATE products SET status=? WHERE id=?', (status, product_id))
        db.commit()

    @staticmethod
    def list_active(page=1, per_page=20, sort='latest', region_filter=''):
        offset = (page - 1) * per_page
        order = _sort_clause(sort)
        params: list = []
        where = "p.status='active'"
        if region_filter:
            where += " AND p.region LIKE ?"
            params.append(f'%{region_filter}%')
        rows = _db().execute(
            f"SELECT p.*, u.nickname as seller_name FROM products p JOIN users u ON p.seller_id=u.id "
            f"WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
            params + [per_page, offset]
        ).fetchall()
        total = _db().execute(
            f"SELECT COUNT(*) FROM products p WHERE {where}", params
        ).fetchone()[0]
        return rows, total

    @staticmethod
    def search(query, sort='latest', page=1, per_page=20, region_filter=''):
        offset = (page - 1) * per_page
        order = _sort_clause(sort)
        like = f'%{query}%'
        params: list = [like, like, like]
        where = "p.status='active' AND (p.title LIKE ? OR p.description LIKE ? OR p.keywords LIKE ?)"
        if region_filter:
            where += " AND p.region LIKE ?"
            params.append(f'%{region_filter}%')
        rows = _db().execute(
            f"SELECT p.*, u.nickname as seller_name FROM products p JOIN users u ON p.seller_id=u.id "
            f"WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
            params + [per_page, offset]
        ).fetchall()
        cnt_params: list = [like, like, like]
        cnt_where = "status='active' AND (title LIKE ? OR description LIKE ? OR keywords LIKE ?)"
        if region_filter:
            cnt_where += " AND region LIKE ?"
            cnt_params.append(f'%{region_filter}%')
        total = _db().execute(
            f"SELECT COUNT(*) FROM products WHERE {cnt_where}", cnt_params
        ).fetchone()[0]
        return rows, total

    @staticmethod
    def hot_products(days=7, limit=5):
        return _db().execute(
            "SELECT p.*, u.nickname as seller_name FROM products p JOIN users u ON p.seller_id=u.id "
            "WHERE p.status='active' AND p.created_at >= datetime('now', ?) "
            "ORDER BY p.views DESC LIMIT ?",
            (f'-{days} days', limit)
        ).fetchall()

    @staticmethod
    def by_seller(seller_id, include_pending=False):
        statuses = "('active','pending','sold')" if include_pending else "('active','sold')"
        return _db().execute(
            f"SELECT * FROM products WHERE seller_id=? AND status IN {statuses} ORDER BY created_at DESC",
            (seller_id,)
        ).fetchall()

    @staticmethod
    def pending_products():
        return _db().execute(
            "SELECT p.*, u.nickname as seller_name FROM products p JOIN users u ON p.seller_id=u.id "
            "WHERE p.status='pending' ORDER BY p.created_at DESC"
        ).fetchall()

    @staticmethod
    def all_for_admin(page=1, per_page=30):
        offset = (page - 1) * per_page
        rows = _db().execute(
            "SELECT p.*, u.nickname as seller_name FROM products p JOIN users u ON p.seller_id=u.id "
            "WHERE p.status != 'deleted' ORDER BY p.created_at DESC LIMIT ? OFFSET ?",
            (per_page, offset)
        ).fetchall()
        total = _db().execute("SELECT COUNT(*) FROM products WHERE status != 'deleted'").fetchone()[0]
        return rows, total


def _sort_clause(sort: str) -> str:
    return {
        'latest': 'p.created_at DESC',
        'price_asc': 'p.price ASC',
        'price_desc': 'p.price DESC',
        'views': 'p.views DESC',
    }.get(sort, 'p.created_at DESC')
