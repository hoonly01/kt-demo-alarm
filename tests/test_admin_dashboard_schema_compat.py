import os
import sqlite3
import tempfile
from contextlib import contextmanager

from app.config.settings import settings
from app.database.connection import init_db


def test_admin_dashboard_works_with_legacy_user_schema(test_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASS", "secret123")

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        legacy_conn = sqlite3.connect(db_path)
        cursor = legacy_conn.cursor()
        cursor.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_user_key TEXT UNIQUE NOT NULL,
                first_message_at DATETIME,
                last_message_at DATETIME,
                message_count INTEGER DEFAULT 1,
                location TEXT,
                active BOOLEAN DEFAULT TRUE,
                departure_name TEXT,
                arrival_name TEXT,
                marked_bus TEXT
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO users (
                bot_user_key, first_message_at, last_message_at, message_count, active, departure_name, arrival_name, marked_bus
            ) VALUES (
                'legacy-user', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 3, 1, '영통역', '광화문역', '470'
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                location_name TEXT NOT NULL,
                severity_level INTEGER DEFAULT 1,
                start_date DATETIME,
                created_at DATETIME,
                status TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE alarm_tasks (
                task_id TEXT PRIMARY KEY,
                alarm_type TEXT,
                status TEXT,
                total_recipients INTEGER,
                successful_sends INTEGER,
                failed_sends INTEGER,
                created_at DATETIME
            )
            """
        )
        legacy_conn.commit()
        legacy_conn.close()

        @contextmanager
        def legacy_db_connection():
            conn = sqlite3.connect(db_path, check_same_thread=False)
            try:
                yield conn
            finally:
                conn.close()

        monkeypatch.setattr("app.routers.admin.get_db_connection", legacy_db_connection)

        response = test_client.get("/admin/dashboard", auth=("admin", "secret123"))

        assert response.status_code == 200
        assert "legacy-user" in response.text
    finally:
        os.unlink(db_path)


def test_init_db_preserves_user_column_mapping_during_not_null_migration(monkeypatch):
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_user_key TEXT UNIQUE NOT NULL,
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
                open_id TEXT,
                plusfriend_user_key TEXT,
                favorite_zone INTEGER
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO users (
                bot_user_key, first_message_at, last_message_at, message_count, location,
                active, is_alarm_on, departure_name, departure_address, departure_x,
                departure_y, arrival_name, arrival_address, arrival_x, arrival_y,
                route_updated_at, marked_bus, language, open_id, plusfriend_user_key, favorite_zone
            ) VALUES (
                'bot-user', '2026-04-16 10:00:00', '2026-04-16 11:00:00', 9, 'Seoul',
                1, 0, '광화문역', '서울 종로구', 126.9784,
                37.5716, '강남역', '서울 강남구', 127.0276, 37.4979,
                '2026-04-16 11:30:00', '470', 'ko', 'open-123', 'pf-123', 2
            )
            """
        )
        conn.commit()
        conn.close()

        monkeypatch.setattr("app.config.settings.settings.DATABASE_PATH", db_path)
        import app.database.connection as db_module
        original_db_path = db_module.DATABASE_PATH
        db_module.DATABASE_PATH = db_path
        try:
            init_db()
        finally:
            db_module.DATABASE_PATH = original_db_path

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT bot_user_key, open_id, plusfriend_user_key, first_message_at, last_message_at,
                   message_count, location, active, is_alarm_on, departure_name, departure_address,
                   departure_x, departure_y, arrival_name, arrival_address, arrival_x, arrival_y,
                   route_updated_at, marked_bus, language, favorite_zone
            FROM users
            WHERE bot_user_key = 'bot-user'
            """
        ).fetchone()
        conn.close()

        assert row["open_id"] == "open-123"
        assert row["plusfriend_user_key"] == "pf-123"
        assert row["first_message_at"] == "2026-04-16 10:00:00"
        assert row["last_message_at"] == "2026-04-16 11:00:00"
        assert row["message_count"] == 9
        assert row["location"] == "Seoul"
        assert row["active"] == 1
        assert row["is_alarm_on"] == 0
        assert row["departure_name"] == "광화문역"
        assert row["departure_address"] == "서울 종로구"
        assert row["departure_x"] == 126.9784
        assert row["departure_y"] == 37.5716
        assert row["arrival_name"] == "강남역"
        assert row["arrival_address"] == "서울 강남구"
        assert row["arrival_x"] == 127.0276
        assert row["arrival_y"] == 37.4979
        assert row["route_updated_at"] == "2026-04-16 11:30:00"
        assert row["marked_bus"] == "470"
        assert row["language"] == "ko"
        assert row["favorite_zone"] == 2
    finally:
        os.unlink(db_path)
