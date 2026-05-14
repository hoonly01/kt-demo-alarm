"""Event repository integration tests."""
import os
import sqlite3
import tempfile
from typing import Iterator

import pytest

from app.database.models import EVENTS_TABLE_SCHEMA
from app.repositories.event_repository import EventRepository


@pytest.fixture
def event_db_pair() -> Iterator[tuple[sqlite3.Connection, sqlite3.Connection]]:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    writer = sqlite3.connect(db_path)
    reader = sqlite3.connect(db_path)
    writer.row_factory = sqlite3.Row
    reader.row_factory = sqlite3.Row
    writer.execute(EVENTS_TABLE_SCHEMA)
    writer.commit()

    try:
        yield writer, reader
    finally:
        writer.close()
        reader.close()
        try:
            os.remove(db_path)
        except FileNotFoundError:
            pass


def _event_count(db: sqlite3.Connection) -> int:
    cursor = db.execute("SELECT COUNT(*) FROM events")
    return int(cursor.fetchone()[0])


def test_create_event_uses_caller_transaction(event_db_pair):
    writer, reader = event_db_pair

    event_id = EventRepository.create_event(
        writer,
        title="종로 집회",
        description="테스트 설명",
        location_name="종로구청",
        location_address="서울 종로구",
        latitude=37.5729,
        longitude=126.9794,
        start_date="2026-05-12T10:00:00",
        end_date="2026-05-12T12:00:00",
        category="protest",
        severity_level=2,
        status="active",
    )

    assert event_id == 1
    assert _event_count(writer) == 1
    assert _event_count(reader) == 0

    writer.commit()

    saved = EventRepository.get_by_id(reader, event_id)
    assert saved is not None
    assert saved["title"] == "종로 집회"
    assert saved["status"] == "active"
    assert saved["severity_level"] == 2


def test_list_events_filters_orders_and_limits(event_db_pair):
    writer, reader = event_db_pair
    EventRepository.create_event(
        writer,
        title="old-active",
        description=None,
        location_name="서울광장",
        location_address=None,
        latitude=37.5,
        longitude=127.0,
        start_date="2026-05-01T09:00:00",
        end_date=None,
        category="notice",
        severity_level=1,
        status="active",
    )
    EventRepository.create_event(
        writer,
        title="new-active",
        description=None,
        location_name="광화문",
        location_address=None,
        latitude=37.5,
        longitude=127.0,
        start_date="2026-05-12T09:00:00",
        end_date=None,
        category="notice",
        severity_level=3,
        status="active",
    )
    EventRepository.create_event(
        writer,
        title="inactive",
        description=None,
        location_name="청계천",
        location_address=None,
        latitude=37.5,
        longitude=127.0,
        start_date="2026-05-13T09:00:00",
        end_date=None,
        category="notice",
        severity_level=2,
        status="ended",
    )
    writer.commit()

    rows = EventRepository.list_events(reader, category="notice", status="active", limit=1)

    assert [row["title"] for row in rows] == ["new-active"]


def test_list_upcoming_and_today_events(event_db_pair):
    writer, reader = event_db_pair
    for title, location_name, location_address, start_date, status in [
        ("past", "종로", "서울 종로구", "2026-05-11T09:00:00", "active"),
        ("future", "광화문", "서울 종로구", "2026-05-12T11:00:00", "active"),
        ("later", "시청", "서울 중구", "2026-05-13T11:00:00", "active"),
        ("inactive", "종로", "서울 종로구", "2026-05-12T12:00:00", "cancelled"),
    ]:
        EventRepository.create_event(
            writer,
            title=title,
            description=None,
            location_name=location_name,
            location_address=location_address,
            latitude=37.5,
            longitude=127.0,
            start_date=start_date,
            end_date=None,
            category="notice",
            severity_level=1,
            status=status,
        )
    writer.commit()

    upcoming = EventRepository.list_upcoming(
        reader,
        now="2026-05-12T10:00:00",
        limit=2,
    )
    assert [row["title"] for row in upcoming] == ["future", "later"]

    today = EventRepository.list_today_by_location_pattern(
        reader,
        today="2026-05-12",
        location_pattern="%종로%",
    )
    assert [row["title"] for row in today] == ["future"]
