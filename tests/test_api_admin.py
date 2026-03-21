import os
import pytest
from fastapi.testclient import TestClient
from main import app
from app.config.settings import settings

client = TestClient(app)

def test_admin_dashboard_no_credentials(monkeypatch):
    """인증 정보 없이 접근 시 401 에러를 반환해야 함"""
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASS", "secret123")
    
    response = client.get("/admin/dashboard")
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers
    assert response.headers["WWW-Authenticate"] == "Basic"

def test_admin_dashboard_invalid_credentials(monkeypatch):
    """잘못된 인증 정보로 접근 시 401 에러를 반환해야 함"""
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASS", "secret123")
    
    response = client.get("/admin/dashboard", auth=("admin", "wrongpassword"))
    assert response.status_code == 401

def test_admin_dashboard_valid_credentials(monkeypatch):
    """올바른 인증 정보로 접근 시 200 OK와 HTML을 반환해야 함"""
    monkeypatch.setattr(settings, "ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASS", "secret123")
    
    response = client.get("/admin/dashboard", auth=("admin", "secret123"))
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "KT Demo Alarm Back-office" in response.text

def test_admin_dashboard_missing_env_vars(monkeypatch):
    """환경변수가 설정되지 않은 경우 500 에러를 반환해야 함"""
    monkeypatch.setattr(settings, "ADMIN_USER", None)
    monkeypatch.setattr(settings, "ADMIN_PASS", None)
    
    response = client.get("/admin/dashboard", auth=("admin", "secret123"))
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
def test_admin_dashboard_empty_or_whitespace_env_vars(monkeypatch, admin_user, admin_pass):
    """환경변수가 빈 문자열이거나 공백만 있는 경우 500 에러를 반환해야 함"""
    monkeypatch.setattr(settings, "ADMIN_USER", admin_user)
    monkeypatch.setattr(settings, "ADMIN_PASS", admin_pass)
    
    response = client.get("/admin/dashboard", auth=("admin", "secret123"))
    assert response.status_code == 500
    assert response.json() == {"detail": "Admin credentials are not configured on the server"}
