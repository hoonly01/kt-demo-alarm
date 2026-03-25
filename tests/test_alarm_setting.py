"""알람 On/Off 설정 기능 테스트"""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


@pytest.fixture
def alarm_save_payload():
    """알람 설정 저장 요청 기본 payload"""
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
                "alarm_status": "on"
            }
        }
    }


@pytest.fixture
def alarm_select_payload():
    """알람 설정 선택 UI 요청 기본 payload"""
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


class TestAlarmSettingSelectionUI:
    """알람 설정 선택 UI (ListCard) 반환 테스트"""

    def test_alarm_setting_selection_ui(self, alarm_select_payload):
        """ListCard 형식으로 2개 옵션이 반환되는지 확인"""
        response = client.post("/alarm-setting", json=alarm_select_payload)

        assert response.status_code == 200
        data = response.json()

        # ListCard 존재 확인
        output = data["template"]["outputs"][0]
        assert "listCard" in output

        list_card = output["listCard"]

        # 헤더 확인
        assert "알림 설정" in list_card["header"]["title"]

        # 아이템 2개 확인 (켜기 + 끄기)
        items = list_card["items"]
        assert len(items) == 2

        # 각 아이템에 action: message 확인
        for item in items:
            assert item["action"] == "message"
            assert "messageText" in item

        # 옵션 이름 확인
        titles = [item["title"] for item in items]
        assert any("켜기" in t for t in titles)
        assert any("끄기" in t for t in titles)


class TestAlarmSettingSave:
    """알람 설정 저장 테스트"""

    def test_save_alarm_on_success(self, clean_test_db, alarm_save_payload):
        """알림 켜기 선택 시 성공 메시지 반환"""
        alarm_save_payload["action"]["params"]["alarm_status"] = "on"

        with patch("app.services.user_service.UserService.sync_kakao_user"):
            with patch("app.services.user_service.UserService.update_alarm_setting") as mock_update:
                mock_update.return_value = {"success": True}

                response = client.post("/alarm-setting/save", json=alarm_save_payload)

                assert response.status_code == 200
                data = response.json()
                text = data["template"]["outputs"][0]["simpleText"]["text"]
                assert "켜졌습니다" in text

                # update_alarm_setting이 is_alarm_on=True로 호출됐는지 확인
                mock_update.assert_called_once()
                call_args = mock_update.call_args
                assert call_args[0][1] is True  # is_alarm_on value

    def test_save_alarm_off_success(self, clean_test_db, alarm_save_payload):
        """알림 끄기 선택 시 성공 메시지 반환"""
        alarm_save_payload["action"]["params"]["alarm_status"] = "off"

        with patch("app.services.user_service.UserService.sync_kakao_user"):
            with patch("app.services.user_service.UserService.update_alarm_setting") as mock_update:
                mock_update.return_value = {"success": True}

                response = client.post("/alarm-setting/save", json=alarm_save_payload)

                assert response.status_code == 200
                data = response.json()
                text = data["template"]["outputs"][0]["simpleText"]["text"]
                assert "꺼졌습니다" in text

                # update_alarm_setting이 is_alarm_on=False로 호출됐는지 확인
                mock_update.assert_called_once()
                call_args = mock_update.call_args
                assert call_args[0][1] is False  # is_alarm_on value

    def test_save_invalid_alarm_status(self, clean_test_db, alarm_save_payload):
        """잘못된 알림 설정 값 입력 시 에러 메시지 반환"""
        alarm_save_payload["action"]["params"]["alarm_status"] = "maybe"

        response = client.post("/alarm-setting/save", json=alarm_save_payload)

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
                    "alarm_status": "on"
                }
            }
        }

        response = client.post("/alarm-setting/save", json=payload)

        assert response.status_code == 200
        data = response.json()
        text = data["template"]["outputs"][0]["simpleText"]["text"]
        assert "사용자 식별 정보" in text

    def test_save_system_error(self, clean_test_db, alarm_save_payload):
        """시스템 오류 시 에러 메시지 반환"""
        with patch("app.services.user_service.UserService.sync_kakao_user") as mock_sync:
            mock_sync.side_effect = Exception("DB Connection Fail")

            response = client.post("/alarm-setting/save", json=alarm_save_payload)

            assert response.status_code == 200
            data = response.json()
            text = data["template"]["outputs"][0]["simpleText"]["text"]
            assert "시스템 오류" in text
