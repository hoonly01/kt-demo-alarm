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
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_connection():
    """컨텍스트 매니저를 사용한 DB 연결 (일반 함수용)"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
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

    # 컬럼 추가 로직 (이미 있으면 Exception 발생하므로 try-except로 무시)
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN open_id TEXT")
        cursor.execute("ALTER TABLE users ADD COLUMN plusfriend_user_key TEXT")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_open_id ON users(open_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_plusfriend_key ON users(plusfriend_user_key)")
        logger.info("✅ open_id, plusfriend_user_key 컬럼 추가 완료")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            logger.warning(f"컬럼 갱신 실패 (무시됨): {str(e)}")

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN is_alarm_on BOOLEAN DEFAULT TRUE")
        logger.info("✅ is_alarm_on 컬럼 추가 완료")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            logger.warning(f"is_alarm_on 컬럼 갱신 실패 (무시됨): {str(e)}")

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN favorite_zone INTEGER")
        logger.info("✅ favorite_zone 컬럼 추가 완료")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            logger.warning(f"favorite_zone 컬럼 갱신 실패 (무시됨): {str(e)}")

    # bot_user_key NOT NULL 제약 제거 (채널 웹훅 신규 사용자는 open_id만 있음)
    try:
        cursor.execute("PRAGMA table_info(users)")
        columns = cursor.fetchall()
        bot_col = next((c for c in columns if c[1] == 'bot_user_key'), None)
        if bot_col and bot_col[3] == 1:  # notnull=1 이면 마이그레이션 필요
            logger.info("🔄 bot_user_key NOT NULL 제약 제거 마이그레이션 시작")
            cursor.execute("PRAGMA foreign_keys=OFF")
            cursor.execute('''
                CREATE TABLE users_migration_tmp (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_user_key TEXT UNIQUE,
                    open_id TEXT,
                    plusfriend_user_key TEXT,
                    first_message_at DATETIME,
                    last_message_at DATETIME,
                    message_count INTEGER DEFAULT 1,
                    location TEXT,
                    active BOOLEAN DEFAULT TRUE,
                    is_alarm_on BOOLEAN DEFAULT TRUE,
                    departure_name TEXT,
                    departure_address TEXT,
                    departure_x REAL,
                    departure_y REAL,
                    arrival_name TEXT,
                    arrival_address TEXT,
                    arrival_x REAL,
                    arrival_y REAL,
                    route_updated_at DATETIME,
                    marked_bus TEXT,
                    language TEXT,
                    favorite_zone INTEGER
                )
            ''')
            cursor.execute("INSERT INTO users_migration_tmp SELECT * FROM users")
            cursor.execute("DROP TABLE users")
            cursor.execute("ALTER TABLE users_migration_tmp RENAME TO users")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_open_id ON users(open_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_plusfriend_key ON users(plusfriend_user_key)")
            cursor.execute("PRAGMA foreign_keys=ON")
            logger.info("✅ bot_user_key NOT NULL 제약 제거 완료")
    except Exception as e:
        logger.warning(f"bot_user_key 마이그레이션 실패: {str(e)}")

    conn.commit()
    conn.close()
    print("✅ 데이터베이스 초기화 완료")