
import os
import sys
import pytest
from unittest.mock import MagicMock, patch
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
