
import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

# Add project root to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.services.bus_notice_service import BusNoticeService
from app.routers.bus_notice import router
from fastapi import FastAPI
from app.config.settings import settings

# Create a test app
app = FastAPI()
app.include_router(router)

client = TestClient(app)


@pytest.mark.asyncio
async def test_bus_notice_service_initialization(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test_key")
    print("Testing BusNoticeService initialization...")
    # Mock TOPISCrawler
    with patch("app.services.bus_notice_service.TOPISCrawler") as MockCrawler:
        mock_instance = MockCrawler.return_value
        mock_instance.crawl_notices.return_value = ({"1": {"seq": "1", "title": "Test Notice"}}, True)

        await BusNoticeService.initialize()

        assert BusNoticeService.crawler is not None
        assert "1" in BusNoticeService.cached_notices
        assert BusNoticeService.cached_notices["1"]["title"] == "Test Notice"


@pytest.mark.asyncio
async def test_bus_notice_service_refresh(monkeypatch):
    """refresh()가 크롤러를 재호출하고 캐시를 갱신하는지 검증"""
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test_key")
    with patch("app.services.bus_notice_service.TOPISCrawler") as MockCrawler:
        mock_instance = MockCrawler.return_value
        mock_instance.crawl_notices.return_value = (
            {"2": {"seq": "2", "title": "갱신된 공지"}}, True
        )
        # 이미 초기화된 상태 모사
        monkeypatch.setattr(BusNoticeService, "crawler", mock_instance)
        monkeypatch.setattr(BusNoticeService, "cached_notices", {"1": {"seq": "1", "title": "기존 공지"}})

        with patch.object(BusNoticeService, "generate_all_route_images", new_callable=AsyncMock):
            await BusNoticeService.refresh()

        assert "2" in BusNoticeService.cached_notices
        assert BusNoticeService.cached_notices["2"]["title"] == "갱신된 공지"
        assert BusNoticeService.last_update is not None
        mock_instance.crawl_notices.assert_called_once()


@pytest.mark.asyncio
async def test_bus_notice_service_refresh_without_crawler(monkeypatch):
    """크롤러가 초기화되지 않은 상태에서 refresh()를 호출해도 예외가 발생하지 않는지 검증"""
    monkeypatch.setattr(BusNoticeService, "crawler", None)
    # 예외 없이 조기 반환되어야 함
    await BusNoticeService.refresh()


def test_get_notices_endpoint():
    print("Testing GET /bus/notices endpoint...")
    # Mock cached notices
    BusNoticeService.cached_notices = {"1": {"seq": "1", "title": "Test Notice"}}
    # Mock crawler (needed for filter_by_date)
    mock_crawler = MagicMock()
    mock_crawler.filter_by_date.return_value = [{"seq": "1", "title": "Test Notice"}]
    BusNoticeService.crawler = mock_crawler

    response = client.get("/bus/notices")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["title"] == "Test Notice"


def test_webhook_route_check():
    print("Testing POST /bus/webhook/route_check endpoint...")
    with patch.object(BusNoticeService, 'get_route_controls', return_value=[]):
        response = client.post("/bus/webhook/route_check", json={
            "userRequest": {},
            "action": {
                "params": {"route_number": "100"}
            }
        })
        assert response.status_code == 200
        data = response.json()
        assert "template" in data
