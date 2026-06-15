"""DB bootstrap source-of-truth 회귀 테스트."""

import sqlite3

from app.database.bootstrap import _add_column_with_duplicate_tolerance
from app.database.connection import init_db


def _column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def _index_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA index_list({table_name})").fetchall()
    return {row["name"] for row in rows}


def test_init_db_uses_central_bootstrap_contract_for_fresh_db(
    tmp_path,
    settings_overrides,
):
    db_path = tmp_path / "bootstrap-contract.db"
    settings_overrides(DATABASE_PATH=str(db_path))

    init_db()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        assert "image_path" in _column_names(conn, "events")
        assert {
            "open_id",
            "plusfriend_user_key",
            "is_alarm_on",
            "favorite_zone",
        }.issubset(_column_names(conn, "users"))
        assert {
            "idx_users_open_id",
            "idx_users_plusfriend_key",
        }.issubset(_index_names(conn, "users"))
        assert "idx_events_source_record_hash" in _index_names(conn, "events")
    finally:
        conn.close()


def test_init_db_applies_central_user_migration_columns_to_legacy_db(
    tmp_path,
    settings_overrides,
):
    db_path = tmp_path / "legacy-users.db"
    legacy = sqlite3.connect(db_path)
    legacy.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_user_key TEXT UNIQUE NOT NULL,
            active BOOLEAN DEFAULT TRUE
        )
        """
    )
    legacy.execute(
        """
        CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            location_name TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            start_date DATETIME NOT NULL
        )
        """
    )
    legacy.execute(
        """
        CREATE TABLE alarm_tasks (
            task_id TEXT PRIMARY KEY,
            alarm_type TEXT NOT NULL
        )
        """
    )
    legacy.execute(
        """
        INSERT INTO users (bot_user_key, active)
        VALUES ('legacy-user', 1)
        """
    )
    legacy.commit()
    legacy.close()

    settings_overrides(DATABASE_PATH=str(db_path))
    init_db()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT bot_user_key, open_id, plusfriend_user_key, is_alarm_on, favorite_zone
            FROM users
            WHERE bot_user_key = 'legacy-user'
            """
        ).fetchone()
        assert row["bot_user_key"] == "legacy-user"
        assert row["open_id"] is None
        assert row["plusfriend_user_key"] is None
        assert row["is_alarm_on"] == 1
        assert row["favorite_zone"] is None
        assert "image_path" in _column_names(conn, "events")
    finally:
        conn.close()


def test_add_column_with_duplicate_tolerance_absorbs_duplicate_column_error(tmp_path):
    db_path = tmp_path / "duplicate-column.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_user_key TEXT UNIQUE NOT NULL,
                active BOOLEAN DEFAULT TRUE
            )
            """
        )
        cursor = conn.cursor()
        _add_column_with_duplicate_tolerance(cursor, "users", "open_id", "TEXT")
        _add_column_with_duplicate_tolerance(cursor, "users", "open_id", "TEXT")
        conn.commit()

        conn.row_factory = sqlite3.Row
        assert "open_id" in _column_names(conn, "users")
    finally:
        conn.close()
