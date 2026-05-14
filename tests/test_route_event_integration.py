"""Route/event orchestration integration tests."""
import os
import sqlite3
import tempfile
from typing import Iterator

import pytest

from app.config.settings import settings
from app.database.models import EVENTS_TABLE_SCHEMA, USERS_TABLE_SCHEMA
from app.services.event_service import EventService


@pytest.fixture
def route_event_integration_db() -> Iterator[sqlite3.Connection]:
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


def _insert_route_user(db: sqlite3.Connection) -> None:
    db.execute(
        """
        INSERT INTO users (
            bot_user_key, plusfriend_user_key, first_message_at, last_message_at,
            message_count, active, is_alarm_on,
            departure_name, departure_address, departure_x, departure_y,
            arrival_name, arrival_address, arrival_x, arrival_y
        )
        VALUES (
            'bot-route', 'pf-route', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
            1, 1, 1,
            '출발', '출발 주소', 127.0, 37.0,
            '도착', '도착 주소', 127.1, 37.1
        )
        """
    )


def _insert_route_event(
    db: sqlite3.Connection,
    *,
    title: str,
    latitude: float,
    longitude: float,
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
            latitude,
            longitude,
            start_modifier,
            "집회",
            3,
            status,
        ),
    )


@pytest.mark.asyncio
async def test_check_route_events_combines_route_read_and_active_event_query(
    route_event_integration_db,
    monkeypatch,
):
    monkeypatch.setattr(settings, "TMAP_APP_KEY", None)
    monkeypatch.setattr(settings, "KAKAO_LOCATION_API_KEY", None)
    _insert_route_user(route_event_integration_db)
    _insert_route_event(
        route_event_integration_db,
        title="경로 인근 예정 집회",
        latitude=37.05,
        longitude=127.05,
    )
    _insert_route_event(
        route_event_integration_db,
        title="지난 집회",
        latitude=37.05,
        longitude=127.05,
        start_modifier="+8 hours",
    )
    _insert_route_event(
        route_event_integration_db,
        title="취소 집회",
        latitude=37.05,
        longitude=127.05,
        status="cancelled",
    )
    route_event_integration_db.commit()

    result = await EventService.check_route_events(
        "pf-route",
        auto_notify=False,
        db=route_event_integration_db,
    )

    assert result.user_id == "pf-route"
    assert [event.title for event in result.events_found] == ["경로 인근 예정 집회"]
    assert result.total_events == 1
    assert result.route_info["departure"]["name"] == "출발"
