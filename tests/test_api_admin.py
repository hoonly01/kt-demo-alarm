import pytest
from unittest.mock import AsyncMock
from app.config.settings import settings
from app.database.connection import get_db_connection

# Do not instantiate a global TestClient here.
# Use the `test_client` fixture to isolate the DB and rely on `clean_test_db`.

def test_admin_dashboard_no_credentials(test_client, monkeypatch):
    """인증 정보 없이 접근 시 401 에러를 반환해야 함"""
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASS", "secret123")
    
    response = test_client.get("/admin/dashboard")
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers
    assert response.headers["WWW-Authenticate"] == "Basic"

def test_admin_dashboard_invalid_credentials(test_client, monkeypatch):
    """잘못된 인증 정보로 접근 시 401 에러를 반환해야 함"""
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASS", "secret123")
    
    response = test_client.get("/admin/dashboard", auth=("admin", "wrongpassword"))
    assert response.status_code == 401

@pytest.mark.usefixtures("clean_test_db")
def test_admin_dashboard_valid_credentials(test_client, monkeypatch):
    """올바른 인증 정보로 접근 시 200 OK와 HTML을 반환해야 함"""
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASS", "secret123")
    
    response = test_client.get("/admin/dashboard", auth=("admin", "secret123"))
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "KT Demo Alarm Back-office" in response.text


@pytest.mark.usefixtures("clean_test_db")
def test_admin_dashboard_displays_times_in_kst(test_client, monkeypatch):
    """관리자 대시보드의 운영 타임스탬프는 KST로 변환해서 표시해야 함"""
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASS", "secret123")

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

    response = test_client.get("/admin/dashboard", auth=("admin", "secret123"))

    assert response.status_code == 200
    assert "2026-05-15 09:30:00 KST" in response.text
    assert "2026-05-15 09:40:00 KST" in response.text
    assert "2026-05-15 09:50:00 KST" in response.text
    assert "광화문 • 2026-05-15 11:00:00 KST" in response.text
    assert "2026-05-15 20:00:00 KST" not in response.text
    assert "kst-user" in response.text
    assert "2026-05-20 KST" in response.text
    assert "2026-05-21" not in response.text

def test_admin_dashboard_missing_env_vars(test_client, monkeypatch):
    """환경변수가 설정되지 않은 경우 500 에러를 반환해야 함"""
    monkeypatch.setattr(settings, "ADMIN_USER", None)
    monkeypatch.setattr(settings, "ADMIN_PASS", None)
    
    response = test_client.get("/admin/dashboard", auth=("admin", "secret123"))
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
    
    response = test_client.get("/admin/dashboard", auth=("admin", "secret123"))
    assert response.status_code == 500
    assert response.json() == {"detail": "Admin credentials are not configured on the server"}

@pytest.mark.usefixtures("clean_test_db")
def test_admin_dashboard_pagination(test_client, monkeypatch):
    """Pagination 파라미터가 유효하게 작동하는지 검증"""
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASS", "secret123")
    
    # Check page=1, page_size=10
    response = test_client.get("/admin/dashboard?page=1&page_size=10", auth=("admin", "secret123"))
    assert response.status_code == 200
    
    # Boundary cases: ge=1, le=200
    # Negative/zero page should fail validation
    for p in [0, -1]:
        response = test_client.get(f"/admin/dashboard?page={p}", auth=("admin", "secret123"))
        assert response.status_code == 422
        
    # Zero page_size or too large should fail validation
    for ps in [0, 201]:
        response = test_client.get(f"/admin/dashboard?page_size={ps}", auth=("admin", "secret123"))
        assert response.status_code == 422

    # Invalid type should fail
    response = test_client.get("/admin/dashboard?page=invalid", auth=("admin", "secret123"))
    assert response.status_code == 422

def test_trigger_crawling_unauthorized(test_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASS", "secret123")
    response = test_client.post("/admin/trigger-crawling")
    assert response.status_code == 401

def test_trigger_crawling_csrf_failure(test_client, monkeypatch):
    """Origin/Referer 헤더 누락 시 403 Forbidden 반환 검증"""
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASS", "secret123")
    
    # POST without Origin/Referer
    response = test_client.post("/admin/trigger-crawling", auth=("admin", "secret123"))
    assert response.status_code == 403
    assert "Forbidden" in response.json()["detail"]

def test_trigger_crawling_authorized(test_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASS", "secret123")
    
    # Mock to avoid real crawling and ensure task key cleanup
    mock_crawl = AsyncMock()
    headers = {"Origin": "http://testserver"}
    
    with monkeypatch.context() as m:
        m.setattr("app.routers.admin.crawl_and_sync_smpa_events", mock_crawl)
        response = test_client.post("/admin/trigger-crawling", auth=("admin", "secret123"), headers=headers)
        
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
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASS", "secret123")
    
    mock_refresh = AsyncMock()
    headers = {"Origin": "http://testserver"}
    
    with monkeypatch.context() as m:
        m.setattr("app.services.bus_notice_service.BusNoticeService.refresh", mock_refresh)
        response = test_client.post("/admin/trigger-bus-notice", auth=("admin", "secret123"), headers=headers)
        
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
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASS", "secret123")

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
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASS", "secret123")
    
    mock_route_check = AsyncMock()
    headers = {"Origin": "http://testserver"}
    
    with monkeypatch.context() as m:
        m.setattr("app.services.event_service.EventService.check_route_events", mock_route_check)
        response = test_client.post("/admin/trigger-test-alarm-for-user?user_id=12345", auth=("admin", "secret123"), headers=headers)
        
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
