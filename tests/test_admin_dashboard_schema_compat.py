import sqlite3
import tempfile
from contextlib import contextmanager

from app.config.settings import settings


def test_admin_dashboard_works_with_legacy_user_schema(test_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASS", "secret123")

    fd, db_path = tempfile.mkstemp(suffix=".db")
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
