import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

@pytest.fixture
def mock_payload():
    return {
        "userRequest": {
            "user": {
                "id": "bot_user_key_123",
                "properties": {
                    "plusfriendUserKey": "plusfriend_key_123"
                }
            }
        },
        "action": {
            "params": {
                "departure": "ㄴㄴ",
                "arrival": "ㄴ네ㅔ",
                "marked_bus": "싷ㅎ어",
                "language": "가위"
            }
        }
    }

def test_initial_setup_logic_error(clean_test_db, mock_payload):
    """
    Test that invalid input (logic error) returns 200 OK with specific error message.
    """
    # Mock UserService.sync_kakao_user to avoid live DB call
    with patch("app.services.user_service.UserService.sync_kakao_user"):
        # Mock UserService.setup_user_profile to return logic failure
        with patch("app.services.user_service.UserService.setup_user_profile", new_callable=AsyncMock) as mock_setup:
            mock_setup.return_value = {"success": False, "error": "출발지를 찾을 수 없습니다"}

            response = client.post("/users/initial-setup", json=mock_payload)

            assert response.status_code == 200
            data = response.json()
            text = data["template"]["outputs"][0]["simpleText"]["text"]
            assert "출발지를 찾을 수 없습니다" in text


def test_initial_setup_system_error_in_service(clean_test_db, mock_payload):
    """
    Test that exception in Service layer is caught and returns friendly message (200 OK).
    """
    # UserService.setup_user_profile is NOT mocked here to test its internal try/except,
    # BUT we need to mock whatever it calls to raise exception.
    # However, forcing an exception inside setup_user_profile might be hard without mocking internal calls.
    # So we can mock setup_user_profile to return the error dict that UserService.setup_user_profile WOULD return.
    # wait, we modified user_service.py to catch exception and return dict.
    # So if we mock get_location_info to raise exception, UserService should catch it.
    
    with patch("app.services.user_service.get_location_info", new_callable=AsyncMock) as mock_geo:
        mock_geo.side_effect = Exception("Unexpected API Fail")
        
        # Mock sync_kakao_user as well
        with patch("app.services.user_service.UserService.sync_kakao_user"):
             response = client.post("/users/initial-setup", json=mock_payload)

             assert response.status_code == 200
             data = response.json()
             text = data["template"]["outputs"][0]["simpleText"]["text"]
             # Should be the safe message we added in user_service.py
             assert "일시적인 오류가 발생했습니다" in text

def test_initial_setup_system_error_in_router(clean_test_db, mock_payload):
    """
    Test that exception in Router layer (before Service call) is caught and returns friendly message (200 OK).
    """
    # Mock UserService.sync_kakao_user to raise exception (Router calls this before setup_user_profile)
    with patch("app.services.user_service.UserService.sync_kakao_user") as mock_sync:
        mock_sync.side_effect = Exception("DB Connection Fail")

        response = client.post("/users/initial-setup", json=mock_payload)

        assert response.status_code == 200
        data = response.json()
        text = data["template"]["outputs"][0]["simpleText"]["text"]
        # Should be the system error message we added in users.py except block
        assert "시스템 오류가 발생했습니다" in text
