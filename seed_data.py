"""
샘플 데이터 삽입 스크립트
실행: python seed_data.py
주의: 기존 샘플 계정/상품이 있으면 일부 중복될 수 있습니다.
"""
import sqlite3
from werkzeug.security import generate_password_hash

DB_PATH = 'instance/market.db'

USERS = [
    ('user01', '판매왕김씨', 'user01@example.com', '37.5665', '126.9780'),
    ('user02', '거래달인이씨', 'user02@example.com', '37.4979', '127.0276'),
    ('user03', '중고마켓박씨', 'user03@example.com', '37.5172', '127.0473'),
    ('user04', '알뜰쇼핑최씨', 'user04@example.com', '37.5326', '126.9904'),
    ('user05', '하늘유저정씨', 'user05@example.com', '37.5519', '126.9918'),
]

# (title, description, price, category, region, lat, lon, stock, keywords)
PRODUCTS = [
    ('아이폰 15 프로 128GB', '사용감 거의 없는 아이폰 15 프로입니다. 케이스+보호필름 포함. 배터리 98%', 1100000, '전자기기', '서울 강남구', 37.5172, 127.0473, 1, '아이폰,iPhone,스마트폰'),
    ('맥북 프로 M3 14인치', '작년 구매 맥북 프로 M3 14인치. 스크래치 없음. 충전기 포함.', 2200000, '전자기기', '서울 서초구', 37.4979, 127.0276, 1, '맥북,MacBook,노트북,애플'),
    ('갤럭시 버즈2 프로', '개봉만 한 갤럭시 버즈2 프로 화이트. 풀박스.', 120000, '전자기기', '서울 마포구', 37.5519, 126.9918, 2, '갤럭시버즈,이어폰,삼성'),
    ('나이키 에어포스1 270mm', '3번 신은 나이키 에어포스1 흰색. 박스 없음.', 65000, '의류', '서울 홍대', 37.5563, 126.9236, 1, '나이키,스니커즈,운동화'),
    ('리바이스 청바지 32인치', '리바이스 511 슬림핏 청바지. 깨끗한 상태.', 35000, '의류', '서울 신촌', 37.5596, 126.9426, 1, '리바이스,청바지,데님'),
    ('파이썬 완전정복 (책)', '파이썬 프로그래밍 입문서. 밑줄 없음. 최신판.', 12000, '도서', '서울 관악구', 37.4784, 126.9516, 3, '파이썬,프로그래밍,코딩,IT'),
    ('클린코드 (책)', 'Clean Code 한국어판. 깨끗한 상태.', 18000, '도서', '서울 동작구', 37.5124, 126.9393, 2, '클린코드,개발,소프트웨어'),
    ('IKEA 책상 (화이트, 120cm)', 'IKEA 린몬 책상 화이트. 조립되어 있음. 직거래만.', 45000, '가구', '서울 은평구', 37.6176, 126.9270, 1, 'IKEA,책상,이케아,가구'),
    ('요가매트 6mm TPE', '사용 2회. 미끄럼방지 TPE 요가매트 퍼플. 가방 포함.', 18000, '스포츠', '서울 노원구', 37.6619, 127.0674, 1, '요가매트,운동,피트니스'),
    ('덤벨 세트 5~20kg', '가정용 가변 덤벨 세트. 5·10·15·20kg. 거의 안 씀.', 85000, '스포츠', '서울 성동구', 37.5633, 127.0370, 1, '덤벨,헬스,운동기구'),
    ('에어팟 프로 2세대', '에어팟 프로 2세대. 케이스 포함. ANC 정상 작동.', 220000, '전자기기', '서울 강서구', 37.5509, 126.8495, 1, '에어팟,AirPods,이어폰,애플'),
    ('캐논 EOS M50 카메라', '유튜브·브이로그용 미러리스. 렌즈 15-45mm 포함. 박스 없음.', 380000, '전자기기', '서울 중구', 37.5638, 126.9973, 1, '카메라,캐논,미러리스,사진'),
    ('닌텐도 스위치 OLED', '닌텐도 스위치 OLED 화이트. 게임 3개 포함.', 310000, '전자기기', '서울 송파구', 37.5145, 127.1059, 1, '닌텐도,스위치,게임기'),
    ('아디다스 트레이닝복 세트 M', '아디다스 트레이닝복 상하의 세트. 사이즈 M. 거의 안 입음.', 42000, '의류', '서울 강동구', 37.5301, 127.1239, 1, '아디다스,트레이닝복,운동복'),
    ('무인양품 원목 선반', 'MUJI 원목 3단 선반. 조립 가능. 직거래.', 55000, '가구', '서울 용산구', 37.5326, 126.9904, 1, '무인양품,MUJI,선반,수납'),
    ('프로틴 파우더 1kg (사용 절반)', '헬스보충제 WPI 프로틴 초코맛. 절반 사용. 유통기한 내년 3월.', 22000, '식품', '서울 광진구', 37.5384, 127.0822, 2, '프로틴,헬스,보충제'),
    ('립스틱 세트 (미사용)', '백화점 선물세트 미개봉 립스틱 4종. 시즌오프 처분.', 28000, '뷰티', '서울 강남구', 37.5172, 127.0473, 3, '립스틱,화장품,뷰티'),
    ('커피메이커 드롱기', '드롱기 스틸레토 에스프레소 머신. 2년 사용. 청결 유지.', 95000, '기타', '서울 종로구', 37.5735, 126.9790, 1, '커피,에스프레소,드롱기'),
    ('레고 테크닉 42141', '레고 테크닉 맥라렌 포뮬러1 미조립. 설명서 완비.', 130000, '기타', '서울 마포구', 37.5519, 126.9918, 1, '레고,LEGO,테크닉'),
    ('텐트 4인용 (캠핑)', '코베아 4인용 돔텐트. 2회 사용. 팩·폴대 풀세트.', 78000, '스포츠', '서울 도봉구', 37.6688, 127.0471, 1, '텐트,캠핑,아웃도어'),
]

COMMENTS = [
    (1, 1, '상태가 좋아 보이네요! 직거래 가능한가요?'),
    (1, 2, '배터리 교체 이력 있나요?'),
    (2, 3, '맥북 스펙이 어떻게 되나요?'),
    (3, 4, '버즈2 프로 새거랑 소리 차이 있나요?'),
    (5, 1, '사이즈가 정확한지 궁금합니다.'),
    (6, 2, '직거래 가능 지역이 어디인가요?'),
    (13, 3, '게임 어떤 타이틀인지 알 수 있을까요?'),
    (20, 4, '텐트 방수 기능은 어떤가요?'),
]


def seed():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    pw_hash = generate_password_hash('Test1234!')

    user_ids = []
    for username, nickname, email, lat, lon in USERS:
        try:
            cur = conn.execute(
                'INSERT INTO users (username, password_hash, nickname, email, balance) VALUES (?,?,?,?,?)',
                (username, pw_hash, nickname, email, 300000)
            )
            user_ids.append(cur.lastrowid)
        except Exception:
            row = conn.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
            if row:
                user_ids.append(row['id'])

    conn.commit()

    if not user_ids:
        print('사용자 생성 실패')
        conn.close()
        return

    product_ids = []
    for i, (title, desc, price, cat, region, lat, lon, stock, kw) in enumerate(PRODUCTS):
        seller_id = user_ids[i % len(user_ids)]
        try:
            cur = conn.execute(
                'INSERT INTO products (seller_id, title, description, price, category, region, '
                'latitude, longitude, stock, status, keywords) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (seller_id, title, desc, price, cat, region, lat, lon, stock, 'active', kw)
            )
            product_ids.append(cur.lastrowid)
        except Exception as e:
            print(f'상품 오류: {e}')
            product_ids.append(None)

    conn.commit()

    # Add sample comments
    for prod_idx, user_idx, content in COMMENTS:
        prod_id = product_ids[prod_idx - 1] if prod_idx - 1 < len(product_ids) else None
        user_id = user_ids[user_idx - 1] if user_idx - 1 < len(user_ids) else None
        if prod_id and user_id:
            try:
                conn.execute(
                    'INSERT INTO comments (product_id, user_id, content) VALUES (?,?,?)',
                    (prod_id, user_id, content)
                )
            except Exception:
                pass

    conn.commit()
    conn.close()

    print(f'✅ 샘플 사용자 {len(user_ids)}명 생성/확인')
    print(f'✅ 샘플 상품 {len([p for p in product_ids if p])}개 등록')
    print()
    print('테스트 계정 (공통 비밀번호: Test1234!):')
    for u, n, e, *_ in USERS:
        print(f'  아이디: {u}  닉네임: {n}')


if __name__ == '__main__':
    seed()
