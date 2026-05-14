"""관리자 대시보드 read-model 저장소 통합 테스트."""
import os
import sqlite3
import tempfile
from typing import Iterator

import pytest

from app.database.models import ALARM_TASKS_TABLE_SCHEMA, EVENTS_TABLE_SCHEMA, USERS_TABLE_SCHEMA
from app.repositories.admin_dashboard_read_repository import AdminDashboardReadRepository


@pytest.fixture
def admin_dashboard_db() -> Iterator[sqlite3.Connection]:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    conn.execute(USERS_TABLE_SCHEMA)
    conn.execute(EVENTS_TABLE_SCHEMA)
    conn.execute(ALARM_TASKS_TABLE_SCHEMA)
    conn.commit()

    try:
        yield conn
    finally:
        conn.close()
        try:
            os.remove(db_path)
        except FileNotFoundError:
            pass


def test_admin_dashboard_repository_lists_recent_events_and_alarms(admin_dashboard_db):
    admin_dashboard_db.execute(
        """
        INSERT INTO events (
            title, location_name, latitude, longitude,
            start_date, severity_level, status, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("집회 A", "광화문", 37.57, 126.98, "2026-05-12T09:00:00", 2, "active", "2026-05-12T08:00:00"),
    )
    admin_dashboard_db.execute(
        """
        INSERT INTO alarm_tasks (
            task_id, alarm_type, status, total_recipients,
            successful_sends, failed_sends, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("task-1", "bulk", "completed", 3, 2, 1, "2026-05-12T08:30:00"),
    )
    admin_dashboard_db.commit()

    events = AdminDashboardReadRepository.list_recent_events(admin_dashboard_db)
    alarms = AdminDashboardReadRepository.list_recent_alarms(admin_dashboard_db)

    assert events == [
        {
            "id": 1,
            "title": "집회 A",
            "location_name": "광화문",
            "severity_level": 2,
            "start_date": "2026-05-12T09:00:00",
            "created_at": "2026-05-12T08:00:00",
            "status": "active",
        }
    ]
    assert alarms == [
        {
            "task_id": "task-1",
            "alarm_type": "bulk",
            "status": "completed",
            "total_recipients": 3,
            "successful_sends": 2,
            "failed_sends": 1,
            "created_at": "2026-05-12T08:30:00",
        }
    ]


def test_admin_dashboard_repository_preserves_optional_user_columns(admin_dashboard_db):
    admin_dashboard_db.execute(
        """
        INSERT INTO users (
            bot_user_key, plusfriend_user_key, open_id,
            first_message_at, last_message_at, message_count,
            active, departure_name, arrival_name, marked_bus,
            is_alarm_on, favorite_zone
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "bot-modern",
            "pf-modern",
            "open-modern",
            "2026-05-12T08:00:00",
            "2026-05-12T09:00:00",
            5,
            1,
            "출발",
            "도착",
            "7016",
            0,
            None,
        ),
    )
    admin_dashboard_db.commit()

    assert AdminDashboardReadRepository.count_users(admin_dashboard_db) == 1

    users = AdminDashboardReadRepository.list_paginated_users(
        admin_dashboard_db,
        limit=10,
        offset=0,
    )

    assert users == [
        {
            "id": 1,
            "bot_user_key": "bot-modern",
            "active": 1,
            "departure_name": "출발",
            "arrival_name": "도착",
            "marked_bus": "7016",
            "created_at": "2026-05-12T08:00:00",
            "message_count": 5,
            "plusfriend_user_key": "pf-modern",
            "open_id": "open-modern",
            "is_alarm_on": 0,
            "favorite_zone": 0,
        }
    ]


def test_admin_dashboard_repository_supports_legacy_user_schema():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
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
        conn.execute(
            """
            INSERT INTO users (
                bot_user_key, first_message_at, last_message_at,
                message_count, active, departure_name, arrival_name, marked_bus
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-user",
                "2026-05-12T07:00:00",
                "2026-05-12T08:00:00",
                3,
                1,
                "영통역",
                "광화문역",
                "470",
            ),
        )
        conn.commit()

        users = AdminDashboardReadRepository.list_paginated_users(conn, limit=10, offset=0)

        assert users == [
            {
                "id": 1,
                "bot_user_key": "legacy-user",
                "active": 1,
                "departure_name": "영통역",
                "arrival_name": "광화문역",
                "marked_bus": "470",
                "created_at": "2026-05-12T07:00:00",
                "message_count": 3,
                "plusfriend_user_key": None,
                "open_id": None,
                "is_alarm_on": None,
                "favorite_zone": 0,
            }
        ]
    finally:
        conn.close()
        os.remove(db_path)


def test_admin_dashboard_repository_returns_empty_read_model_for_uninitialized_db():
    conn = sqlite3.connect(":memory:")

    try:
        assert AdminDashboardReadRepository.list_recent_events(conn) == []
        assert AdminDashboardReadRepository.list_recent_alarms(conn) == []
        assert AdminDashboardReadRepository.count_users(conn) == 0
        assert AdminDashboardReadRepository.list_paginated_users(conn, limit=10, offset=0) == []
    finally:
        conn.close()
