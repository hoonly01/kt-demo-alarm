import os
import pytest
from unittest.mock import AsyncMock
from app.config.settings import settings

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

def test_admin_dashboard_valid_credentials(test_client, monkeypatch):
    """올바른 인증 정보로 접근 시 200 OK와 HTML을 반환해야 함"""
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASS", "secret123")
    
    response = test_client.get("/admin/dashboard", auth=("admin", "secret123"))
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "KT Demo Alarm Back-office" in response.text

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
        m.setattr("app.services.crawling_service.CrawlingService.crawl_and_sync_events", mock_crawl)
        response = test_client.post("/admin/trigger-crawling", auth=("admin", "secret123"), headers=headers)
        
    assert response.status_code == 200
    assert response.json() == {"message": "Scheduled"}

def test_trigger_crawling_authorized_with_api_key(test_client, monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "test-api-key")

    mock_crawl = AsyncMock()
    headers = {"X-API-Key": "test-api-key"}

    with monkeypatch.context() as m:
        m.setattr("app.services.crawling_service.CrawlingService.crawl_and_sync_events", mock_crawl)
        response = test_client.post("/admin/trigger-crawling", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"message": "Scheduled"}

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

def test_trigger_bus_notice_rejects_invalid_api_key(test_client, monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "test-api-key")

    response = test_client.post(
        "/admin/trigger-bus-notice",
        headers={"X-API-Key": "wrong-key"},
    )

    assert response.status_code == 401

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

    with monkeypatch.context() as m:
        m.setattr("app.services.event_service.EventService.check_route_events", mock_route_check)
        response = test_client.post(
            "/admin/trigger-test-alarm-for-user?user_id=12345",
            headers={"X-API-Key": "test-api-key"},
        )

    assert response.status_code == 200
    assert response.json() == {"message": "Scheduled"}
