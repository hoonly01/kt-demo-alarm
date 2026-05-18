"""DB 연결 설정 경계 회귀 테스트"""
import sqlite3

from app.config.settings import settings
from app.database.connection import get_db, get_db_connection, init_db


def _table_names(db_path: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


def test_database_connections_use_current_settings_path_without_module_patch(
    monkeypatch,
    tmp_path,
):
    """settings 변경만으로 init/get_db/get_db_connection이 같은 임시 DB를 사용한다."""
    db_path = tmp_path / "runtime-settings.db"
    monkeypatch.setattr(settings, "DATABASE_PATH", str(db_path))

    init_db()

    assert {"users", "events", "alarm_tasks"}.issubset(_table_names(str(db_path)))

    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (bot_user_key, active)
            VALUES (?, ?)
            """,
            ("settings-user", True),
        )
        conn.commit()

    db_generator = get_db()
    db = next(db_generator)
    try:
        row = db.execute(
            "SELECT bot_user_key FROM users WHERE bot_user_key = ?",
            ("settings-user",),
        ).fetchone()
        assert row["bot_user_key"] == "settings-user"
    finally:
        db_generator.close()


def test_database_runtime_settings_path_is_current(monkeypatch, tmp_path):
    """DB 경로 해석은 중앙 settings 경계를 따른다."""
    relative_db_path = tmp_path / "relative-test.db"
    monkeypatch.setattr(settings, "DATABASE_PATH", str(relative_db_path))

    init_db()

    assert {"users", "events", "alarm_tasks"}.issubset(_table_names(str(relative_db_path)))
