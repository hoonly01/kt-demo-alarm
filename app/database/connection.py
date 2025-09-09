"""데이터베이스 연결 관리"""
import sqlite3
from contextlib import contextmanager
from app.config.settings import settings
from app.database.models import USERS_TABLE_SCHEMA, EVENTS_TABLE_SCHEMA


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
    """데이터베이스 초기화 - 중앙집중식 스키마 사용"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    cursor = conn.cursor()
    
    # Users 테이블 생성 (통합 스키마 사용)
    cursor.execute(USERS_TABLE_SCHEMA)
    
    # Events 테이블 생성 (통합 스키마 사용)
    cursor.execute(EVENTS_TABLE_SCHEMA)
    
    conn.commit()
    conn.close()
    print("✅ 데이터베이스 초기화 완료")