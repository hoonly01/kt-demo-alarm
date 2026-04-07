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
    
    # Check invalid page should default fallback or fail gracefully depending on FastAPI validation
    response = test_client.get("/admin/dashboard?page=invalid", auth=("admin", "secret123"))
    assert response.status_code == 422  # Validation error from FastAPI

def test_trigger_crawling_unauthorized(test_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASS", "secret123")
    response = test_client.post("/admin/trigger-crawling")
    assert response.status_code == 401

def test_trigger_crawling_authorized(test_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASS", "secret123")
    
    mock_crawl = AsyncMock()
    with monkeypatch.context() as m:
        m.setattr("app.services.crawling_service.CrawlingService.crawl_and_sync_events", mock_crawl)
        response = test_client.post("/admin/trigger-crawling", auth=("admin", "secret123"))
        
    assert response.status_code == 200
    assert response.json() == {"message": "Success"}

def test_trigger_bus_notice_authorized(test_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASS", "secret123")
    
    mock_refresh = AsyncMock()
    with monkeypatch.context() as m:
        m.setattr("app.services.bus_notice_service.BusNoticeService.refresh", mock_refresh)
        response = test_client.post("/admin/trigger-bus-notice", auth=("admin", "secret123"))
        
    assert response.status_code == 200
    assert response.json() == {"message": "Success"}

def test_trigger_test_alarm_authorized(test_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASS", "secret123")
    
    mock_route_check = AsyncMock()
    with monkeypatch.context() as m:
        m.setattr("app.services.event_service.EventService.scheduled_route_check", mock_route_check)
        response = test_client.post("/admin/trigger-test-alarm", auth=("admin", "secret123"))
        
    assert response.status_code == 200
    assert response.json() == {"message": "Success"}
