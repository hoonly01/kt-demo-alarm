"""이동경로 2단계 UI 기능 테스트"""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


@pytest.fixture
def route_select_payload():
    """이동경로 관리 선택 UI 요청 기본 payload"""
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
            "params": {}
        }
    }


@pytest.fixture
def route_delete_payload():
    """이동경로 삭제 요청 기본 payload"""
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
            "params": {}
        }
    }


class TestRouteSettingSelectionUI:
    """이동경로 선택 UI (ListCard) 반환 테스트"""

    def test_route_setting_selection_ui(self, route_select_payload):
        """ListCard 형식으로 설정/삭제 2개 항목이 반환되는지 확인"""
        response = client.post("/route-setting", json=route_select_payload)

        assert response.status_code == 200
        data = response.json()

        output = data["template"]["outputs"][0]
        assert "listCard" in output

        list_card = output["listCard"]
        assert "출퇴근 경로" in list_card["header"]["title"]

        items = list_card["items"]
        assert len(items) == 2

        # 각 아이템에 action: block+blockId 또는 message+messageText 확인
        for item in items:
            assert item["action"] in ("message", "block")
            if item["action"] == "block":
                assert "blockId" in item
            else:
                assert "messageText" in item

        titles = [item["title"] for item in items]
        assert any("설정" in t for t in titles)
        assert any("삭제" in t for t in titles)


class TestRouteSettingDelete:
    """이동경로 삭제 처리 테스트"""

    def test_delete_route_success(self, clean_test_db, route_delete_payload):
        """삭제 성공 시 완료 메시지 반환"""
        with patch("app.services.user_service.UserService.sync_kakao_user"):
            with patch("app.services.user_service.UserService.delete_user_route") as mock_delete:
                mock_delete.return_value = {"success": True}

                response = client.post("/route-setting/delete", json=route_delete_payload)

                assert response.status_code == 200
                data = response.json()
                text = data["template"]["outputs"][0]["simpleText"]["text"]
                assert "삭제" in text

                mock_delete.assert_called_once()

    def test_delete_no_user_id(self, clean_test_db):
        """사용자 식별 정보 누락 시 에러 반환"""
        payload = {
            "userRequest": {
                "user": {
                    "id": None,
                    "properties": {}
                }
            },
            "action": {"params": {}}
        }

        response = client.post("/route-setting/delete", json=payload)

        assert response.status_code == 200
        data = response.json()
        text = data["template"]["outputs"][0]["simpleText"]["text"]
        assert "사용자 식별 정보" in text

    def test_delete_system_error(self, clean_test_db, route_delete_payload):
        """시스템 오류 시 에러 메시지 반환"""
        with patch("app.services.user_service.UserService.sync_kakao_user") as mock_sync:
            mock_sync.side_effect = Exception("DB Connection Fail")

            response = client.post("/route-setting/delete", json=route_delete_payload)

            assert response.status_code == 200
            data = response.json()
            text = data["template"]["outputs"][0]["simpleText"]["text"]
            assert "시스템 오류" in text
