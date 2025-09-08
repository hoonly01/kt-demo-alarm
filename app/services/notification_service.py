"""알림 전송 서비스"""
import logging
import httpx
import json
import os
from typing import List, Dict, Any, Optional
from app.models.alarm import AlarmRequest, FilteredAlarmRequest
from app.models.kakao import EventAPIRequest, EventData, EventUser

logger = logging.getLogger(__name__)

# 환경변수에서 카카오 설정 로드
BOT_ID = os.getenv("BOT_ID")


class NotificationService:
    """알림 전송 비즈니스 로직"""

    @staticmethod
    async def send_individual_alarm(alarm_request: AlarmRequest) -> Dict[str, Any]:
        """
        개별 사용자에게 알림 전송
        
        Args:
            alarm_request: 알림 요청 데이터
            
        Returns:
            Dict: 전송 결과
        """
        if not BOT_ID:
            return {"success": False, "error": "BOT_ID가 설정되지 않았습니다"}
        
        try:
            event_api_request = EventAPIRequest(
                botId=BOT_ID,
                event=EventData(
                    name=alarm_request.event_name,
                    data=alarm_request.data
                ),
                user=EventUser(
                    type="botUserKey",
                    id=alarm_request.user_id
                )
            )
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://bot-api.kakao.com/v1/bots/message/send",
                    json=event_api_request.model_dump(),
                    headers={"Content-Type": "application/json"},
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    logger.info(f"개별 알림 전송 성공: {alarm_request.user_id}")
                    return {"success": True, "response": response.json()}
                else:
                    logger.error(f"개별 알림 전송 실패: {response.status_code} - {response.text}")
                    return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
                    
        except Exception as e:
            logger.error(f"개별 알림 전송 중 오류: {str(e)}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def send_bulk_alarm(
        user_ids: List[str], 
        event_name: str, 
        data: Dict[str, Any],
        batch_size: int = 100
    ) -> Dict[str, Any]:
        """
        대량 사용자에게 배치 알림 전송
        
        Args:
            user_ids: 사용자 ID 목록
            event_name: 이벤트 이름
            data: 전송 데이터
            batch_size: 배치 크기
            
        Returns:
            Dict: 전송 결과
        """
        if not BOT_ID:
            return {"success": False, "error": "BOT_ID가 설정되지 않았습니다"}
        
        try:
            success_count = 0
            fail_count = 0
            
            # 배치 단위로 처리
            for i in range(0, len(user_ids), batch_size):
                batch_users = user_ids[i:i + batch_size]
                
                for user_id in batch_users:
                    try:
                        alarm_request = AlarmRequest(
                            user_id=user_id,
                            event_name=event_name,
                            data=data
                        )
                        
                        result = await NotificationService.send_individual_alarm(alarm_request)
                        
                        if result.get("success"):
                            success_count += 1
                        else:
                            fail_count += 1
                            
                    except Exception as e:
                        logger.error(f"사용자 {user_id} 알림 전송 실패: {str(e)}")
                        fail_count += 1
            
            logger.info(f"대량 알림 전송 완료: 성공 {success_count}건, 실패 {fail_count}건")
            
            return {
                "success": True,
                "total_sent": success_count,
                "total_failed": fail_count,
                "total_users": len(user_ids)
            }
            
        except Exception as e:
            logger.error(f"대량 알림 전송 중 오류: {str(e)}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def send_route_alert(user_id: str, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        경로 기반 집회 알림 전송
        
        Args:
            user_id: 사용자 ID
            events: 감지된 집회 목록
            
        Returns:
            Dict: 전송 결과
        """
        if not events:
            return {"success": False, "error": "전송할 집회 정보가 없습니다"}
        
        # 집회 정보를 알림 메시지로 구성
        event_messages = []
        for event in events:
            severity_emoji = "🔴" if event.get("severity_level", 1) >= 3 else "🟡" if event.get("severity_level", 1) >= 2 else "🟢"
            
            event_messages.append(
                f"{severity_emoji} {event['title']}\n"
                f"📍 {event['location']}\n"
                f"⏰ {event['start_date']}\n"
                f"🏷️ {event.get('category', '일반')}"
            )
        
        message_text = f"⚠️ 경로상에 {len(events)}개의 집회가 감지되었습니다:\n\n" + "\n\n".join(event_messages)
        
        # 알림 전송
        alarm_request = AlarmRequest(
            user_id=user_id,
            event_name="route_rally_alert",
            data={
                "message": message_text,
                "events_count": len(events),
                "events": events
            }
        )
        
        return await NotificationService.send_individual_alarm(alarm_request)

    @staticmethod
    def validate_event_data(event_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        이벤트 데이터 검증
        
        Args:
            event_name: 이벤트 이름
            data: 이벤트 데이터
            
        Returns:
            Dict: 검증 결과
        """
        if not event_name:
            return {"valid": False, "error": "이벤트 이름이 필요합니다"}
        
        if not isinstance(data, dict):
            return {"valid": False, "error": "데이터는 딕셔너리 형태여야 합니다"}
        
        # 필수 필드 확인 (이벤트 이름별로 다를 수 있음)
        if event_name == "route_rally_alert":
            if "message" not in data:
                return {"valid": False, "error": "message 필드가 필요합니다"}
        
        return {"valid": True}