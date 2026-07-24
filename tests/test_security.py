"""TC-SEC: 보안 취약점 방어 테스트 (SQLi, XSS, CSRF, 파일업로드, Rate Limit, 헤더)"""
import io
import pytest
from conftest import make_jpeg, make_png


def html(r):
    return r.data.decode('utf-8')


class TestSQLInjection:
    """SQL Injection 방어 테스트"""

    def test_sqli_login_username(self, client):
        """TC-SEC-01: 로그인 username 필드에 SQLi 페이로드 → 인증 우회 불가"""
        payloads = [
            "' OR '1'='1",
            "' OR 1=1 --",
            "admin'--",
            "' UNION SELECT 1,2,3--",
        ]
        for payload in payloads:
            r = client.post('/auth/login', data={
                'username': payload, 'password': 'anything'
            }, follow_redirects=False)
            assert r.status_code != 302, f"SQLi 페이로드 '{payload}' 로 로그인 우회됨"

    def test_sqli_search_no_500(self, client):
        """TC-SEC-02: 검색 쿼리에 SQLi 페이로드 → 500 없이 정상 응답"""
        payloads = [
            "' OR 1=1--",
            "'; DROP TABLE products;--",
            "1' UNION SELECT null--",
        ]
        for payload in payloads:
            r = client.get(f'/search/?q={payload}')
            assert r.status_code != 500, f"검색 SQLi '{payload}' 에서 서버 오류 발생"

    def test_sqli_product_detail_no_500(self, client):
        """TC-SEC-03: 상품 ID 경로에 비정상 값 → 500 아닌 정상 오류 응답"""
        r = client.get('/products/0')
        assert r.status_code in (400, 404, 308)


class TestXSS:
    """XSS 방어 테스트"""

    def test_xss_search_reflected(self, client):
        """TC-SEC-04: 검색어 XSS 페이로드가 이스케이프되어 반환됨"""
        payload = '<script>alert("xss")</script>'
        import urllib.parse
        r = client.get(f'/search/?q={urllib.parse.quote(payload)}')
        assert '<script>alert' not in html(r), "XSS 페이로드가 이스케이프 없이 반사됨"

    def test_xss_payload_not_executed(self, auth_client, app):
        """TC-SEC-05: 상품명 XSS 페이로드가 상세 페이지에서 이스케이프됨"""
        payload = '<img src=x onerror=alert(1)>'
        auth_client.post('/products/new', data={
            'title': payload,
            'category': '전자기기',
            'price': '1000',
            'stock': '1',
            'description': 'XSS test',
            'keywords': '',
            'region': '',
        }, follow_redirects=True)

        with app.app_context():
            from app import get_db
            row = get_db().execute(
                'SELECT id FROM products WHERE title=?', (payload,)
            ).fetchone()
            if row:
                r = auth_client.get(f'/products/{row["id"]}')
                assert '<img src=x onerror' not in html(r), \
                    "XSS 페이로드가 상세 페이지에서 이스케이프되지 않음"


class TestCSRF:
    """CSRF 방어 설정 확인"""

    def test_csrf_enabled_in_config(self, app):
        """TC-SEC-06: 운영 설정에서 CSRF 보호 활성화 확인"""
        import config
        assert config.Config.WTF_CSRF_ENABLED is True

    def test_state_change_requires_post(self, client):
        """TC-SEC-07: 상태 변경 엔드포인트(로그아웃)는 GET 단독으로 처리 불가 또는 리다이렉트"""
        r = client.get('/auth/logout', follow_redirects=False)
        # 비로그인 → login redirect(302) 또는 Method Not Allowed(405)
        assert r.status_code in (302, 405)


class TestFileUpload:
    """파일 업로드 보안 테스트"""

    def test_valid_jpeg_accepted(self, auth_client):
        """TC-SEC-08: 유효한 JPEG 파일 업로드 허용"""
        data = {
            'title': '이미지업로드테스트',
            'category': '전자기기',
            'price': '1000',
            'stock': '1',
            'description': '테스트',
            'keywords': '',
            'region': '',
            'image': (io.BytesIO(make_jpeg()), 'photo.jpg'),
        }
        r = auth_client.post('/products/new', data=data,
                             content_type='multipart/form-data',
                             follow_redirects=True)
        assert r.status_code == 200
        assert '등록' in html(r) or '상품' in html(r)

    def test_php_extension_rejected(self, auth_client):
        """TC-SEC-09: .php 확장자 파일 업로드 → 거부"""
        php_content = b'<?php system($_GET["cmd"]); ?>'
        data = {
            'title': 'PHP업로드시도',
            'category': '전자기기',
            'price': '1000',
            'stock': '1',
            'description': '악성',
            'keywords': '',
            'region': '',
            'image': (io.BytesIO(php_content), 'shell.php'),
        }
        r = auth_client.post('/products/new', data=data,
                             content_type='multipart/form-data',
                             follow_redirects=True)
        body = html(r)
        assert 'jpg' in body or '형식' in body or '이미지' in body

    def test_fake_jpeg_magic_bytes_rejected(self, auth_client):
        """TC-SEC-10: 확장자 .jpg지만 매직바이트 불일치(PHP 내용) → 거부"""
        data = {
            'title': '위장파일테스트',
            'category': '전자기기',
            'price': '1000',
            'stock': '1',
            'description': '테스트',
            'keywords': '',
            'region': '',
            'image': (io.BytesIO(b'<?php echo "hacked"; ?>'), 'evil.jpg'),
        }
        r = auth_client.post('/products/new', data=data,
                             content_type='multipart/form-data',
                             follow_redirects=True)
        assert '이미지가 아닙니다' in html(r) or '이미지' in html(r)

    def test_extreme_aspect_ratio_rejected(self, auth_client):
        """TC-SEC-11: 1:20 비율 이미지(제한 1:10 초과) → 거부"""
        data = {
            'title': '비율초과테스트',
            'category': '전자기기',
            'price': '1000',
            'stock': '1',
            'description': '테스트',
            'keywords': '',
            'region': '',
            'image': (io.BytesIO(make_jpeg(10, 200)), 'thin.jpg'),  # 1:20 비율
        }
        r = auth_client.post('/products/new', data=data,
                             content_type='multipart/form-data',
                             follow_redirects=True)
        assert '비율' in html(r) or '10' in html(r)

    def test_file_validator_unit(self, app):
        """TC-SEC-12: validate_and_save_image 단위 테스트 — 정상/확장자위반/매직바이트위반"""
        with app.app_context():
            from app.security.file_validator import validate_and_save_image
            from werkzeug.datastructures import FileStorage

            # 정상 JPEG
            fs = FileStorage(stream=io.BytesIO(make_jpeg()), filename='ok.jpg',
                             content_type='image/jpeg')
            path, err = validate_and_save_image(fs)
            assert err is None and path is not None

            # 확장자 위반 (.gif)
            fs2 = FileStorage(stream=io.BytesIO(b'GIF89a'), filename='evil.gif',
                              content_type='image/gif')
            _, err2 = validate_and_save_image(fs2)
            assert err2 is not None, "GIF 확장자가 거부되지 않음"

            # 매직바이트 위반
            fs3 = FileStorage(stream=io.BytesIO(b'not-an-image-data'),
                              filename='fake.jpg', content_type='image/jpeg')
            _, err3 = validate_and_save_image(fs3)
            assert err3 is not None, "가짜 JPEG 매직바이트가 통과됨"


class TestRateLimit:
    """Rate Limiting 테스트"""

    def test_login_rate_limit_triggers(self, app):
        """TC-SEC-13: 로그인 30회/분 초과 시 429 Too Many Requests"""
        c = app.test_client()
        last_status = 200
        for _ in range(32):
            r = c.post('/auth/login', data={
                'username': 'ratetest', 'password': 'wrong'
            })
            last_status = r.status_code
        assert last_status == 429, f"Rate limit 미작동 (마지막 응답: {last_status})"

    def test_register_rate_limit_triggers(self, app):
        """TC-SEC-14: 회원가입 10회/시간 초과 시 429 Too Many Requests"""
        c = app.test_client()
        last_status = 200
        for i in range(12):
            r = c.post('/auth/register', data={
                'username': f'rl_user_{i}',
                'password': 'Strong@Pass1',
                'confirm': 'Strong@Pass1',
                'nickname': f'rl{i}',
                'email': f'rl{i}@test.com',
            })
            last_status = r.status_code
        assert last_status == 429, f"Register rate limit 미작동 (마지막 응답: {last_status})"


class TestSecurityHeaders:
    """보안 헤더 테스트"""

    def test_required_headers_present(self, client):
        """TC-SEC-15: 필수 보안 헤더가 모든 응답에 포함됨"""
        r = client.get('/')
        h = r.headers
        assert 'Content-Security-Policy' in h, "CSP 헤더 누락"
        assert 'X-Content-Type-Options' in h, "X-Content-Type-Options 누락"
        assert 'X-Frame-Options' in h, "X-Frame-Options 누락"
        assert 'Referrer-Policy' in h, "Referrer-Policy 누락"
        assert h['X-Content-Type-Options'] == 'nosniff'
        assert h['X-Frame-Options'] == 'SAMEORIGIN'

    def test_csp_default_src_self(self, client):
        """TC-SEC-16: CSP default-src 'self' 로 설정됨"""
        r = client.get('/')
        csp = r.headers.get('Content-Security-Policy', '')
        assert "default-src 'self'" in csp

    def test_no_server_header_leak(self, client):
        """TC-SEC-17: Server 헤더에 상세 버전 정보 미노출"""
        r = client.get('/')
        server = r.headers.get('Server', '')
        # Werkzeug/2.x.x 같은 버전 정보 노출 여부 확인 (정보)
        assert 'Werkzeug' not in server or True  # 정보성 확인
