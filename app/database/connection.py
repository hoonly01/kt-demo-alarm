"""데이터베이스 연결 관리"""
import sqlite3
from contextlib import contextmanager

from app.config.settings import settings
from app.database.bootstrap import bootstrap_database, ensure_events_contract


def get_database_path() -> str:
    """현재 설정의 데이터베이스 경로를 반환한다."""
    return settings.DATABASE_PATH


def get_db():
    """데이터베이스 연결을 위한 의존성 주입 함수 (FastAPI 용)"""
    db = sqlite3.connect(get_database_path(), check_same_thread=False)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_connection():
    """컨텍스트 매니저를 사용한 DB 연결 (일반 함수용)"""
    conn = sqlite3.connect(get_database_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _ensure_events_contract(cursor: sqlite3.Cursor) -> None:
    """기존 events 테이블을 현재 SMPA 이벤트 계약으로 보강한다."""
    ensure_events_contract(cursor)


def init_db():
    """데이터베이스 초기화 - 중앙집중식 스키마 사용"""
    bootstrap_database(get_database_path(), path_source="settings")
    print("✅ 데이터베이스 초기화 완료")
