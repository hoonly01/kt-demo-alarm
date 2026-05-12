"""Route event query repository integration tests."""
import os
import sqlite3
import tempfile
from typing import Iterator

import pytest

from app.database.models import EVENTS_TABLE_SCHEMA
from app.repositories.route_event_query_repository import RouteEventQueryRepository


@pytest.fixture
def route_event_db() -> Iterator[sqlite3.Connection]:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
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


def _insert_event(
    db: sqlite3.Connection,
    *,
    title: str,
    status: str = "active",
    start_modifier: str = "+10 hours",
) -> None:
    db.execute(
        """
        INSERT INTO events (
            title, description, location_name, location_address,
            latitude, longitude, start_date, end_date, category,
            severity_level, status
        )
        VALUES (?, ?, ?, ?, ?, ?, datetime('now', ?), datetime('now', '+11 hours'), ?, ?, ?)
        """,
        (
            title,
            f"{title} 설명",
            "광화문",
            "서울 종로구",
            37.572,
            126.9769,
            start_modifier,
            "집회",
            2,
            status,
        ),
    )


def test_list_active_future_events_filters_status_time_and_orders(route_event_db):
    _insert_event(route_event_db, title="future-2", start_modifier="+12 hours")
    _insert_event(route_event_db, title="past", start_modifier="+8 hours")
    _insert_event(route_event_db, title="inactive", status="cancelled", start_modifier="+10 hours")
    _insert_event(route_event_db, title="future-1", start_modifier="+10 hours")
    route_event_db.commit()

    rows = RouteEventQueryRepository.list_active_future_events(route_event_db)

    assert [row["title"] for row in rows] == ["future-1", "future-2"]
    assert all(row["status"] == "active" for row in rows)
