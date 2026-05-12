"""Zone alarm read repository integration tests."""
import os
import sqlite3
import tempfile
from typing import Iterator

import pytest

from app.database.models import EVENTS_TABLE_SCHEMA, USERS_TABLE_SCHEMA
from app.repositories.zone_alarm_read_repository import ZoneAlarmReadRepository


@pytest.fixture
def zone_alarm_db() -> Iterator[sqlite3.Connection]:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(USERS_TABLE_SCHEMA)
    conn.execute(EVENTS_TABLE_SCHEMA)
    conn.commit()

    try:
        yield conn
    finally:
        conn.close()
        try:
            os.remove(db_path)
        except FileNotFoundError:
            pass


def test_list_zone_users_requires_active_alarm_on_favorite_zone_and_plusfriend(zone_alarm_db):
    rows = [
        ("pf-1", 1, 1, 1),
        ("pf-off", 1, 0, 1),
        ("pf-inactive", 0, 1, 1),
        ("pf-no-zone", 1, 1, None),
        (None, 1, 1, 1),
    ]
    for plusfriend_key, active, is_alarm_on, favorite_zone in rows:
        zone_alarm_db.execute(
            """
            INSERT INTO users (
                plusfriend_user_key, first_message_at, last_message_at,
                message_count, active, is_alarm_on, favorite_zone
            )
            VALUES (?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, ?, ?, ?)
            """,
            (plusfriend_key, active, is_alarm_on, favorite_zone),
        )
    zone_alarm_db.commit()

    users = ZoneAlarmReadRepository.list_zone_users(zone_alarm_db)

    assert users == [{"plusfriend_user_key": "pf-1", "favorite_zone": 1}]


def test_list_active_future_events_requires_active_coordinates_and_future_start(zone_alarm_db):
    for title, status, latitude, longitude, start_date in [
        ("future", "active", 37.5, 127.0, "2099-05-12T09:00:00"),
        ("inactive", "ended", 37.5, 127.0, "2099-05-12T09:00:00"),
        ("past", "active", 37.5, 127.0, "2000-05-12T09:00:00"),
    ]:
        zone_alarm_db.execute(
            """
            INSERT INTO events (
                title, location_name, latitude, longitude, start_date, status, category, severity_level
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (title, title, latitude, longitude, start_date, status, "notice", 1),
        )
    zone_alarm_db.commit()

    events = ZoneAlarmReadRepository.list_active_future_events(zone_alarm_db)

    assert [event["title"] for event in events] == ["future"]
