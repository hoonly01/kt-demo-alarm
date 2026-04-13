import pytest
from unittest.mock import patch, AsyncMock
import sqlite3

def test_send_alarms_separates_id_types(test_client, clean_test_db):
    """plusfriendUserKey와 botUserKey 보유자에 따라 알림 발송이 2번 분리되어 호출되는지 확인하는 테스트"""
    conn = sqlite3.connect(clean_test_db)
    cursor = conn.cursor()
    try:
        # User 1: plusfriend와 bot 둘 다 있음 (plusfriend로 분류되어야 함)
        cursor.execute("INSERT INTO users (bot_user_key, plusfriend_user_key, active, is_alarm_on) VALUES ('bot1', 'pf1', 1, 1)")
        # User 2: bot_user_key만 있음 (botUserKey로 분류되어야 함)
        cursor.execute("INSERT INTO users (bot_user_key, active, is_alarm_on) VALUES ('bot2', 1, 1)")
        # User 3: 또 다른 plusfriend (plusfriend로 분류되어야 함)
        cursor.execute("INSERT INTO users (bot_user_key, plusfriend_user_key, active, is_alarm_on) VALUES ('bot3', 'pf3', 1, 1)")
        # User 4: 알림 꺼둠 (제외되어야 함)
        cursor.execute("INSERT INTO users (bot_user_key, plusfriend_user_key, active, is_alarm_on) VALUES ('bot4', 'pf4', 1, 0)")
        # User 5: 비활성화 (제외되어야 함)
        cursor.execute("INSERT INTO users (bot_user_key, plusfriend_user_key, active, is_alarm_on) VALUES ('bot5', 'pf5', 0, 1)")
        
        conn.commit()
    finally:
        conn.close()

    with patch('app.routers.alarms.NotificationService.send_bulk_alarm', new_callable=AsyncMock) as mock_send_bulk:
        mock_send_bulk.return_value = {"success": True, "total_users": 1, "total_sent": 1, "total_failed": 0}
        
        response = test_client.post(
            "/alarms/send-to-all?event_name=test_event",
            headers={"X-API-Key": "test-api-key"},
            json={}
        )
        
        assert response.status_code == 200
        
        # ID 타입별로 2번 호출되어야 합니다 (plusfriend 대상자 그룹 1번, bot_user 대상자 그룹 1번)
        assert mock_send_bulk.call_count == 2
        
        # 첫 번째 호출은 plusfriendUserKey 대상자 (pf1, pf3)
        call1_kwargs = mock_send_bulk.call_args_list[0].kwargs
        assert set(call1_kwargs['user_ids']) == {'pf1', 'pf3'}
        assert call1_kwargs['id_type'] == "plusfriendUserKey"
        
        # 두 번째 호출은 botUserKey 대상자 (bot2)
        call2_kwargs = mock_send_bulk.call_args_list[1].kwargs
        assert set(call2_kwargs['user_ids']) == {'bot2'}
        assert call2_kwargs['id_type'] == "botUserKey"


def test_send_alarms_to_all_404_when_empty(test_client, clean_test_db):
    """발송 대상자가 한 명도 없을 때 500 에러를 뿜지 않고 404를 잘 반환하는지 확인하는 테스트"""
    # DB가 비어있는 상태에서 바로 호출
    response = test_client.post(
        "/alarms/send-to-all?event_name=test_event",
        headers={"X-API-Key": "test-api-key"},
        json={}
    )
    
    assert response.status_code == 404
    assert response.json()["detail"] == "활성 사용자가 없습니다"


def test_send_filtered_alarms_404_when_empty(test_client, clean_test_db):
    """필터링 된 발송 대상자가 한 명도 없을 때 404를 잘 반환하는지 확인하는 테스트"""
    conn = sqlite3.connect(clean_test_db)
    cursor = conn.cursor()
    try:
        # 사용자는 있지만 필터 조건(location)에 맞는 사용자가 없는 상황 구성
        cursor.execute("INSERT INTO users (bot_user_key, plusfriend_user_key, location, active, is_alarm_on) VALUES ('bot1', 'pf1', '부산광역시', 1, 1)")
        conn.commit()
    finally:
        conn.close()
    
    response = test_client.post(
        "/alarms/send-filtered",
        headers={"X-API-Key": "test-api-key"},
        json={"filter_location": "서울특별시", "event_name": "test", "data": {}}
    )
    
    assert response.status_code == 404
    assert response.json()["detail"] == "조건에 맞는 사용자가 없습니다"
