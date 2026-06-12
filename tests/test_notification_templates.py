from datetime import datetime
import sqlite3
from zoneinfo import ZoneInfo

import pytest

from app.routers import events as event_router
from app.routers import kakao_skills
from app.services.notification_payload_assembler import NotificationEventPayload
from app.services.notification_service import NotificationService


def insert_event(
    conn: sqlite3.Connection,
    *,
    event_id: int,
    description: str | None,
    attendees: str,
    location_name: str,
    location_address: str,
    start_date: str,
    end_date: str,
    image_path: str | None = None,
) -> None:
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


def test_route_alert_template_uses_numbered_brief_fields():
    events = [
        NotificationEventPayload(
            location="산업은행 측면 -> 신교교차로",
            description="도심 행진",
            start_date=datetime(2026, 5, 14, 11, 30),
            end_date=datetime(2026, 5, 14, 13, 0),
            attendees="70명",
        ),
        NotificationEventPayload(
            location="광화문 월대 -> 舊)효자치안센터",
            description="주최 측 집결",
            start_date="2026-05-14 14:30:00",
            end_date="2026-05-14 16:00:00",
            attendees="300명",
        ),
    ]

    message = NotificationService.format_event_message(events)

    assert message == (
        "경로상 감지된 집회 안내입니다.\n\n"
        "1.\n"
        "집회 일시 : 11:30 ~ 13:00\n"
        "집회 장소 : 산업은행 측면 -> 신교교차로\n"
        "상세 내용 : 도심 행진\n"
        "신고 인원 : 70명\n\n"
        "2.\n"
        "집회 일시 : 14:30 ~ 16:00\n"
        "집회 장소 : 광화문 월대 -> 舊)효자치안센터\n"
        "상세 내용 : 주최 측 집결\n"
        "신고 인원 : 300명"
    )


def test_zone_alert_template_uses_zone_header_and_unknown_description_default():
    events = [
        NotificationEventPayload(
            location="산업은행 측면 -> 신교교차로",
            description="미상",
            start_date="2026-05-14T11:30:00",
            end_date="2026-05-14T13:00:00",
            attendees="미상",
        ),
        NotificationEventPayload(
            location="광화문 월대 -> 舊)효자치안센터",
            description="미상",
            start_date="2026-05-14T14:30:00",
            end_date="2026-05-14T16:00:00",
            attendees="미상",
        ),
    ]

    message = NotificationService.format_zone_message("광화문광장", events)

    assert message == (
        "설정하신 광화문광장의 집회 안내입니다.\n\n"
        "1.\n"
        "집회 일시 : 11:30 ~ 13:00\n"
        "집회 장소 : 산업은행 측면 -> 신교교차로\n"
        "상세 내용 : 미상\n"
        "신고 인원 : 미상\n\n"
        "2.\n"
        "집회 일시 : 14:30 ~ 16:00\n"
        "집회 장소 : 광화문 월대 -> 舊)효자치안센터\n"
        "상세 내용 : 미상\n"
        "신고 인원 : 미상"
    )


@pytest.mark.asyncio
async def test_events_today_protests_uses_four_line_contract_from_db(clean_test_db):
    conn = sqlite3.connect(clean_test_db, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    today_kst = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    try:
        insert_event(
            conn,
            event_id=1,
            description="도심 행진",
            attendees="70명",
            location_name="산업은행 측면 -> 신교교차로",
            location_address="서울특별시 종로구 종로1가",
            start_date=f"{today_kst} 11:30:00",
            end_date=f"{today_kst} 13:00:00",
        )
        response = await event_router.get_today_protests({}, conn)
    finally:
        conn.close()

    assert response["template"]["outputs"][0]["simpleText"]["text"] == (
        "오늘 예정된 집회 안내입니다.\n\n"
        "1.\n"
        "집회 일시 : 11:30 ~ 13:00\n"
        "집회 장소 : 산업은행 측면 -> 신교교차로\n"
        "상세 내용 : 도심 행진\n"
        "신고 인원 : 70명"
    )


@pytest.mark.asyncio
async def test_kakao_skills_upcoming_protests_uses_four_line_contract_from_db(clean_test_db):
    conn = sqlite3.connect(clean_test_db, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        insert_event(
            conn,
            event_id=2,
            description="주최 측 집결",
            attendees="300명",
            location_name="광화문 월대 -> 舊)효자치안센터",
            location_address="서울특별시 종로구 세종대로",
            start_date="2999-05-14 14:30:00",
            end_date="2999-05-14 16:00:00",
        )
        response = await kakao_skills.get_upcoming_protests(
            {"action": {"params": {"limit": 1}}},
            conn,
        )
    finally:
        conn.close()

    assert response["template"]["outputs"][0]["simpleText"]["text"] == (
        "예정된 집회 안내입니다.\n\n"
        "1.\n"
        "집회 일시 : 14:30 ~ 16:00\n"
        "집회 장소 : 광화문 월대 -> 舊)효자치안센터\n"
        "상세 내용 : 주최 측 집결\n"
        "신고 인원 : 300명"
    )


@pytest.mark.asyncio
async def test_kakao_skills_upcoming_protests_includes_image_url_from_db(
    clean_test_db,
    settings_overrides,
):
    settings_overrides(RENDER_EXTERNAL_URL="http://localhost:8000")

    conn = sqlite3.connect(clean_test_db, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        insert_event(
            conn,
            event_id=3,
            description="이미지 포함 안내",
            attendees="150명",
            location_name="광화문광장 북측",
            location_address="서울특별시 종로구 세종대로",
            start_date="2999-05-15 10:00:00",
            end_date="2999-05-15 12:00:00",
            image_path="/attachments/protest_images/upcoming.png",
        )
        response = await kakao_skills.get_upcoming_protests(
            {"action": {"params": {"limit": 1}}},
            conn,
        )
    finally:
        conn.close()

    outputs = response["template"]["outputs"]
    assert outputs[0]["simpleImage"]["imageUrl"] == "http://localhost:8000/attachments/protest_images/upcoming.png"
    assert outputs[1]["simpleText"]["text"] == (
        "예정된 집회 안내입니다.\n\n"
        "1.\n"
        "집회 일시 : 10:00 ~ 12:00\n"
        "집회 장소 : 광화문광장 북측\n"
        "상세 내용 : 이미지 포함 안내\n"
        "신고 인원 : 150명"
    )
