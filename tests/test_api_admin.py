from datetime import datetime
from html import unescape
import os
import re
from typing import Any, cast
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from app.config.settings import settings
from app.database.connection import get_db_connection
from app.services.bus_notice_service import BusNoticeService

# Do not instantiate a global TestClient here.
# Use the `test_client` fixture to isolate the DB and rely on `clean_test_db`.

ADMIN_SECTION_HEADINGS = [
    "Overview",
    "데이터 수집 상태",
    "알림 발송 운영",
    "사용자 readiness",
    "수동 운영 액션",
    "이벤트/집회 탐색",
    "버스 공지 운영",
]

ADMIN_ACTION_ENDPOINTS = [
    "/admin/trigger-crawling",
    "/admin/trigger-bus-notice",
    "/admin/trigger-route-check",
    "/admin/trigger-zone-check",
    "/admin/trigger-test-alarm-for-user",
]

ADMIN_USER = "admin"
ADMIN_CREDENTIAL_ENV = "KT_DEMO_TEST_ADMIN_PASS"
ADMIN_PASS = os.environ.get(ADMIN_CREDENTIAL_ENV) or f"{ADMIN_USER}-test-auth"
ADMIN_AUTH = (ADMIN_USER, ADMIN_PASS)
INVALID_ADMIN_AUTH = (ADMIN_USER, f"invalid-{ADMIN_PASS}")
SOURCE_URL = "https://source.example/smpa/20260516-001"


def _set_admin_credentials(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ADMIN_USER", ADMIN_USER)
    monkeypatch.setattr(settings, "ADMIN_PASS", ADMIN_PASS)


def _restore_bus_notice_state(crawler, cached_notices, last_update) -> None:
    BusNoticeService.crawler = crawler
    BusNoticeService.cached_notices = cached_notices
    BusNoticeService.last_update = last_update


def test_admin_dashboard_no_credentials(test_client, monkeypatch):
    """인증 정보 없이 접근 시 401 에러를 반환해야 함"""
    monkeypatch.setattr(settings, "ADMIN_USER", ADMIN_USER)
    monkeypatch.setattr(settings, "ADMIN_PASS", ADMIN_PASS)

    response = test_client.get("/admin/dashboard")
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers
    assert response.headers["WWW-Authenticate"] == "Basic"

def test_admin_dashboard_invalid_credentials(test_client, monkeypatch):
    """잘못된 인증 정보로 접근 시 401 에러를 반환해야 함"""
    monkeypatch.setattr(settings, "ADMIN_USER", ADMIN_USER)
    monkeypatch.setattr(settings, "ADMIN_PASS", ADMIN_PASS)

    response = test_client.get("/admin/dashboard", auth=INVALID_ADMIN_AUTH)
    assert response.status_code == 401

@pytest.mark.usefixtures("clean_test_db")
def test_admin_dashboard_valid_credentials(test_client, monkeypatch):
    """올바른 인증 정보로 접근 시 200 OK와 HTML을 반환해야 함"""
    _set_admin_credentials(monkeypatch)

    response = test_client.get("/admin/dashboard", auth=ADMIN_AUTH)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "KT Demo Alarm Back-office" in response.text


@pytest.mark.usefixtures("clean_test_db")
def test_admin_dashboard_redesign_sections_and_operational_signals(test_client, monkeypatch):
    """대시보드는 7개 운영 섹션과 실제 sqlite 기반 운영 신호를 표시해야 함"""
    monkeypatch.setattr(settings, "ADMIN_USER", ADMIN_USER)
    monkeypatch.setattr(settings, "ADMIN_PASS", ADMIN_PASS)
    monkeypatch.setattr(BusNoticeService, "crawler", object())
    monkeypatch.setattr(BusNoticeService, "cached_notices", {"bus-1": {"seq": "bus-1"}})
    monkeypatch.setattr(
        BusNoticeService,
        "last_update",
        datetime(2026, 5, 16, 12, 0, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )

    with get_db_connection() as db:
        cursor = db.cursor()
        cursor.execute(
            """
            INSERT INTO events (
                title, description, attendees, police_station, location_name,
                location_address, latitude, longitude, start_date, end_date,
                severity_level, status, source, source_id, source_url,
                source_record_hash, source_payload_hash, collected_at,
                parser_version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "운영 신호 검증 집회",
                "운영자가 확인해야 하는 집회",
                "120명",
                "종로경찰서",
                "광화문광장",
                "서울 종로구 세종대로",
                37.5716,
                126.9784,
                "2026-05-16 13:00:00",
                "2026-05-16 15:00:00",
                3,
                "active",
                "SMPA",
                "smpa-1",
                "http://testserver/source/smpa-1",
                "source-record-hash-abcdef",
                "payload-hash-abcdef",
                "2026-05-16 01:00:00",
                "parser-v1",
                "2026-05-16 01:05:00",
                "2026-05-16 01:10:00",
            ),
        )
        event_id = cursor.lastrowid
        cursor.execute(
            """
            INSERT INTO alarm_tasks (
                task_id, alarm_type, status, total_recipients, successful_sends,
                failed_sends, event_id, request_data, error_messages,
                created_at, updated_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "task-failure-diagnostics",
                "bulk",
                "partial",
                5,
                3,
                2,
                event_id,
                f'{{"event_id": {event_id}, "target": "route"}}',
                '["Kakao timeout", "Invalid token"]',
                "2026-05-16 02:00:00",
                "2026-05-16 02:05:00",
                "2026-05-16 02:10:00",
            ),
        )
        cursor.execute(
            """
            INSERT INTO users (
                bot_user_key, plusfriend_user_key, first_message_at, last_message_at,
                message_count, active, is_alarm_on, departure_name, departure_address,
                departure_x, departure_y, arrival_name, arrival_address, arrival_x,
                arrival_y, route_updated_at, marked_bus, language, favorite_zone
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "bot-ready-user",
                "plusfriend-ready-user",
                "2026-05-16 09:00:00",
                "2026-05-16 09:30:00",
                7,
                1,
                1,
                "영통역",
                "수원시 영통구",
                127.071,
                37.251,
                "광화문역",
                "서울 종로구",
                126.9769,
                37.5709,
                "2026-05-16 09:40:00",
                "470",
                "ko",
                2,
            ),
        )
        db.commit()

    response = test_client.get("/admin/dashboard", auth=ADMIN_AUTH)
    rendered = unescape(response.text)

    assert response.status_code == 200
    for heading in ADMIN_SECTION_HEADINGS:
        assert heading in rendered
    for endpoint in ADMIN_ACTION_ENDPOINTS:
        assert endpoint in rendered

    assert "운영 신호 검증 집회" in rendered
    assert "SMPA" in rendered
    assert "source-recor" in rendered
    assert "parser-v1" in rendered
    assert "종로경찰서" in rendered
    assert "120명" in rendered
    assert f"event_id: {event_id}" in rendered
    assert "Kakao timeout" in rendered
    assert "Invalid token" in rendered
    assert "3</strong> success" in rendered
    assert "2</strong> failed" in rendered
    assert "Route ready" in rendered
    assert "Language: <strong>ko</strong>" in rendered
    assert "Crawler initialized" in rendered
    assert "cached_count" in rendered
    assert "2026-05-16 12:00:00 KST" in rendered


@pytest.mark.usefixtures("clean_test_db")
def test_admin_dashboard_action_catalog_endpoints(test_client, monkeypatch):
    """관리자 대시보드의 수동 운영 액션 catalog는 기존 endpoint만 노출해야 함"""
    _set_admin_credentials(monkeypatch)

    response = test_client.get("/admin/dashboard", auth=ADMIN_AUTH)

    assert response.status_code == 200
    for endpoint in [
        "/admin/trigger-crawling",
        "/admin/trigger-bus-notice",
        "/admin/trigger-route-check",
        "/admin/trigger-zone-check",
        "/admin/trigger-test-alarm-for-user",
    ]:
        assert endpoint in response.text


@pytest.mark.usefixtures("clean_test_db")
def test_admin_dashboard_displays_times_in_kst(test_client, monkeypatch):
    """관리자 대시보드의 운영 타임스탬프는 KST로 변환해서 표시해야 함"""
    _set_admin_credentials(monkeypatch)

    with get_db_connection() as db:
        cursor = db.cursor()
        cursor.execute(
            """
            INSERT INTO events (
                title, location_name, latitude, longitude, start_date,
                severity_level, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "KST 표시 검증 집회",
                "광화문",
                37.5716,
                126.9784,
                "2026-05-15 11:00:00",
                1,
                "active",
                "2026-05-15 00:30:00",
            ),
        )
        cursor.execute(
            """
            INSERT INTO alarm_tasks (
                task_id, alarm_type, status, total_recipients,
                successful_sends, failed_sends, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "task-kst-display",
                "bulk",
                "completed",
                3,
                3,
                0,
                "2026-05-15T09:40:00",
            ),
        )
        cursor.execute(
            """
            INSERT INTO alarm_tasks (
                task_id, alarm_type, status, total_recipients,
                successful_sends, failed_sends, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "task-utc-offset-display",
                "bulk",
                "completed",
                2,
                2,
                0,
                "2026-05-15T00:50:00+00:00",
            ),
        )
        cursor.execute(
            """
            INSERT INTO users (
                bot_user_key, first_message_at, last_message_at,
                message_count, active
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "kst-user",
                "2026-05-20 23:30:00",
                "2026-05-20 23:30:00",
                1,
                1,
            ),
        )
        db.commit()

    response = test_client.get("/admin/dashboard", auth=ADMIN_AUTH)

    assert response.status_code == 200
    assert "2026-05-15 09:30:00 KST" in response.text
    assert "2026-05-15 09:40:00 KST" in response.text
    assert "2026-05-15 09:50:00 KST" in response.text
    assert "광화문 • 2026-05-15 11:00:00 KST" in response.text
    assert "2026-05-15 20:00:00 KST" not in response.text
    assert "kst-user" in response.text
    assert "2026-05-20 KST" in response.text
    assert "2026-05-21" not in response.text


@pytest.mark.usefixtures("clean_test_db")
def test_admin_dashboard_renders_real_operational_aggregates_and_diagnostics(
    test_client,
    monkeypatch,
):
    """실제 sqlite/TestClient 경로로 수집·알림 실패·readiness·버스 캐시 운영 신호를 검증"""
    _set_admin_credentials(monkeypatch)

    original_bus_state = (
        BusNoticeService.crawler,
        BusNoticeService.cached_notices,
        BusNoticeService.last_update,
    )

    async def unexpected_async_bus_call(*_args, **_kwargs):
        raise AssertionError("dashboard render must not call BusNoticeService live methods")

    def unexpected_sync_bus_call(*_args, **_kwargs):
        raise AssertionError("dashboard render must not call BusNoticeService live methods")

    monkeypatch.setattr(BusNoticeService, "initialize", classmethod(unexpected_async_bus_call))
    monkeypatch.setattr(BusNoticeService, "refresh", classmethod(unexpected_async_bus_call))
    monkeypatch.setattr(BusNoticeService, "get_nearby_controls", classmethod(unexpected_sync_bus_call))
    monkeypatch.setattr(BusNoticeService, "get_route_controls", classmethod(unexpected_sync_bus_call))

    try:
        BusNoticeService.crawler = cast(Any, object())
        BusNoticeService.cached_notices = {
            "notice-470": {"title": "470 우회", "routes": ["470"]},
            "notice-741": {"title": "741 우회", "routes": ["741"]},
        }
        BusNoticeService.last_update = datetime(
            2026,
            5,
            16,
            9,
            30,
            tzinfo=ZoneInfo("Asia/Seoul"),
        )

        with get_db_connection() as db:
            cursor = db.cursor()
            cursor.execute(
                """
                INSERT INTO events (
                    title, description, attendees, police_station,
                    location_name, location_address, latitude, longitude,
                    start_date, end_date, category, severity_level, status,
                    source, source_id, source_url, source_record_hash,
                    source_payload_hash, collected_at, parser_version,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "운영 집회",
                    "운영 판단용 설명",
                    "1,200명",
                    "종로경찰서",
                    "광화문광장",
                    "서울 종로구 세종대로",
                    37.5716,
                    126.9784,
                    "2026-05-16 13:00:00",
                    "2026-05-16 15:00:00",
                    "assembly",
                    3,
                    "active",
                    "SMPA",
                    "SMPA-20260516-001",
                    SOURCE_URL,
                    "record-hash-admin-ops-1234567890",
                    "payload-hash-admin-ops-abcdef",
                    "2026-05-16T00:15:00+00:00",
                    "smpa-parser-v2",
                    "2026-05-16T00:20:00+00:00",
                    "2026-05-16T00:45:00+00:00",
                ),
            )
            event_id = cursor.lastrowid
            cursor.execute(
                """
                INSERT INTO alarm_tasks (
                    task_id, alarm_type, status, total_recipients,
                    successful_sends, failed_sends, event_id, request_data,
                    error_messages, created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "ops-alarm-task-failed",
                    "bulk",
                    "partial",
                    5,
                    3,
                    2,
                    event_id,
                    '{"target":"route-ready-user","retry_reason":"operator-smoke"}',
                    '["recipient timeout","partial provider failure"]',
                    "2026-05-16T01:00:00+00:00",
                    "2026-05-16T01:05:00+00:00",
                    "2026-05-16T01:10:00+00:00",
                ),
            )
            cursor.execute(
                """
                INSERT INTO users (
                    bot_user_key, plusfriend_user_key, open_id,
                    first_message_at, last_message_at, message_count, active,
                    is_alarm_on, departure_name, departure_address,
                    departure_x, departure_y, arrival_name, arrival_address,
                    arrival_x, arrival_y, route_updated_at, marked_bus,
                    language, favorite_zone
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "route-ready-user",
                    "plusfriend-route-ready",
                    "open-route-ready",
                    "2026-05-15 10:00:00",
                    "2026-05-16 08:20:00",
                    7,
                    1,
                    1,
                    "강남역",
                    "서울 강남구 강남대로",
                    127.0276,
                    37.4979,
                    "광화문역",
                    "서울 종로구 세종대로",
                    126.9784,
                    37.5716,
                    "2026-05-16 08:30:00",
                    "470",
                    "ko",
                    2,
                ),
            )
            cursor.execute(
                """
                INSERT INTO users (
                    bot_user_key, plusfriend_user_key, open_id,
                    first_message_at, last_message_at, message_count, active,
                    is_alarm_on, departure_name, departure_address,
                    departure_x, departure_y, arrival_name, arrival_address,
                    arrival_x, arrival_y, route_updated_at, marked_bus,
                    language, favorite_zone
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "named-route-user",
                    "plusfriend-named-route",
                    "open-named-route",
                    "2026-05-15 11:00:00",
                    "2026-05-16 08:40:00",
                    3,
                    1,
                    1,
                    "잠실역",
                    "서울 송파구 올림픽로",
                    None,
                    None,
                    "서울역",
                    "서울 용산구 한강대로",
                    None,
                    None,
                    "2026-05-16 08:50:00",
                    "741",
                    "ko",
                    1,
                ),
            )
            db.commit()

        response = test_client.get("/admin/dashboard", auth=ADMIN_AUTH)

        assert response.status_code == 200
        expected_markers = (
            "운영 집회",
            "SMPA",
            "source.example",
            "record-hash-admin",
            "payload-hash-admin",
            "smpa-parser-v2",
            "종로경찰서",
            "1,200명",
            "ops-alarm-task-failed",
            "event_id",
            str(event_id),
            "retry_reason",
            "recipient timeout",
            "partial provider failure",
            "2026-05-16 10:10:00 KST",
            "2/2",
            "100.0% route-ready",
            "route-ready",
            "강남역",
            "광화문역",
            "잠실역",
            "서울역",
            "470",
            "ko",
            "route-ready",
            "crawler_initialized",
            "cached_count",
            "2",
            "2026-05-16 09:30:00 KST",
        )
        for marker in expected_markers:
            assert marker in response.text
        assert re.search(r"record: record-hash[^<]*\.\.\.", response.text)
        assert re.search(r"payload: payload-hash[^<]*\.\.\.", response.text)
        assert "record-hash-admin-ops-1234567890" not in response.text
        assert "payload-hash-admin-ops-abcdef" not in response.text
    finally:
        _restore_bus_notice_state(*original_bus_state)


def test_admin_dashboard_missing_env_vars(test_client, monkeypatch):
    """환경변수가 설정되지 않은 경우 500 에러를 반환해야 함"""
    monkeypatch.setattr(settings, "ADMIN_USER", None)
    monkeypatch.setattr(settings, "ADMIN_PASS", None)

    response = test_client.get("/admin/dashboard", auth=ADMIN_AUTH)
    assert response.status_code == 500
    assert response.json() == {"detail": "Admin credentials are not configured on the server"}

@pytest.mark.parametrize("admin_user,admin_pass", [
    ("", ""),
    ("   ", "   "),
    ("admin", "   "),
    ("   ", "password"),
    ("", "password"),
    ("admin", ""),
])
def test_admin_dashboard_empty_or_whitespace_env_vars(test_client, monkeypatch, admin_user, admin_pass):
    """환경변수가 빈 문자열이거나 공백만 있는 경우 500 에러를 반환해야 함"""
    monkeypatch.setattr(settings, "ADMIN_USER", admin_user)
    monkeypatch.setattr(settings, "ADMIN_PASS", admin_pass)

    response = test_client.get("/admin/dashboard", auth=ADMIN_AUTH)
    assert response.status_code == 500
    assert response.json() == {"detail": "Admin credentials are not configured on the server"}

@pytest.mark.usefixtures("clean_test_db")
def test_admin_dashboard_pagination(test_client, monkeypatch):
    """Pagination 파라미터가 유효하게 작동하는지 검증"""
    monkeypatch.setattr(settings, "ADMIN_USER", ADMIN_USER)
    monkeypatch.setattr(settings, "ADMIN_PASS", ADMIN_PASS)

    # Check page=1, page_size=10
    response = test_client.get("/admin/dashboard?page=1&page_size=10", auth=ADMIN_AUTH)
    assert response.status_code == 200

    # Boundary cases: ge=1, le=200
    # Negative/zero page should fail validation
    for p in [0, -1]:
        response = test_client.get(f"/admin/dashboard?page={p}", auth=ADMIN_AUTH)
        assert response.status_code == 422

    # Zero page_size or too large should fail validation
    for ps in [0, 201]:
        response = test_client.get(f"/admin/dashboard?page_size={ps}", auth=ADMIN_AUTH)
        assert response.status_code == 422

    # Invalid type should fail
    response = test_client.get("/admin/dashboard?page=invalid", auth=ADMIN_AUTH)
    assert response.status_code == 422

def test_trigger_crawling_unauthorized(test_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USER", ADMIN_USER)
    monkeypatch.setattr(settings, "ADMIN_PASS", ADMIN_PASS)
    response = test_client.post("/admin/trigger-crawling")
    assert response.status_code == 401

def test_trigger_crawling_csrf_failure(test_client, monkeypatch):
    """Origin/Referer 헤더 누락 시 403 Forbidden 반환 검증"""
    monkeypatch.setattr(settings, "ADMIN_USER", ADMIN_USER)
    monkeypatch.setattr(settings, "ADMIN_PASS", ADMIN_PASS)

    # POST without Origin/Referer
    response = test_client.post("/admin/trigger-crawling", auth=ADMIN_AUTH)
    assert response.status_code == 403
    assert "Forbidden" in response.json()["detail"]

def test_trigger_crawling_authorized(test_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USER", ADMIN_USER)
    monkeypatch.setattr(settings, "ADMIN_PASS", ADMIN_PASS)

    # Mock to avoid real crawling and ensure task key cleanup
    mock_crawl = AsyncMock()
    headers = {"Origin": "http://testserver"}

    with monkeypatch.context() as m:
        m.setattr("app.routers.admin.crawl_and_sync_smpa_events", mock_crawl)
        response = test_client.post("/admin/trigger-crawling", auth=ADMIN_AUTH, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"message": "Scheduled"}

def test_trigger_crawling_authorized_with_api_key(test_client, monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "test-api-key")

    mock_crawl = AsyncMock()
    headers = {"X-API-Key": "test-api-key"}

    with monkeypatch.context() as m:
        m.setattr("app.routers.admin.crawl_and_sync_smpa_events", mock_crawl)
        response = test_client.post("/admin/trigger-crawling", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"message": "Scheduled"}
    mock_crawl.assert_called_once()

def test_trigger_bus_notice_authorized(test_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USER", ADMIN_USER)
    monkeypatch.setattr(settings, "ADMIN_PASS", ADMIN_PASS)

    mock_refresh = AsyncMock()
    headers = {"Origin": "http://testserver"}

    with monkeypatch.context() as m:
        m.setattr("app.services.bus_notice_service.BusNoticeService.refresh", mock_refresh)
        response = test_client.post("/admin/trigger-bus-notice", auth=ADMIN_AUTH, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"message": "Scheduled"}

def test_trigger_bus_notice_authorized_with_api_key(test_client, monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "test-api-key")

    mock_refresh = AsyncMock()
    headers = {"X-API-Key": "test-api-key"}

    with monkeypatch.context() as m:
        m.setattr("app.services.bus_notice_service.BusNoticeService.refresh", mock_refresh)
        response = test_client.post("/admin/trigger-bus-notice", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"message": "Scheduled"}
    mock_refresh.assert_called_once()

def test_trigger_bus_notice_rejects_invalid_api_key(test_client, monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "test-api-key")

    response = test_client.post(
        "/admin/trigger-bus-notice",
        headers={"X-API-Key": "wrong-key"},
    )

    assert response.status_code == 401


@pytest.mark.parametrize("endpoint", [
    "/admin/trigger-route-check",
    "/admin/trigger-zone-check",
    "/admin/trigger-test-alarm-for-user?user_id=12345",
])
def test_new_trigger_endpoints_reject_missing_credentials(test_client, monkeypatch, endpoint):
    monkeypatch.setattr(settings, "ADMIN_USER", ADMIN_USER)
    monkeypatch.setattr(settings, "ADMIN_PASS", ADMIN_PASS)

    response = test_client.post(endpoint)

    assert response.status_code == 401


@pytest.mark.parametrize("endpoint", [
    "/admin/trigger-route-check",
    "/admin/trigger-zone-check",
    "/admin/trigger-test-alarm-for-user?user_id=12345",
])
def test_new_trigger_endpoints_reject_invalid_api_key(test_client, monkeypatch, endpoint):
    monkeypatch.setattr(settings, "API_KEY", "test-api-key")

    response = test_client.post(
        endpoint,
        headers={"X-API-Key": "wrong-key"},
    )

    assert response.status_code == 401


def test_trigger_route_check_authorized_with_api_key(test_client, monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "test-api-key")

    mock_route_check = AsyncMock()

    monkeypatch.setattr("app.services.event_service.EventService.scheduled_route_check", mock_route_check)
    response = test_client.post(
        "/admin/trigger-route-check",
        headers={"X-API-Key": "test-api-key"},
    )

    assert response.status_code == 200
    assert response.json() == {"message": "Scheduled"}
    mock_route_check.assert_called_once()

def test_trigger_zone_check_authorized_with_api_key(test_client, monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "test-api-key")

    mock_zone_check = AsyncMock()

    monkeypatch.setattr("app.services.zone_alarm_service.ZoneAlarmService.scheduled_zone_check", mock_zone_check)
    response = test_client.post(
        "/admin/trigger-zone-check",
        headers={"X-API-Key": "test-api-key"},
    )

    assert response.status_code == 200
    assert response.json() == {"message": "Scheduled"}
    mock_zone_check.assert_called_once()

def test_trigger_test_alarm_for_user_authorized(test_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USER", ADMIN_USER)
    monkeypatch.setattr(settings, "ADMIN_PASS", ADMIN_PASS)

    mock_route_check = AsyncMock()
    headers = {"Origin": "http://testserver"}

    with monkeypatch.context() as m:
        m.setattr("app.services.event_service.EventService.check_route_events", mock_route_check)
        response = test_client.post("/admin/trigger-test-alarm-for-user?user_id=12345", auth=ADMIN_AUTH, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"message": "Scheduled"}

def test_trigger_test_alarm_for_user_authorized_with_api_key(test_client, monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "test-api-key")

    mock_route_check = AsyncMock()

    monkeypatch.setattr("app.services.event_service.EventService.check_route_events", mock_route_check)
    response = test_client.post(
        "/admin/trigger-test-alarm-for-user?user_id=12345",
        headers={"X-API-Key": "test-api-key"},
    )

    assert response.status_code == 200
    assert response.json() == {"message": "Scheduled"}
