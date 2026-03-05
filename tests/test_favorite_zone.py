"""관심장소 알림 설정 기능 테스트"""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


@pytest.fixture
def zone_save_payload():
    """관심장소 저장 요청 기본 payload"""
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
                "zone": "1구역"
            }
        }
    }


@pytest.fixture
def zone_select_payload():
    """관심장소 선택 UI 요청 기본 payload"""
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


class TestFavoriteZoneSelectionUI:
    """관심장소 선택 UI (ListCard) 반환 테스트"""

    def test_favorite_zone_selection_ui(self, zone_select_payload):
        """ListCard 형식으로 4개 구역 옵션이 반환되는지 확인"""
        response = client.post("/favorite-zone", json=zone_select_payload)

        assert response.status_code == 200
        data = response.json()

        # ListCard 존재 확인
        output = data["template"]["outputs"][0]
        assert "listCard" in output

        list_card = output["listCard"]

        # 헤더 확인
        assert "관심장소" in list_card["header"]["title"]

        # 아이템 4개 확인 (3 구역 + 미설정)
        items = list_card["items"]
        assert len(items) == 4

        # 각 아이템에 action: message 확인
        for item in items:
            assert item["action"] == "message"
            assert "messageText" in item

        # 구역 이름 확인
        titles = [item["title"] for item in items]
        assert "1구역" in titles
        assert "2구역" in titles
        assert "3구역" in titles
        assert "미설정" in titles


class TestFavoriteZoneSave:
    """관심장소 구역 저장 테스트"""

    def test_save_zone1_success(self, clean_test_db, zone_save_payload):
        """1구역 선택 시 성공 메시지 반환"""
        zone_save_payload["action"]["params"]["zone"] = "1구역"

        with patch("app.services.user_service.UserService.sync_kakao_user"):
            with patch("app.services.user_service.UserService.update_favorite_zone") as mock_update:
                mock_update.return_value = {"success": True}

                response = client.post("/favorite-zone/save", json=zone_save_payload)

                assert response.status_code == 200
                data = response.json()
                text = data["template"]["outputs"][0]["simpleText"]["text"]
                assert "1구역" in text
                assert "설정되었습니다" in text

                # update_favorite_zone이 zone=1로 호출됐는지 확인
                mock_update.assert_called_once()
                call_args = mock_update.call_args
                assert call_args[0][1] == 1  # zone value

    def test_save_zone_unset(self, clean_test_db, zone_save_payload):
        """미설정 선택 시 삭제 확인 메시지 반환"""
        zone_save_payload["action"]["params"]["zone"] = "미설정"

        with patch("app.services.user_service.UserService.sync_kakao_user"):
            with patch("app.services.user_service.UserService.update_favorite_zone") as mock_update:
                mock_update.return_value = {"success": True}

                response = client.post("/favorite-zone/save", json=zone_save_payload)

                assert response.status_code == 200
                data = response.json()
                text = data["template"]["outputs"][0]["simpleText"]["text"]
                assert "해제" in text

                # update_favorite_zone이 zone=None으로 호출됐는지 확인
                mock_update.assert_called_once()
                call_args = mock_update.call_args
                assert call_args[0][1] is None  # zone value

    def test_save_invalid_zone(self, clean_test_db, zone_save_payload):
        """잘못된 구역 값 입력 시 에러 메시지 반환"""
        zone_save_payload["action"]["params"]["zone"] = "5구역"

        response = client.post("/favorite-zone/save", json=zone_save_payload)

        assert response.status_code == 200
        data = response.json()
        text = data["template"]["outputs"][0]["simpleText"]["text"]
        assert "올바르지 않은" in text

    def test_save_no_user_id(self, clean_test_db):
        """사용자 식별 정보 누락 시 에러 반환"""
        payload = {
            "userRequest": {
                "user": {
                    "id": None,
                    "properties": {}
                }
            },
            "action": {
                "params": {
                    "zone": "1구역"
                }
            }
        }

        response = client.post("/favorite-zone/save", json=payload)

        assert response.status_code == 200
        data = response.json()
        text = data["template"]["outputs"][0]["simpleText"]["text"]
        assert "사용자 식별 정보" in text

    def test_save_system_error(self, clean_test_db, zone_save_payload):
        """시스템 오류 시 에러 메시지 반환"""
        with patch("app.services.user_service.UserService.sync_kakao_user") as mock_sync:
            mock_sync.side_effect = Exception("DB Connection Fail")

            response = client.post("/favorite-zone/save", json=zone_save_payload)

            assert response.status_code == 200
            data = response.json()
            text = data["template"]["outputs"][0]["simpleText"]["text"]
            assert "시스템 오류" in text
