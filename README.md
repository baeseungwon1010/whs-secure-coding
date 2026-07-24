# 하늘마켓 — Tiny Second-hand Shopping Platform

WHS 시큐어코딩 과제 — Flask 기반 중고거래 플랫폼

## 기술 스택

| 구분 | 기술 |
|------|------|
| 백엔드 | Python 3.10+ / Flask 3 |
| 실시간 채팅 | Flask-SocketIO (threading mode) |
| DB | SQLite (WAL mode, foreign keys ON) |
| 인증 | Flask-Login + werkzeug password hashing |
| CSRF | Flask-WTF |
| 이미지 검증 | Pillow + magic bytes 검사 |
| 이메일 | smtplib SMTP (Gmail App Password) |

## 환경 설정

```bash
# 1. 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 2. 의존성 설치
pip install -r requirements.txt

# 3. 환경 변수 설정
cp .env.example .env
# .env 파일에서 아래 항목 입력:
#   SECRET_KEY      — 긴 무작위 문자열
#   SMTP_USER       — Gmail 주소
#   SMTP_PASSWORD   — Gmail 앱 비밀번호
#   ADMIN_PASSWORD  — 최초 관리자 비밀번호
```

## 실행

```bash
python app.py
# → http://localhost:5000
```

## 주요 기능

- **회원**: 회원가입/로그인/아이디·비번 찾기(이메일)/프로필/비번 변경
- **상품**: 등록/수정/삭제(3초 지연 확인)/카테고리/이미지 업로드
- **검색**: 최신·가격·조회수 정렬 / 핫게시물 / 최근 본 상품·검색어(5개)
- **채팅**: 1:1 실시간 채팅 / 비속어 필터 / 차단·신고
- **송금**: 가상 잔액 충전 및 구매 이체
- **알림**: 채팅·판매·찜 알림 / 수신 설정
- **신고**: 상품·사용자·채팅 신고 / 자동 누적 감지
- **관리자**: 대시보드·상품관리·회원관리·신고처리·공지사항·로그

## 보안 적용 사항

| 항목 | 구현 |
|------|------|
| 비밀번호 | `werkzeug.security` 해시 저장, 평문 금지 |
| SQL Injection | 파라미터 바인딩(`?`) 전면 적용, 문자열 포맷 쿼리 없음 |
| XSS | Jinja2 자동 이스케이프 (`|e` 필터 사용), `|safe` 사용 없음 |
| CSRF | Flask-WTF CSRF 토큰 모든 상태변경 폼 적용 |
| 파일 업로드 | magic bytes 검사 + 확장자 화이트리스트(jpg/jpeg/png) + 용량 제한 + `secure_filename` + path traversal 방지 |
| 인증/세션 | Flask-Login, `@login_required`, HttpOnly·SameSite 쿠키 |
| 접근 제어 | 본인/관리자 권한 검사(IDOR 방지), `@admin_required` 데코레이터 |
| 비속어 | 채팅·상품 등록 시 필터링 및 금지 키워드 → 관리자 검토 |
| 서버 검증 | 모든 폼 서버 측 입력 검증(클라이언트 검증 신뢰 않음) |
| 로그 | 인증·상품 주요 이벤트 DB 기록, 민감정보 마스킹 |
| 비밀정보 | `.env` 분리, `.gitignore`로 커밋 방지 |

## 디렉터리 구조

```
secure-coding/
├─ app.py               # 엔트리포인트
├─ config.py            # 설정 (.env 로드)
├─ requirements.txt
├─ schema.sql           # SQLite 스키마
├─ .env.example
├─ app/
│  ├─ __init__.py       # create_app, extensions
│  ├─ blueprints/       # auth, products, search, chat, payment,
│  │                    # notifications, reports, admin, mypage, main
│  ├─ models/           # user, product, notification, report
│  ├─ security/         # decorators, file_validator, profanity
│  ├─ utils/            # email (SMTP), helpers
│  ├─ static/css/       # main.css (하늘색·둥글둥글)
│  ├─ static/uploads/   # 업로드 이미지 (gitignore)
│  └─ templates/        # Jinja2 템플릿
├─ instance/            # SQLite DB (gitignore)
└─ tests/               # 보안·기능 테스트
```
