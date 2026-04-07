"""알림 전송 서비스"""
import asyncio
import logging
import httpx
import json
from typing import List, Dict, Any, Optional
from app.models.alarm import AlarmRequest, FilteredAlarmRequest
from app.models.kakao import EventAPIRequest, Event, EventUser
from app.config.settings import settings

logger = logging.getLogger(__name__)


class NotificationService:
    """알림 전송 비즈니스 로직"""

    @staticmethod
    def _format_event_message(events: List[Dict[str, Any]]) -> str:
        """
        집회 정보를 텍스트 메시지로 포맷팅
        
        Args:
            events: 집회 정보 목록
            
        Returns:
            str: 포맷팅된 메시지 텍스트
        """
        event_messages = []
        for event in events:
            severity_level = event.get("severity_level", 1)
            severity_emoji = "🔴" if severity_level >= 3 else "🟡" if severity_level >= 2 else "🟢"

            event_messages.append(
                f"{severity_emoji} {event['title']}\n"
                f"📍 {event['location']}\n"
                f"⏰ {event['start_date']}\n"
                f"🏷️ {event.get('category', '일반')}"
            )

        return f"⚠️ 경로상에 {len(events)}개의 집회가 감지되었습니다:\n\n" + "\n\n".join(event_messages)

    @staticmethod
    async def send_individual_alarm(
        alarm_request: AlarmRequest, 
        id_type: str = "plusfriendUserKey",
        client: Optional[httpx.AsyncClient] = None
    ) -> Dict[str, Any]:
        """
        개별 사용자에게 알림 전송
        
        Args:
            alarm_request: 알림 요청 데이터
            id_type: 사용자 ID 타입 (plusfriendUserKey, botUserKey, appUserId)
            client: 재사용할 HTTP 클라이언트 (Optional)
            
        Returns:
            Dict: 전송 결과
        """
        if not settings.BOT_ID:
            return {"success": False, "error": "BOT_ID가 설정되지 않았습니다"}

        try:
            event_api_request = EventAPIRequest(
                botId=settings.BOT_ID,
                event=Event(
                    name=alarm_request.event_name,
                    data=alarm_request.data
                ),
                user=EventUser(
                    type=id_type,  # ← plusfriendUserKey 사용 (기본값)
                    id=alarm_request.user_id
                )
            )
            
            # 클라이언트 컨텍스트 관리
            if client:
                response = await client.post(
                    settings.KAKAO_BOT_API_URL,
                    json=event_api_request.model_dump(),
                    headers={"Content-Type": "application/json"},
                    timeout=settings.NOTIFICATION_TIMEOUT
                )
                return NotificationService._process_response(response, alarm_request.user_id)
            else:
                async with httpx.AsyncClient() as new_client:
                    response = await new_client.post(
                        settings.KAKAO_BOT_API_URL,
                        json=event_api_request.model_dump(),
                        headers={"Content-Type": "application/json"},
                        timeout=settings.NOTIFICATION_TIMEOUT
                    )
                    return NotificationService._process_response(response, alarm_request.user_id)
                    
        except Exception as e:
            logger.error(f"개별 알림 전송 중 오류: {str(e)}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def _process_response(response: httpx.Response, user_id: str) -> Dict[str, Any]:
        """HTTP 응답 처리 헬퍼"""
        if response.status_code == 200:
            logger.info(f"개별 알림 전송 성공: {user_id}")
            return {"success": True, "response": response.json()}
        else:
            logger.error(f"개별 알림 전송 실패: {response.status_code} - {response.text}")
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}

    @staticmethod
    async def send_bulk_alarm(
        user_ids: List[str],
        event_name: str,
        data: Dict[str, Any],
        batch_size: int = 100,  # settings.BATCH_SIZE를 기본값으로 사용하고 싶지만 staticmethod라 인자 기본값에 접근 주의
        id_type: str = "plusfriendUserKey"
    ) -> Dict[str, Any]:
        """
        대량 사용자에게 배치 알림 전송 (HTTP 세션 재사용)
        
        Args:
            user_ids: 사용자 ID 목록
            event_name: 이벤트 이름
            data: 전송 데이터
            batch_size: 배치 크기
            id_type: 사용자 ID 타입
            
        Returns:
            Dict: 전송 결과
        """
        if not settings.BOT_ID:
            return {"success": False, "error": "BOT_ID가 설정되지 않았습니다"}

        actual_batch_size = batch_size if batch_size > 0 else settings.BATCH_SIZE

        try:
            success_count = 0
            fail_count = 0

            # 하나의 세션을 생성하여 모든 요청에 재사용
            async with httpx.AsyncClient() as client:
                # 내부 헬퍼 함수 - 세션과 파라미터 캡처
                async def send_to_user(user_id: str) -> Dict[str, Any]:
                    try:
                        alarm_request = AlarmRequest(
                            user_id=user_id,
                            event_name=event_name,
                            data=data
                        )
                        return await NotificationService.send_individual_alarm(
                            alarm_request, 
                            id_type=id_type,
                            client=client
                        )
                    except Exception as e:
                        logger.error(f"사용자 {user_id} 알림 전송 실패: {str(e)}")
                        return {"success": False, "error": str(e)}

                # 배치 단위로 처리
                for i in range(0, len(user_ids), actual_batch_size):
                    batch_users = user_ids[i:i + actual_batch_size]
                    
                    # 배치 내 모든 작업을 동시에 실행
                    batch_tasks = [send_to_user(user_id) for user_id in batch_users]
                    batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
                    
                    # 결과 집계
                    batch_success = 0
                    for result in batch_results:
                        if isinstance(result, Exception):
                            fail_count += 1
                        elif result.get("success"):
                            batch_success += 1
                            success_count += 1
                        else:
                            fail_count += 1
                    
                    logger.info(f"배치 {i//actual_batch_size + 1} 완료: 성공 {batch_success}/{len(batch_users)}")
            
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
    async def send_route_alert(user_id: str, events: List[Dict[str, Any]], id_type: str = "plusfriendUserKey") -> Dict[str, Any]:
        """경로 기반 집회 알림 전송"""
        if not events:
            return {"success": False, "error": "전송할 집회 정보가 없습니다"}

        message_text = NotificationService._format_event_message(events)

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

        return await NotificationService.send_individual_alarm(alarm_request, id_type=id_type)

    @staticmethod
    async def send_bulk_alert(
        user_ids: List[str],
        events_data: List[Dict[str, Any]],
        id_type: str = "plusfriendUserKey"
    ) -> Dict[str, Any]:
        """조건부 일괄 알림 전송"""
        if not user_ids:
            return {"success": False, "error": "수신자가 없습니다"}

        message_text = NotificationService._format_event_message(events_data)

        # Event API로 일괄 전송
        return await NotificationService.send_bulk_alarm(
            user_ids=user_ids,
            event_name="route_rally_alert",
            data={
                "message": message_text,
                "events_count": len(events_data),
                "events": events_data
            },
            id_type=id_type
        )

    @staticmethod
    def validate_event_data(event_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """이벤트 데이터 검증"""
        if not event_name:
            return {"valid": False, "error": "이벤트 이름이 필요합니다"}
        
        if not isinstance(data, dict):
            return {"valid": False, "error": "데이터는 딕셔너리 형태여야 합니다"}
        
        # 필수 필드 확인 (이벤트 이름별로 다를 수 있음)
        if event_name == "route_rally_alert":
            if "message" not in data:
                return {"valid": False, "error": "message 필드가 필요합니다"}
        
        return {"valid": True}