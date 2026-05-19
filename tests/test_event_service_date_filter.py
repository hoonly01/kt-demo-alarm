import sqlite3
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.database.models import EVENTS_TABLE_SCHEMA
from app.services.event_service import EventService

KST = ZoneInfo("Asia/Seoul")
SQL_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
EVENT_START_TIME = time(hour=10, minute=0)
EVENT_END_TIME = time(hour=11, minute=30)
JONGNO_COORDINATES = (37.57, 126.98)
GANGNAM_COORDINATES = (37.50, 127.03)
WEEKEND_START_WEEKDAY = 5
JONGNO_POLICE_STATION = "종로"
DEFAULT_ATTENDEES = "100명"
DEFAULT_SEVERITY_LEVEL = 2
EVENT_CATEGORY = "protest"
EVENT_STATUS_ACTIVE = "active"
EVENT_STATUS_ENDED = "ended"


def _open_event_db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    _ = db.execute(EVENTS_TABLE_SCHEMA)
    return db


def _next_future_weekend_after(base_date: date) -> date:
    candidate = base_date + timedelta(days=1)
    while candidate.weekday() < WEEKEND_START_WEEKDAY:
        candidate += timedelta(days=1)
    return candidate


def _sql_datetime(event_date: date, event_time: time) -> str:
    return datetime.combine(event_date, event_time).strftime(SQL_DATETIME_FORMAT)


def _insert_event(
    db: sqlite3.Connection,
    *,
    title: str,
    event_date: date,
    status: str = EVENT_STATUS_ACTIVE,
    location_name: str = "종로 테스트 집회",
    location_address: str = "서울 종로구 세종대로 1",
    coordinates: tuple[float, float] = JONGNO_COORDINATES,
) -> None:
    _ = db.execute(
        """
        INSERT INTO events (
            title, attendees, police_station, location_name, location_address,
            latitude, longitude, start_date, end_date, category, severity_level, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            DEFAULT_ATTENDEES,
            JONGNO_POLICE_STATION,
            location_name,
            location_address,
            coordinates[0],
            coordinates[1],
            _sql_datetime(event_date, EVENT_START_TIME),
            _sql_datetime(event_date, EVENT_END_TIME),
            EVENT_CATEGORY,
            DEFAULT_SEVERITY_LEVEL,
            status,
        ),
    )


def test_get_today_events_returns_only_active_jongno_events_for_kst_today():
    today = datetime.now(KST).date()
    tomorrow = today + timedelta(days=1)
    future_weekend = _next_future_weekend_after(tomorrow)
    db = _open_event_db()

    try:
        _insert_event(db, title="오늘 종로 집회", event_date=today)
        _insert_event(db, title="사전 저장된 내일 종로 집회", event_date=tomorrow)
        _insert_event(db, title="사전 저장된 주말 종로 집회", event_date=future_weekend)
        _insert_event(
            db,
            title="오늘 강남 집회",
            event_date=today,
            location_name="강남 테스트 집회",
            location_address="서울 강남구 테헤란로 1",
            coordinates=GANGNAM_COORDINATES,
        )
        _insert_event(
            db,
            title="종료된 오늘 종로 집회",
            event_date=today,
            status=EVENT_STATUS_ENDED,
        )

        events = EventService.get_today_events(db)

        assert [event.title for event in events] == ["오늘 종로 집회"]
        assert {event.start_date.date() for event in events} == {today}
    finally:
        db.close()
