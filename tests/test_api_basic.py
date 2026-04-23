"""Test basic API functionality"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock


def test_root_endpoint(test_client):
    """Test the root endpoint"""
    response = test_client.get("/")
    assert response.status_code == 200
    
    data = response.json()
    assert "message" in data
    assert "version" in data
    assert "status" in data
    assert data["status"] == "healthy"


def test_api_docs_available(test_client):
    """Test that API documentation is available"""
    response = test_client.get("/docs")
    assert response.status_code == 200
    
    response = test_client.get("/redoc")
    assert response.status_code == 200
    
    response = test_client.get("/openapi.json")
    assert response.status_code == 200


def test_alarm_status_list_empty(test_client, clean_test_db):
    """Test alarm status list when empty"""
    response = test_client.get("/alarms/status")
    assert response.status_code == 200
    
    data = response.json()
    assert "tasks" in data
    assert "total" in data
    assert "limit" in data
    assert data["total"] == 0
    assert len(data["tasks"]) == 0


def test_alarm_status_nonexistent_task(test_client):
    """Test alarm status for non-existent task"""
    response = test_client.get("/alarms/status/nonexistent-task-id")
    assert response.status_code == 404
    
    data = response.json()
    assert "detail" in data
    assert "찾을 수 없습니다" in data["detail"]


def test_cleanup_old_tasks_endpoint(test_client, clean_test_db):
    """Test cleanup old alarm tasks endpoint"""
    # API Key 인증 필요 (headers에 추가)
    headers = {"x-api-key": "test-api-key"}
    response = test_client.post("/alarms/cleanup-old-tasks?days=30", headers=headers)
    assert response.status_code == 200
    
    data = response.json()
    assert "message" in data
    assert "deleted_count" in data
    assert "retention_days" in data
    assert data["retention_days"] == 30


def test_events_list_empty(test_client, clean_test_db):
    """Test events list when empty"""
    response = test_client.get("/events")
    assert response.status_code == 200
    
    # Should return empty list
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 0


def test_scheduler_status(test_client):
    """Test scheduler status endpoint"""
    response = test_client.get("/scheduler/status")
    assert response.status_code == 200
    
    data = response.json()
    assert "scheduler" in data
    assert "status" in data["scheduler"]
    assert "jobs" in data["scheduler"]


def test_startup_does_not_initialize_bus_notice(test_db, monkeypatch):
    """Server startup should not crawl TOPIS bus notices."""
    from main import app

    mock_initialize = AsyncMock()
    monkeypatch.setattr(
        "app.services.bus_notice_service.BusNoticeService.initialize",
        mock_initialize,
    )

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    mock_initialize.assert_not_called()


def test_removed_manual_crawling_endpoints_return_404(test_client):
    """Manual crawling should be consolidated under /admin/trigger-*."""
    assert test_client.post("/bus/refresh").status_code == 404
    assert test_client.post("/scheduler/crawl-events").status_code == 404
    assert test_client.post("/scheduler/manual-test").status_code == 404
    assert test_client.post(
        "/events/crawl-and-sync",
        headers={"X-API-Key": "test-api-key"},
    ).status_code == 404
