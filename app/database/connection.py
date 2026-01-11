"""데이터베이스 연결 관리"""
import sqlite3
import logging
from contextlib import contextmanager
from app.config.settings import settings
from app.database.models import USERS_TABLE_SCHEMA, EVENTS_TABLE_SCHEMA, ALARM_TASKS_TABLE_SCHEMA

logger = logging.getLogger(__name__)
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

    # Alarm Tasks 테이블 생성 (알림 상태 추적용)
    cursor.execute(ALARM_TASKS_TABLE_SCHEMA)

    # 컬럼 2개 추가 (이미 있으면 무시) - Kakao ID 통합
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN open_id TEXT")
        cursor.execute("ALTER TABLE users ADD COLUMN plusfriend_user_key TEXT")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_open_id ON users(open_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_plusfriend_key ON users(plusfriend_user_key)")
        logger.info("✅ open_id, plusfriend_user_key 컬럼 추가 완료")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            logger.info("컬럼 이미 존재")
        else:
            raise

    conn.commit()
    conn.close()
    print("✅ 데이터베이스 초기화 완료")