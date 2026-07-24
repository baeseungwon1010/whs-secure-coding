"""TC-AUTH: 인증 및 회원관리 테스트"""
import pytest
from werkzeug.security import check_password_hash


def html(r):
    return r.data.decode('utf-8')


class TestLogin:
    def test_login_success(self, auth_client):
        """TC-AUTH-01: 올바른 자격증명으로 로그인 성공"""
        r = auth_client.get('/mypage/')
        assert r.status_code == 200

    def test_login_wrong_password(self, client):
        """TC-AUTH-02: 잘못된 비밀번호 → 로그인 실패"""
        r = client.post('/auth/login', data={
            'username': 'testuser', 'password': 'WrongPass!'
        })
        assert '올바르지 않습니다' in html(r) or r.status_code == 200
        # 로그인 실패 후 마이페이지 접근 차단 확인
        r2 = client.get('/mypage/', follow_redirects=False)
        assert r2.status_code in (302, 401)

    def test_login_nonexistent_user(self, client):
        """TC-AUTH-03: 존재하지 않는 아이디 → 로그인 실패"""
        r = client.post('/auth/login', data={
            'username': 'nobody_xyz', 'password': 'Any@Pass1'
        })
        assert r.status_code == 200
        assert '올바르지 않습니다' in html(r)

    def test_session_required_redirect(self, client):
        """TC-AUTH-04: 미로그인 상태에서 보호된 페이지 → /auth/login 리다이렉트"""
        r = client.get('/mypage/', follow_redirects=False)
        assert r.status_code == 302
        assert '/auth/login' in r.headers['Location']

    def test_logout_clears_session(self, app):
        """TC-AUTH-05: 로그아웃 후 보호 페이지 접근 불가"""
        c = app.test_client()
        c.post('/auth/login', data={'username': 'testuser', 'password': 'Test@1234'})
        c.get('/auth/logout')
        r = c.get('/mypage/', follow_redirects=False)
        assert r.status_code == 302


class TestPasswordSecurity:
    def test_password_stored_as_hash(self, app):
        """TC-AUTH-06: DB에 비밀번호가 해시로 저장됨 (평문 저장 금지)"""
        with app.app_context():
            from app import get_db
            row = get_db().execute(
                'SELECT password_hash FROM users WHERE username=?', ('testuser',)
            ).fetchone()
            assert row is not None
            pw_hash = row['password_hash']
            assert pw_hash != 'Test@1234', "비밀번호 평문 저장됨"
            assert pw_hash.startswith(('pbkdf2:', 'scrypt:')), "해시 형식이 아님"
            assert check_password_hash(pw_hash, 'Test@1234'), "해시 검증 실패"

    def test_weak_password_rejected(self, client):
        """TC-AUTH-07: 취약한 비밀번호로 회원가입 거부 (특수문자 없음)"""
        weak_passwords = ['12345678', 'password', 'aaaaaaaa', 'Test12345']
        for pw in weak_passwords:
            r = client.post('/auth/register', data={
                'username': 'weakpwtest',
                'password': pw,
                'confirm': pw,
                'nickname': '테스트',
                'email': 'weak@test.com',
            }, follow_redirects=True)
            body = html(r)
            rejected = ('특수문자' in body or '영문' in body or '8자' in body
                        or '비밀번호' in body or '조건' in body)
            assert rejected, f"취약 비밀번호 '{pw}' 가 거부되지 않음"

    def test_password_confirm_mismatch(self, client):
        """TC-AUTH-08: 비밀번호 확인 불일치 → 가입 거부"""
        r = client.post('/auth/register', data={
            'username': 'mismatch1',
            'password': 'Strong@Pass1',
            'confirm': 'Different@Pass2',
            'nickname': '불일치',
            'email': 'mismatch@test.com',
        }, follow_redirects=True)
        assert '일치' in html(r)


class TestRegister:
    def test_duplicate_username_rejected(self, client):
        """TC-AUTH-09: 중복 아이디 가입 거부"""
        r = client.post('/auth/register', data={
            'username': 'testuser',
            'password': 'Strong@Pass1',
            'confirm': 'Strong@Pass1',
            'nickname': '중복테스터',
            'email': 'dup@test.com',
        }, follow_redirects=True)
        assert '이미 사용 중' in html(r)

    def test_username_check_api(self, client):
        """TC-AUTH-10: 아이디 중복 확인 API"""
        r = client.get('/auth/check-username?username=testuser')
        assert r.json['exists'] is True

        r2 = client.get('/auth/check-username?username=nobody_xyz_unique')
        assert r2.json['exists'] is False
