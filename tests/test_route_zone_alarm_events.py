import pytest
import sqlite3
from contextlib import contextmanager

from app.config.settings import settings
from app.database.connection import get_db_connection
from app.services.event_service import EventService
from app.services.zone_alarm_service import ZoneAlarmService


def insert_event(conn, event_id=1):
    conn.execute(
        """
        INSERT INTO events (
            id, title, description, attendees, police_station, location_name,
            location_address, latitude, longitude, start_date, end_date, category,
            severity_level, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
        """,
        (
            event_id,
            "SMPA 집회",
            "legacy description",
            "100명",
            "종로",
            "교보빌딩 남측 -> 청진공원",
            "서울특별시 종로구 종로1가",
            37.5720,
            126.9769,
            "2999-05-15 11:00:00",
            "2999-05-15 13:00:00",
            "protest",
            2,
        ),
    )
    conn.commit()
@pytest.mark.asyncio
async def test_route_event_check_returns_single_representative_event(clean_test_db, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_PATH", clean_test_db)
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (
                bot_user_key, plusfriend_user_key, active, is_alarm_on,
                departure_name, departure_x, departure_y, arrival_name, arrival_x, arrival_y
            )
            VALUES ('bot-1', 'pf-1', 1, 1, '출발', 126.9700, 37.5700, '도착', 126.9900, 37.5740)
            """
        )
        insert_event(conn)

        result = await EventService.check_route_events("pf-1", auto_notify=False, db=conn)

    assert result.total_events == 1
    assert result.events_found[0].attendees == "100명"
    assert result.events_found[0].location_name == "교보빌딩 남측 -> 청진공원"


@pytest.mark.asyncio
async def test_zone_alarm_uses_single_representative_event_and_attendees(clean_test_db, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_PATH", clean_test_db)
    monkeypatch.setattr(settings, "BOT_ID", "")
    monkeypatch.setattr(settings, "KAKAO_EVENT_API_KEY", "")

    @contextmanager
    def test_db_connection():
        conn = sqlite3.connect(clean_test_db, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr("app.services.zone_alarm_service.get_db_connection", test_db_connection)
    monkeypatch.setattr("app.services.alarm_status_service.get_db_connection", test_db_connection)

    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (bot_user_key, plusfriend_user_key, active, is_alarm_on, favorite_zone)
            VALUES ('bot-zone', 'pf-zone', 1, 1, 1)
            """
        )
        insert_event(conn)
        matching_users = conn.execute(
            """
            SELECT COUNT(*) FROM users
            WHERE active = 1
              AND is_alarm_on = 1
              AND favorite_zone IS NOT NULL
              AND plusfriend_user_key IS NOT NULL
            """
        ).fetchone()[0]
        assert matching_users == 1

    result = await ZoneAlarmService.scheduled_zone_check()

    assert result["success"] is True
    assert result["total_users"] == 1
    assert result["notifications_sent"] == 0
