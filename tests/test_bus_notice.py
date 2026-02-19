
import os
import sys
import asyncio
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

# Add project root to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.services.bus_notice_service import BusNoticeService
from app.routers.bus_notice import router
from fastapi import FastAPI
from app.config.settings import settings

# Mock settings
settings.GOOGLE_API_KEY = "test_key"

# Create a test app
app = FastAPI()
app.include_router(router)

client = TestClient(app)

async def test_bus_notice_service_initialization():
    print("Testing BusNoticeService initialization...")
    # Mock TOPISCrawler
    with patch("app.services.bus_logic.restricted_bus.TOPISCrawler") as MockCrawler:
        mock_instance = MockCrawler.return_value
        mock_instance.crawl_notices.return_value = ({"1": {"seq": "1", "title": "Test Notice"}}, True)
        
        await BusNoticeService.initialize()
        
        try:
            assert BusNoticeService.crawler is not None
            assert "1" in BusNoticeService.cached_notices
            assert BusNoticeService.cached_notices["1"]["title"] == "Test Notice"
            print("✅ BusNoticeService initialization passed")
        except AssertionError as e:
            print(f"❌ BusNoticeService initialization failed: {e}")

def test_get_notices_endpoint():
    print("Testing GET /bus/notices endpoint...")
    # Mock cached notices
    BusNoticeService.cached_notices = {"1": {"seq": "1", "title": "Test Notice"}}
    # Mock crawler (needed for filter_by_date)
    mock_crawler = MagicMock()
    mock_crawler.filter_by_date.return_value = [{"seq": "1", "title": "Test Notice"}]
    BusNoticeService.crawler = mock_crawler
    
    try:
        response = client.get("/bus/notices")
        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["title"] == "Test Notice"
        print("✅ GET /bus/notices passed")
    except AssertionError as e:
        print(f"❌ GET /bus/notices failed: {e}")

def test_webhook_route_check():
    print("Testing POST /bus/webhook/route_check endpoint...")
    # Mock get_route_controls to return empty list so checking text response works without complex mocks
    with patch.object(BusNoticeService, 'get_route_controls', return_value=[]):
        try:
            response = client.post("/bus/webhook/route_check", json={
                "userRequest": {},
                "action": {
                    "params": {"route_number": "100"}
                }
            })
            assert response.status_code == 200
            data = response.json()
            assert "template" in data
            print("✅ POST /bus/webhook/route_check passed")
        except AssertionError as e:
            print(f"❌ POST /bus/webhook/route_check failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_bus_notice_service_initialization())
    test_get_notices_endpoint()
    test_webhook_route_check()

