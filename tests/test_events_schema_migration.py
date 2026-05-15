import sqlite3

from app.database.connection import init_db
from app.config.settings import settings


def test_existing_events_table_is_migrated_without_losing_rows(monkeypatch, tmp_path):
    db_path = tmp_path / "legacy-events.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE events (
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
        """
    )
    conn.execute(
        """
        INSERT INTO events (title, location_name, latitude, longitude, start_date)
        VALUES ('기존 집회', '광화문광장', 37.572, 126.9769, '2026-05-15 10:00:00')
        """
    )
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT)")
    conn.execute("CREATE TABLE alarm_tasks (task_id TEXT PRIMARY KEY, alarm_type TEXT)")
    conn.commit()
    conn.close()

    monkeypatch.setattr(settings, "DATABASE_PATH", str(db_path))
    init_db()

    migrated = sqlite3.connect(db_path)
    migrated.row_factory = sqlite3.Row
    try:
        row = migrated.execute("SELECT title, attendees, source FROM events").fetchone()
        assert row["title"] == "기존 집회"
        assert row["attendees"] == "미상"
        assert row["source"] == "SMPA"
        indexes = migrated.execute("PRAGMA index_list(events)").fetchall()
        assert any(index["name"] == "idx_events_source_record_hash" for index in indexes)
    finally:
        migrated.close()
