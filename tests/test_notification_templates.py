from datetime import datetime
from types import SimpleNamespace

import pytest

from app.routers import events as event_router
from app.routers import kakao_skills
from app.services.notification_service import NotificationService


def test_route_alert_template_uses_numbered_brief_fields():
    events = [
        {
            "location": "산업은행 측면 -> 신교교차로",
            "start_date": datetime(2026, 5, 14, 11, 30),
            "end_date": datetime(2026, 5, 14, 13, 0),
            "attendees": "70명",
        },
        {
            "location": "광화문 월대 -> 舊)효자치안센터",
            "start_date": "2026-05-14 14:30:00",
            "end_date": "2026-05-14 16:00:00",
            "attendees": "300명",
        },
    ]

    message = NotificationService._format_event_message(events)

    assert message == (
        "경로상 감지된 집회 안내입니다.\n\n"
        "1.\n"
        "집회 일시 : 11:30 ~ 13:00\n"
        "집회 장소 : 산업은행 측면 -> 신교교차로\n"
        "신고 인원 : 70명\n\n"
        "2.\n"
        "집회 일시 : 14:30 ~ 16:00\n"
        "집회 장소 : 광화문 월대 -> 舊)효자치안센터\n"
        "신고 인원 : 300명"
    )


def test_zone_alert_template_uses_zone_header_and_unknown_description_default():
    events = [
        {
            "location": "산업은행 측면 -> 신교교차로",
            "start_date": "2026-05-14T11:30:00",
            "end_date": "2026-05-14T13:00:00",
            "attendees": "",
        },
        {
            "location": "광화문 월대 -> 舊)효자치안센터",
            "start_date": "2026-05-14T14:30:00",
            "end_date": "2026-05-14T16:00:00",
            "attendees": None,
        }
    ]

    message = NotificationService._format_zone_message("광화문광장", events)

    assert message == (
        "설정하신 광화문광장의 집회 안내입니다.\n\n"
        "1.\n"
        "집회 일시 : 11:30 ~ 13:00\n"
        "집회 장소 : 산업은행 측면 -> 신교교차로\n"
        "신고 인원 : 미상\n\n"
        "2.\n"
        "집회 일시 : 14:30 ~ 16:00\n"
        "집회 장소 : 광화문 월대 -> 舊)효자치안센터\n"
        "신고 인원 : 미상"
    )


@pytest.mark.asyncio
async def test_events_today_protests_uses_numbered_brief_template(monkeypatch):
    monkeypatch.setattr(
        event_router.EventService,
        "get_today_events",
        lambda db: [
            SimpleNamespace(
                description="legacy description must not be used",
                attendees="70명",
                location_name="산업은행 측면 -> 신교교차로",
                start_date="2026-05-14 11:30:00",
                end_date="2026-05-14 13:00:00",
            )
        ],
    )

    response = await event_router.get_today_protests({}, None)

    assert response["template"]["outputs"][0]["simpleText"]["text"] == (
        "오늘 예정된 집회 안내입니다.\n\n"
        "1.\n"
        "집회 일시 : 11:30 ~ 13:00\n"
        "집회 장소 : 산업은행 측면 -> 신교교차로\n"
        "신고 인원 : 70명"
    )


@pytest.mark.asyncio
async def test_kakao_skills_upcoming_protests_uses_numbered_brief_template(monkeypatch):
    monkeypatch.setattr(
        kakao_skills.EventService,
        "get_upcoming_events",
        lambda limit, db: [
            SimpleNamespace(
                description="legacy description must not be used",
                attendees="300명",
                location_name="광화문 월대 -> 舊)효자치안센터",
                start_date="2026-05-14T14:30:00",
                end_date="2026-05-14T16:00:00",
            )
        ],
    )

    response = await kakao_skills.get_upcoming_protests({"action": {"params": {"limit": 1}}}, None)

    assert response["template"]["outputs"][0]["simpleText"]["text"] == (
        "예정된 집회 안내입니다.\n\n"
        "1.\n"
        "집회 일시 : 14:30 ~ 16:00\n"
        "집회 장소 : 광화문 월대 -> 舊)효자치안센터\n"
        "신고 인원 : 300명"
    )
