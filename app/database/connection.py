"""데이터베이스 연결 관리"""
import sqlite3
from contextlib import contextmanager
from app.config.settings import settings


DATABASE_PATH = settings.DATABASE_PATH


def get_db():
    """데이터베이스 연결을 위한 의존성 주입 함수 (FastAPI 용)"""
    db = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_connection():
    """컨텍스트 매니저를 사용한 DB 연결 (일반 함수용)"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """데이터베이스 초기화"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    cursor = conn.cursor()
    
    # Users 테이블 생성
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_user_key TEXT UNIQUE NOT NULL,
            first_message_at DATETIME,
            last_message_at DATETIME,
            message_count INTEGER DEFAULT 1,
            location TEXT,
            active BOOLEAN DEFAULT TRUE
        )
    ''')

    # Phase 7: 동적으로 경로 정보 컬럼들 추가 (기존 테이블에 컬럼이 없는 경우만)
    route_columns = [
        ('departure_name', 'TEXT'),
        ('departure_address', 'TEXT'), 
        ('departure_x', 'REAL'),
        ('departure_y', 'REAL'),
        ('arrival_name', 'TEXT'),
        ('arrival_address', 'TEXT'),
        ('arrival_x', 'REAL'),
        ('arrival_y', 'REAL'),
        ('route_updated_at', 'DATETIME'),
        ('marked_bus', 'TEXT'),
        ('language', 'TEXT')
    ]

    for column_name, column_type in route_columns:
        try:
            cursor.execute(f'ALTER TABLE users ADD COLUMN {column_name} {column_type}')
            print(f"✅ Added column: {column_name}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                continue  # 이미 존재하는 컬럼이면 무시
            else:
                print(f"❌ Error adding column {column_name}: {e}")

    # Events 테이블 생성 (Phase 9)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            location_name TEXT NOT NULL,
            location_address TEXT,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            start_date DATETIME NOT NULL,
            end_date DATETIME,
            category TEXT,
            severity_level INTEGER DEFAULT 1,
            status TEXT DEFAULT 'active',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ 데이터베이스 초기화 완료")