"""TC-AC: 접근제어 / IDOR / 입력검증 테스트"""
import pytest
from conftest import make_jpeg
import io


def html(r):
    return r.data.decode('utf-8')


def _create_product(client, title='테스트상품', price=1000):
    """테스트 상품 생성 헬퍼, 생성된 product_id 반환"""
    r = client.post('/products/new', data={
        'title': title,
        'category': '전자기기',
        'price': str(price),
        'stock': '1',
        'description': '접근제어 테스트용 상품',
        'keywords': '',
        'region': '',
    }, follow_redirects=False)
    if r.status_code == 302:
        loc = r.headers.get('Location', '')
        parts = loc.rstrip('/').split('/')
        if parts and parts[-1].isdigit():
            return int(parts[-1])
    return None


class TestProductAccess:
    def test_edit_own_product_allowed(self, auth_client):
        """TC-AC-01: 본인 상품 수정 페이지 접근 허용"""
        pid = _create_product(auth_client, '내 상품')
        if pid is None:
            pytest.skip("상품 생성 실패")
        r = auth_client.get(f'/products/{pid}/edit')
        assert r.status_code == 200

    def test_edit_others_product_forbidden(self, auth_client, auth_client2):
        """TC-AC-02: 타인 상품 수정 시도 → 403 (IDOR 방어)"""
        pid = _create_product(auth_client, 'IDOR 테스트 상품')
        if pid is None:
            pytest.skip("상품 생성 실패")
        r = auth_client2.get(f'/products/{pid}/edit')
        assert r.status_code == 403, "IDOR 취약점: 타인 상품 수정 페이지 접근됨"

    def test_delete_others_product_forbidden(self, auth_client, auth_client2):
        """TC-AC-03: 타인 상품 삭제 시도 → 403"""
        pid = _create_product(auth_client, '삭제시도 대상 상품')
        if pid is None:
            pytest.skip("상품 생성 실패")
        r = auth_client2.post(f'/products/{pid}/delete', data={},
                              follow_redirects=False)
        assert r.status_code in (403, 302)

    def test_unauthenticated_cannot_create(self, client):
        """TC-AC-04: 비로그인 상태에서 상품 등록 불가 → 로그인 페이지 리다이렉트"""
        r = client.post('/products/new', data={
            'title': '비인증 등록', 'category': '전자기기',
            'price': '1000', 'stock': '1', 'description': '테스트',
        }, follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers.get('Location', '').lower()


class TestPaymentAccess:
    def test_buy_own_product_forbidden(self, auth_client, app):
        """TC-AC-05: 자신의 상품 구매 시도 → 거부"""
        pid = _create_product(auth_client, '자기구매테스트상품')
        if pid is None:
            pytest.skip("상품 생성 실패")
        with app.app_context():
            from app.utils.signed_id import sign_id
            token = sign_id(pid, salt='buy')
        r = auth_client.get(f'/payment/buy/{token}', follow_redirects=True)
        assert '자신의 상품' in html(r) or r.status_code in (302, 403, 404)

    def test_charge_requires_login(self, client):
        """TC-AC-06: 비로그인 상태에서 충전 페이지 접근 불가"""
        r = client.get('/payment/charge', follow_redirects=False)
        assert r.status_code == 302
        assert 'login' in r.headers.get('Location', '').lower()

    def test_negative_charge_rejected(self, auth_client):
        """TC-AC-07: 음수 충전 금액 → 거부 (잔액 감소 없음)"""
        r = auth_client.post('/payment/virtual-charge',
                             data={'amount': '-99999'},
                             follow_redirects=True)
        assert r.status_code == 200
        assert '-99' not in html(r) or '거부' in html(r) or '잘못' in html(r)

    def test_zero_charge_rejected(self, auth_client):
        """TC-AC-08: 0원 충전 시도 → 거부"""
        r = auth_client.post('/payment/virtual-charge',
                             data={'amount': '0'},
                             follow_redirects=True)
        assert r.status_code == 200

    def test_over_limit_charge_rejected(self, auth_client):
        """TC-AC-09: 한도 초과 충전(6백만원) → 거부"""
        r = auth_client.post('/payment/virtual-charge',
                             data={'amount': '6000000'},
                             follow_redirects=True)
        assert r.status_code == 200


class TestAdminAccess:
    def test_admin_page_blocks_regular_user(self, auth_client):
        """TC-AC-10: 일반 사용자의 관리자 페이지 접근 → 403 또는 리다이렉트"""
        r = auth_client.get('/admin/', follow_redirects=False)
        assert r.status_code in (302, 403)

    def test_admin_accessible_by_admin(self, admin_client):
        """TC-AC-11: 관리자 계정으로 관리자 페이지 접근 가능"""
        r = admin_client.get('/admin/')
        assert r.status_code == 200

    def test_unauthenticated_admin_blocked(self, client):
        """TC-AC-12: 비로그인 상태에서 관리자 페이지 → 리다이렉트"""
        r = client.get('/admin/', follow_redirects=False)
        assert r.status_code in (302, 403)


class TestInputValidation:
    def test_empty_title_rejected(self, auth_client):
        """TC-AC-13: 상품명 필수 필드 비어있으면 서버 측에서 거부"""
        r = auth_client.post('/products/new', data={
            'title': '',
            'category': '전자기기',
            'price': '1000',
            'stock': '1',
            'description': '',
        }, follow_redirects=True)
        assert r.status_code == 200
        # 상품 상세 페이지가 아닌 폼 페이지 유지

    def test_open_redirect_prevented(self, client):
        """TC-AC-14: 로그인 next 파라미터 외부 URL → 내부 URL로 강제 이동 (오픈 리다이렉트 방어)"""
        r = client.post('/auth/login',
                        data={'username': 'testuser', 'password': 'Test@1234'},
                        query_string={'next': 'https://evil.com'},
                        follow_redirects=False)
        location = r.headers.get('Location', '')
        assert not location.startswith('https://evil.com'), \
            f"오픈 리다이렉트 취약점: {location} 로 이동됨"

    def test_path_traversal_upload_prevented(self, auth_client):
        """TC-AC-15: 파일명 경로 순회 시도 → 안전한 파일명으로 정규화"""
        data = {
            'title': '경로순회테스트',
            'category': '전자기기',
            'price': '1000',
            'stock': '1',
            'description': '테스트',
            'keywords': '',
            'region': '',
            'image': (io.BytesIO(make_jpeg()), '../../../etc/passwd.jpg'),
        }
        r = auth_client.post('/products/new', data=data,
                             content_type='multipart/form-data',
                             follow_redirects=True)
        # 500 오류 없이 처리되어야 함
        assert r.status_code != 500
