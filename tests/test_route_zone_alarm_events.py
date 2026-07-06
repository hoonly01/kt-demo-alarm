from contextlib import contextmanager
import pytest
import sqlite3

from app.config.settings import settings
from app.routers import kakao_skills as skill_router
from app.services.event_service import EventService
from app.services.notification_payload_assembler import NotificationPayloadAssembler
from app.services.notification_service import NotificationService
from app.services.zone_alarm_service import ZoneAlarmService


def insert_event(
    conn,
    event_id=1,
    *,
    description="도심 행진",
    attendees="100명",
    location_name="교보빌딩 남측 -> 청진공원",
    location_address="서울특별시 종로구 종로1가",
    start_date="2999-05-15 11:00:00",
    end_date="2999-05-15 13:00:00",
    image_path=None,
):
    conn.execute(
        """
        INSERT INTO events (
            id, title, description, attendees, police_station, location_name,
            location_address, latitude, longitude, start_date, end_date, category,
            severity_level, image_path, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
        """,
        (
            event_id,
            "SMPA 집회",
            description,
            attendees,
            "종로",
            location_name,
            location_address,
            37.5720,
            126.9769,
            start_date,
            end_date,
            "protest",
            2,
            image_path,
        ),
    )
    conn.commit()


@contextmanager
def connect_db(path: str):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_route_event_check_returns_single_representative_event(clean_test_db):
    with connect_db(clean_test_db) as conn:
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
async def test_check_route_uses_same_four_line_contract_from_db(clean_test_db):
    with connect_db(clean_test_db) as conn:
        conn.execute(
            """
            INSERT INTO users (
                bot_user_key, plusfriend_user_key, active, is_alarm_on,
                departure_name, departure_x, departure_y, arrival_name, arrival_x, arrival_y
            )
            VALUES ('bot-1', 'pf-1', 1, 1, '출발', 126.9700, 37.5700, '도착', 126.9900, 37.5740)
            """
        )
        insert_event(
            conn,
            description="도심 행진",
            start_date="2999-05-15 11:00:00",
            end_date="2999-05-15 13:00:00",
        )

        response = await skill_router.check_user_route_events(
            {
                "userRequest": {
                    "user": {
                        "id": "bot-1",
                        "properties": {"plusfriendUserKey": "pf-1"},
                    }
                }
            },
            conn,
        )

    assert response["template"]["outputs"][0]["simpleText"]["text"] == (
        "경로상 감지된 집회 안내입니다.\n\n"
        "1.\n"
        "집회 일시 : 11:00 ~ 13:00\n"
        "집회 장소 : 교보빌딩 남측 -> 청진공원\n"
        "상세 내용 : 도심 행진\n"
        "신고 인원 : 100명"
    )


@pytest.mark.asyncio
async def test_route_alert_builder_uses_same_four_line_contract_from_event_responses(
    clean_test_db,
    settings_overrides,
):
    settings_overrides(RENDER_EXTERNAL_URL="http://localhost:8000")

    with connect_db(clean_test_db) as conn:
        conn.execute(
            """
            INSERT INTO users (
                bot_user_key, plusfriend_user_key, active, is_alarm_on,
                departure_name, departure_x, departure_y, arrival_name, arrival_x, arrival_y
            )
            VALUES ('bot-2', 'pf-2', 1, 1, '출발', 126.9700, 37.5700, '도착', 126.9900, 37.5740)
            """
        )
        insert_event(
            conn,
            description="순차 행진",
            attendees="120명",
            image_path="/attachments/protest_images/route.png",
        )

        result = await EventService.check_route_events("pf-2", auto_notify=False, db=conn)

    notification_events = NotificationPayloadAssembler.event_payloads_from_responses(result.events_found)
    alarm_data = NotificationService.build_event_alarm_data(notification_events)

    assert alarm_data["message"] == (
        "경로상 감지된 집회 안내입니다.\n\n"
        "1.\n"
        "집회 일시 : 11:00 ~ 13:00\n"
        "집회 장소 : 교보빌딩 남측 -> 청진공원\n"
        "상세 내용 : 순차 행진\n"
        "신고 인원 : 120명"
    )
    assert alarm_data["image_url"] == "http://localhost:8000/attachments/protest_images/route.png"


@pytest.mark.asyncio
async def test_zone_alarm_uses_single_representative_event_and_four_line_contract(
    clean_test_db,
    settings_overrides,
):
    settings_overrides(
        DATABASE_PATH=clean_test_db,
        BOT_ID="",
        KAKAO_EVENT_API_KEY="",
    )

    with connect_db(clean_test_db) as conn:
        conn.execute(
            """
            INSERT INTO users (bot_user_key, plusfriend_user_key, active, is_alarm_on, favorite_zone)
            VALUES ('bot-zone', 'pf-zone', 1, 1, 1)
            """
        )
        insert_event(
            conn,
            description=None,
            attendees="",
            location_name="광화문광장 동편",
            location_address="서울특별시 종로구 세종대로",
            image_path="/attachments/protest_images/zone.png",
        )

    result = await ZoneAlarmService.scheduled_zone_check()

    with connect_db(clean_test_db) as conn:
        rows = conn.execute(
            """
            SELECT id, title, description, attendees, police_station, location_name,
                   location_address, latitude, longitude, start_date, end_date, category,
                   severity_level, status, image_path
            FROM events
            WHERE id = 1
            """
        ).fetchall()

    notification_events = NotificationPayloadAssembler.event_payloads_from_rows([dict(row) for row in rows])
    alarm_data = NotificationService.build_zone_alarm_data(
        "광화문광장(1구역)",
        notification_events,
    )

    assert result["success"] is True
    assert result["total_users"] == 1
    assert result["notifications_sent"] == 0
    assert alarm_data["message"] == (
        "설정하신 광화문광장(1구역)의 집회 안내입니다.\n\n"
        "1.\n"
        "집회 일시 : 11:00 ~ 13:00\n"
        "집회 장소 : 광화문광장 동편\n"
        "상세 내용 : 미상\n"
        "신고 인원 : 미상"
    )
    assert alarm_data["image_url"] == "http://localhost:8000/attachments/protest_images/zone.png"
