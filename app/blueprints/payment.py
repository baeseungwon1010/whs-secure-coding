import base64
import uuid

import requests as http_requests
from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, url_for)
from flask_login import current_user, login_required

from app.models.notification import Notification
from app.models.product import Product
from app.models.user import User
from app.security.decorators import not_banned
from app.utils.signed_id import sign_id, unsign_id

payment_bp = Blueprint('payment', __name__)

BANKS = [
    ('004', 'KB국민은행'),
    ('011', 'NH농협은행'),
    ('020', '우리은행'),
    ('088', '신한은행'),
    ('081', '하나은행'),
    ('090', '카카오뱅크'),
    ('089', '케이뱅크'),
    ('092', '토스뱅크'),
    ('003', 'IBK기업은행'),
    ('071', '우체국은행'),
    ('023', 'SC제일은행'),
    ('027', '씨티은행'),
    ('031', '대구은행'),
    ('032', '부산은행'),
    ('034', '광주은행'),
    ('039', '경남은행'),
    ('045', '새마을금고'),
    ('048', '신협'),
    ('007', '수협은행'),
]


def _db():
    from flask import g
    import sqlite3
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'],
                               detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db


def _toss_confirm_payment(payment_key: str, order_id: str, amount: int):
    """서버 측에서 Toss API로 결제 검증. (amount는 쿼리 파라미터 값, 응답의 totalAmount로 재확인)"""
    secret_key = current_app.config.get('TOSS_SECRET_KEY', '')
    if not secret_key:
        return False, {'message': 'TOSS_SECRET_KEY가 설정되지 않았습니다.'}
    auth = base64.b64encode(f'{secret_key}:'.encode()).decode()
    try:
        resp = http_requests.post(
            'https://api.tosspayments.com/v1/payments/confirm',
            headers={
                'Authorization': f'Basic {auth}',
                'Content-Type': 'application/json',
                'Idempotency-Key': order_id,
            },
            json={'paymentKey': payment_key, 'orderId': order_id, 'amount': amount},
            timeout=10,
        )
        return resp.status_code == 200, resp.json()
    except Exception as e:
        return False, {'message': str(e)}


def _toss_payout(amount: int, bank_code: str, account_number: str, holder_name: str):
    """Toss Payouts API로 계좌 송금 요청. 테스트 키면 즉시 완료 시뮬레이션."""
    secret_key = current_app.config.get('TOSS_SECRET_KEY', '')
    if not secret_key:
        return False, {'message': 'TOSS_SECRET_KEY가 설정되지 않았습니다.'}

    # 테스트 키(test_sk_)는 Payouts API 미지원 → 시뮬레이션으로 즉시 완료
    if secret_key.startswith('test_sk_') or secret_key.startswith('test_'):
        payout_key = f'test-payout-{uuid.uuid4().hex[:16]}'
        return True, {'payoutKey': payout_key, 'status': 'DONE'}

    auth = base64.b64encode(f'{secret_key}:'.encode()).decode()
    payout_key = str(uuid.uuid4()).replace('-', '')
    try:
        resp = http_requests.post(
            'https://api.tosspayments.com/v1/payouts',
            headers={
                'Authorization': f'Basic {auth}',
                'Content-Type': 'application/json',
            },
            json={
                'payoutKey': payout_key,
                'bankCode': bank_code,
                'accountNumber': account_number,
                'holderName': holder_name,
                'amount': amount,
                'type': 'NORMAL',
            },
            timeout=10,
        )
        return resp.status_code in (200, 201), resp.json()
    except Exception as e:
        return False, {'message': str(e)}


# ── 잔액 충전 메인 ──────────────────────────────────────────────────────────

@payment_bp.route('/charge')
@login_required
def charge():
    user = User.get_by_id(current_user.id)
    return render_template('payment/charge.html', user=user)


@payment_bp.route('/virtual-charge', methods=['POST'])
@login_required
@not_banned
def virtual_charge():
    """가상 잔액 충전 (시뮬레이션 — 외부 결제 API 없음)."""
    from app import limiter
    amount_str = request.form.get('amount', '').strip()
    try:
        amount = int(amount_str)
        if amount < 100 or amount > 5_000_000:
            raise ValueError
    except (ValueError, TypeError):
        flash('충전 금액은 100원 이상 500만원 이하여야 합니다.', 'danger')
        return redirect(url_for('payment.charge'))

    db = _db()
    db.execute('UPDATE users SET balance=balance+? WHERE id=?',
               (amount, current_user.id))
    db.execute(
        'INSERT INTO toss_payments (user_id, order_id, payment_key, amount, status) VALUES (?,?,?,?,?)',
        (current_user.id, f'virtual-{uuid.uuid4().hex[:20]}', 'virtual', amount, 'confirmed'),
    )
    db.commit()
    flash(f'{amount:,}원이 충전되었습니다.', 'success')
    return redirect(url_for('mypage.index'))


# ── 토스페이먼츠 충전 위젯 ──────────────────────────────────────────────────

@payment_bp.route('/toss/charge')
@login_required
def toss_charge():
    client_key = current_app.config.get('TOSS_CLIENT_KEY', '')
    if not client_key:
        flash('토스페이먼츠 클라이언트 키가 설정되지 않았습니다. .env에 TOSS_CLIENT_KEY를 추가하세요.', 'warning')
        return redirect(url_for('payment.charge'))
    order_id = f"haul-{current_user.id}-{uuid.uuid4().hex[:20]}"
    return render_template('payment/toss_charge.html',
                           client_key=client_key,
                           order_id=order_id)


@payment_bp.route('/toss/success')
@login_required
def toss_success():
    payment_key = request.args.get('paymentKey', '').strip()
    order_id = request.args.get('orderId', '').strip()
    amount_str = request.args.get('amount', '0').strip()

    if not payment_key or not order_id:
        flash('결제 정보가 올바르지 않습니다.', 'danger')
        return redirect(url_for('payment.charge'))
    try:
        amount = int(amount_str)
        if amount <= 0 or amount > 10_000_000:
            raise ValueError
    except ValueError:
        flash('결제 금액이 올바르지 않습니다.', 'danger')
        return redirect(url_for('payment.charge'))

    # 중복 처리 방지
    db = _db()
    if db.execute('SELECT id FROM toss_payments WHERE order_id=?', (order_id,)).fetchone():
        flash('이미 처리된 결제입니다.', 'warning')
        return redirect(url_for('mypage.index'))

    # Toss 서버에서 결제 검증
    ok, data = _toss_confirm_payment(payment_key, order_id, amount)

    if not ok:
        db.execute(
            'INSERT INTO toss_payments (user_id, order_id, payment_key, amount, status) VALUES (?,?,?,?,?)',
            (current_user.id, order_id, payment_key, amount, 'failed'),
        )
        db.commit()
        raw_msg = data.get('message', '결제 확인 실패')
        error_msg = str(raw_msg) if not isinstance(raw_msg, str) else raw_msg
        flash(f'결제 확인 실패: {error_msg}', 'danger')
        return redirect(url_for('payment.charge'))

    # Toss 응답의 totalAmount로 재확인 (클라이언트 파라미터 위변조 방지)
    confirmed_amount = data.get('totalAmount', amount)

    db.execute(
        'INSERT INTO toss_payments (user_id, order_id, payment_key, amount, status) VALUES (?,?,?,?,?)',
        (current_user.id, order_id, payment_key, confirmed_amount, 'confirmed'),
    )
    User.adjust_balance(current_user.id, confirmed_amount)
    db.commit()

    flash(f'{confirmed_amount:,}원이 충전되었습니다. 🎉', 'success')
    return redirect(url_for('mypage.index'))


@payment_bp.route('/toss/fail')
@login_required
def toss_fail():
    error_code = request.args.get('code', '')
    error_msg = request.args.get('message', '결제가 취소되었습니다.')
    if error_code == 'USER_CANCEL':
        flash('결제가 취소되었습니다.', 'info')
    else:
        flash(f'결제 실패: {error_msg}', 'danger')
    return redirect(url_for('payment.charge'))


# ── 출금 ───────────────────────────────────────────────────────────────────

@payment_bp.route('/withdraw', methods=['GET', 'POST'])
@login_required
@not_banned
def withdraw():
    user = User.get_by_id(current_user.id)

    if request.method == 'POST':
        amount_str = request.form.get('amount', '').strip()
        bank_code = request.form.get('bank_code', '').strip()
        account_number = request.form.get('account_number', '').strip()
        holder_name = request.form.get('holder_name', '').strip()

        errors = []
        amount = 0
        try:
            amount = int(amount_str)
            if amount < 1000:
                errors.append('최소 출금 금액은 1,000원입니다.')
            elif amount > user.balance:
                errors.append(f'잔액이 부족합니다. (현재 잔액: {user.balance:,}원)')
        except (ValueError, TypeError):
            errors.append('올바른 금액을 입력해 주세요.')

        valid_codes = {code for code, _ in BANKS}
        if bank_code not in valid_codes:
            errors.append('은행을 선택해 주세요.')
        if not account_number.isdigit() or not (10 <= len(account_number) <= 16):
            errors.append('올바른 계좌번호를 입력해 주세요. (숫자 10~16자리)')
        if not (2 <= len(holder_name) <= 20):
            errors.append('예금주명을 올바르게 입력해 주세요. (2~20자)')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('payment/withdraw.html', user=user, BANKS=BANKS)

        db = _db()
        # 원자적 잔액 차감 (잔액 부족 시 rowcount=0)
        result = db.execute(
            'UPDATE users SET balance=balance-? WHERE id=? AND balance>=?',
            (amount, current_user.id, amount),
        )
        if result.rowcount == 0:
            flash('잔액이 부족하거나 처리 중 오류가 발생했습니다.', 'danger')
            return render_template('payment/withdraw.html', user=user, BANKS=BANKS)

        cur = db.execute(
            'INSERT INTO withdrawal_requests (user_id, amount, bank_code, account_number, holder_name, status) '
            'VALUES (?,?,?,?,?,?)',
            (current_user.id, amount, bank_code, account_number, holder_name, 'processing'),
        )
        withdrawal_id = cur.lastrowid
        db.commit()

        # Toss Payouts API 호출
        ok, data = _toss_payout(amount, bank_code, account_number, holder_name)
        if ok:
            payout_key = data.get('payoutKey', '')
            db.execute(
                'UPDATE withdrawal_requests SET status=?, payout_key=? WHERE id=?',
                ('completed', payout_key, withdrawal_id),
            )
            db.commit()
            flash(f'{amount:,}원 출금이 완료되었습니다.', 'success')
        else:
            # 테스트 모드 또는 API 권한 없음 → 처리중 상태 유지
            raw = data.get('message', 'API 오류')
            fail_reason = str(raw) if not isinstance(raw, str) else raw
            db.execute(
                'UPDATE withdrawal_requests SET fail_reason=? WHERE id=?',
                (fail_reason, withdrawal_id),
            )
            db.commit()
            flash(f'{amount:,}원 출금 신청이 접수되었습니다. 처리까지 1~2일 소요될 수 있습니다.', 'info')

        return redirect(url_for('mypage.index'))

    return render_template('payment/withdraw.html', user=user, BANKS=BANKS)


# ── 구매 ───────────────────────────────────────────────────────────────────

@payment_bp.route('/buy/<token>', methods=['GET', 'POST'])
@login_required
@not_banned
def buy(token):
    product_id = unsign_id(token, salt='buy')
    if product_id is None:
        abort(400)
    product = Product.get_by_id(product_id)
    if not product or product['status'] != 'active':
        abort(404)
    if product['seller_id'] == current_user.id:
        flash('자신의 상품을 구매할 수 없습니다.', 'warning')
        return redirect(url_for('products.detail', product_id=product_id))

    buyer = User.get_by_id(current_user.id)
    stock = product['stock'] or 1

    if request.method == 'POST':
        try:
            qty = int(request.form.get('quantity', 1))
        except (ValueError, TypeError):
            qty = 1
        qty = max(1, min(qty, stock, 9999))

        total_price = product['price'] * qty

        if buyer.balance < total_price:
            shortage = total_price - buyer.balance
            flash(
                f'잔액이 {shortage:,}원 부족합니다. 충전 후 다시 시도해 주세요.',
                'danger',
            )
            return render_template('payment/buy.html', product=product,
                                   buyer=buyer, stock=stock, token=token)

        db = _db()
        db.execute(
            'UPDATE users SET balance=balance-? WHERE id=? AND balance>=?',
            (total_price, current_user.id, total_price),
        )
        db.execute('UPDATE users SET balance=balance+? WHERE id=?',
                   (total_price, product['seller_id']))
        db.execute(
            'INSERT INTO transactions (product_id, buyer_id, seller_id, amount, quantity, status) '
            'VALUES (?,?,?,?,?,?)',
            (product_id, current_user.id, product['seller_id'], total_price, qty, 'completed'),
        )
        Product.decrement_stock(product_id, qty)
        db.commit()

        Notification.create(
            product['seller_id'], 'sale',
            f'"{product["title"]}"이 {current_user.nickname}님에게 {qty}개 판매되었습니다.',
            url_for('products.detail', product_id=product_id),
        )
        flash(f'구매 완료! {qty}개 × {product["price"]:,}원 = {total_price:,}원', 'success')
        return redirect(url_for('mypage.purchase_history'))

    return render_template('payment/buy.html', product=product,
                           buyer=buyer, stock=stock, token=token)
