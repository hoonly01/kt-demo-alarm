"""알림 전송 서비스"""
import asyncio
import logging
import httpx
from datetime import datetime
from typing import List, Dict, Any, Optional, Iterator, Tuple
from app.models.alarm import AlarmRequest, FilteredAlarmRequest
from app.models.kakao import EventAPIRequest, Event, EventUser
from app.config.settings import settings

logger = logging.getLogger(__name__)

KAKAO_BOT_API_BASE_URL = "https://bot-api.kakao.com"
KAKAO_EVENT_API_MAX_USERS_PER_REQUEST = 100
KAKAO_EVENT_API_SUCCESS_STATUS = "SUCCESS"
KAKAO_TASK_RESULT_POLL_ATTEMPTS = 5
KAKAO_TASK_RESULT_POLL_DELAY_SECONDS = 0.5
KAKAO_TASK_PENDING_STATUSES = {"PENDING", "PROCESSING", "RUNNING", "WAITING"}


class NotificationService:
    """알림 전송 비즈니스 로직"""

    @staticmethod
    def _kakao_event_headers() -> Dict[str, str]:
        """카카오 Event API 공통 요청 헤더"""
        return {
            "Content-Type": "application/json",
            "Authorization": f"KakaoAK {settings.KAKAO_EVENT_API_KEY}",
        }

    @staticmethod
    def _kakao_talk_url() -> str:
        """카카오 Event API 이벤트 블록 호출 URL"""
        return f"{KAKAO_BOT_API_BASE_URL}/v2/bots/{settings.BOT_ID}/talk"

    @staticmethod
    def _kakao_task_url(task_id: str) -> str:
        """카카오 Event API 발송 결과 조회 URL"""
        return f"{KAKAO_BOT_API_BASE_URL}/v1/tasks/{task_id}"

    @staticmethod
    def _format_event_time(value: Any) -> str:
        """집회 일시 표시용 HH:MM 포맷 변환"""
        if value is None:
            return "미정"

        if isinstance(value, datetime):
            return value.strftime("%H:%M")

        value_text = str(value).strip()
        if not value_text:
            return "미정"

        try:
            return datetime.fromisoformat(value_text).strftime("%H:%M")
        except ValueError:
            return value_text[:5] if len(value_text) >= 5 else value_text

    @staticmethod
    def _format_event_time_range(event: Dict[str, Any]) -> str:
        """집회 시작/종료 일시 범위 포맷팅"""
        start_time = NotificationService._format_event_time(event.get("start_date"))
        end_time = NotificationService._format_event_time(event.get("end_date"))
        return f"{start_time} ~ {end_time}"

    @staticmethod
    def _format_event_block(index: int, event: Dict[str, Any]) -> str:
        """단일 집회 정보를 사용자 알림용 번호 블록으로 포맷팅"""
        attendees = str(event.get("attendees") or "").strip() or "미상"
        return (
            f"{index}.\n"
            f"집회 일시 : {NotificationService._format_event_time_range(event)}\n"
            f"집회 장소 : {event['location']}\n"
            f"신고 인원 : {attendees}"
        )

    @staticmethod
    def _format_event_collection_message(header: str, events: List[Dict[str, Any]]) -> str:
        """여러 집회 정보를 공통 번호형 템플릿으로 포맷팅"""
        blocks = [
            NotificationService._format_event_block(index, event)
            for index, event in enumerate(events, start=1)
        ]
        return f"{header}\n\n" + "\n\n".join(blocks)

    @staticmethod
    def _format_event_message(events: List[Dict[str, Any]]) -> str:
        """
        집회 정보를 텍스트 메시지로 포맷팅

        Args:
            events: 집회 정보 목록

        Returns:
            str: 포맷팅된 메시지 텍스트
        """
        return NotificationService._format_event_collection_message(
            "경로상 감지된 집회 안내입니다.",
            events,
        )

    @staticmethod
    def _format_zone_message(zone_name: str, events: List[Dict[str, Any]]) -> str:
        """
        구역 기반 집회 알림 메시지 포맷팅

        Args:
            zone_name: 구역 이름 (예: "광화문광장(1구역)")
            events: 집회 정보 목록

        Returns:
            str: 포맷팅된 메시지 텍스트
        """
        return NotificationService._format_event_collection_message(
            f"설정하신 {zone_name}의 집회 안내입니다.",
            events,
        )

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
        if not settings.KAKAO_EVENT_API_KEY:
            return {"success": False, "error": "KAKAO_EVENT_API_KEY가 설정되지 않았습니다"}

        try:
            event_api_request = EventAPIRequest(
                event=Event(
                    name=alarm_request.event_name,
                    data=alarm_request.data
                ),
                user=[EventUser(
                    type=id_type,
                    id=alarm_request.user_id
                )],
                params=None
            )

            url = NotificationService._kakao_talk_url()
            headers = NotificationService._kakao_event_headers()

            if client is None:
                async with httpx.AsyncClient() as new_client:
                    response = await new_client.post(
                        url,
                        json=event_api_request.model_dump(),
                        headers=headers,
                        timeout=settings.NOTIFICATION_TIMEOUT
                    )
                    return NotificationService._process_response(response, alarm_request.user_id)

            response = await client.post(
                url,
                json=event_api_request.model_dump(),
                headers=headers,
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
        batch_size: Optional[int] = None,
        id_type: str = "plusfriendUserKey",
        client: Optional[httpx.AsyncClient] = None
    ) -> Dict[str, Any]:
        """
        대량 사용자에게 카카오 Event API 배치 알림 전송
        
        Args:
            user_ids: 사용자 ID 목록
            event_name: 이벤트 이름
            data: 전송 데이터
            batch_size: 배치 크기
            id_type: 사용자 ID 타입
            client: 재사용할 HTTP 클라이언트 (Optional)
            
        Returns:
            Dict: 전송 결과
        """
        if not settings.BOT_ID:
            return {"success": False, "error": "BOT_ID가 설정되지 않았습니다"}
        if not settings.KAKAO_EVENT_API_KEY:
            return {"success": False, "error": "KAKAO_EVENT_API_KEY가 설정되지 않았습니다"}

        actual_batch_size = NotificationService._effective_bulk_batch_size(batch_size)

        try:
            success_count = 0
            fail_count = 0

            async def process_batches(active_client: httpx.AsyncClient) -> None:
                nonlocal success_count, fail_count
                for batch_index, batch_users in enumerate(
                    NotificationService._iter_event_api_batches(user_ids, id_type, actual_batch_size),
                    start=1
                ):
                    sent, failed = await NotificationService._send_event_api_batch(
                        client=active_client,
                        batch_users=batch_users,
                        event_name=event_name,
                        data=data
                    )
                    success_count += sent
                    fail_count += failed
                    logger.info(
                        f"배치 {batch_index} 완료: 성공 {sent}/{len(batch_users)}, 실패 {failed}/{len(batch_users)}"
                    )

            if client is None:
                async with httpx.AsyncClient() as new_client:
                    await process_batches(new_client)
            else:
                await process_batches(client)
            
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
    def _effective_bulk_batch_size(batch_size: Optional[int]) -> int:
        """설정값과 카카오 API 제한을 반영한 실제 배치 크기"""
        configured_size = settings.BATCH_SIZE if batch_size is None or batch_size <= 0 else batch_size
        return max(1, min(configured_size, KAKAO_EVENT_API_MAX_USERS_PER_REQUEST))

    @staticmethod
    def _iter_event_api_batches(
        user_ids: List[str],
        id_type: str,
        batch_size: int
    ) -> Iterator[List[EventUser]]:
        """요청 내 중복 없이 건수를 보존하고 가능한 한 채운 Event API 배치 생성"""
        batches: List[Tuple[List[EventUser], set[Tuple[str, str]]]] = []
        for user_id in user_ids:
            user_key = (id_type, user_id)

            for batch, seen_in_batch in batches:
                if len(batch) < batch_size and user_key not in seen_in_batch:
                    batch.append(EventUser(type=id_type, id=user_id))
                    seen_in_batch.add(user_key)
                    break
            else:
                batches.append(
                    ([EventUser(type=id_type, id=user_id)], {user_key})
                )

        for batch, _ in batches:
            yield batch

    @staticmethod
    def _build_event_api_request(
        batch_users: List[EventUser],
        event_name: str,
        data: Dict[str, Any]
    ) -> EventAPIRequest:
        """카카오 Event API 요청 모델 생성"""
        return EventAPIRequest(
            event=Event(name=event_name, data=data),
            user=batch_users,
            params=None
        )

    @staticmethod
    async def _send_event_api_batch(
        client: httpx.AsyncClient,
        batch_users: List[EventUser],
        event_name: str,
        data: Dict[str, Any]
    ) -> Tuple[int, int]:
        """단일 Event API 배치 POST 후 task 결과를 조회해 성공/실패 건수를 반환"""
        batch_size = len(batch_users)
        event_api_request = NotificationService._build_event_api_request(
            batch_users=batch_users,
            event_name=event_name,
            data=data
        )

        try:
            post_response = await client.post(
                NotificationService._kakao_talk_url(),
                json=event_api_request.model_dump(),
                headers=NotificationService._kakao_event_headers(),
                timeout=settings.NOTIFICATION_TIMEOUT
            )
        except httpx.HTTPError as e:
            logger.error(f"카카오 Event API 배치 POST 실패: batch_size={batch_size}, reason={str(e)}")
            return 0, batch_size

        if post_response.status_code != 200:
            logger.error(
                f"카카오 Event API 배치 POST HTTP 실패: status={post_response.status_code}, "
                f"batch_size={batch_size}"
            )
            return 0, batch_size

        try:
            post_payload = post_response.json()
        except ValueError as e:
            logger.error(f"카카오 Event API 배치 POST 응답 JSON 파싱 실패: batch_size={batch_size}, reason={str(e)}")
            return 0, batch_size

        task_id = post_payload.get("taskId") or post_payload.get("taskID")
        if post_payload.get("status") != KAKAO_EVENT_API_SUCCESS_STATUS or not task_id:
            logger.error(
                f"카카오 Event API 배치 POST 요청 실패: status={post_payload.get('status')}, "
                f"taskId={task_id}, batch_size={batch_size}"
            )
            return 0, batch_size

        parsed_counts = await NotificationService._poll_task_result_counts(
            client=client,
            task_id=str(task_id),
            batch_size=batch_size,
        )
        if parsed_counts is None:
            return 0, batch_size

        return parsed_counts

    @staticmethod
    async def _poll_task_result_counts(
        client: httpx.AsyncClient,
        task_id: str,
        batch_size: int
    ) -> Optional[Tuple[int, int]]:
        """카카오 Event API task 결과를 제한된 횟수 안에서 조회하고 집계 건수를 반환"""
        poll_attempts = NotificationService._task_poll_attempts()
        for attempt in range(1, poll_attempts + 1):
            parsed_counts, should_retry = await NotificationService._get_task_result_counts_once(
                client=client,
                task_id=task_id,
                batch_size=batch_size,
                attempt=attempt,
            )
            if parsed_counts is not None:
                return parsed_counts
            if not should_retry:
                return None

            if attempt < poll_attempts:
                await asyncio.sleep(NotificationService._task_poll_delay_seconds(attempt))

        logger.error(
            f"카카오 Event API task 조회 최종 실패: attempts={poll_attempts}, "
            f"taskId={task_id}, batch_size={batch_size}"
        )
        return None

    @staticmethod
    def _task_poll_attempts() -> int:
        """설정 가능한 task 조회 최대 시도 횟수"""
        configured_attempts = getattr(
            settings,
            "KAKAO_TASK_RESULT_POLL_ATTEMPTS",
            KAKAO_TASK_RESULT_POLL_ATTEMPTS,
        )
        return max(1, int(configured_attempts))

    @staticmethod
    def _task_poll_delay_seconds(attempt: int) -> float:
        """시도 횟수에 따른 지수 backoff 대기 시간"""
        configured_delay = getattr(
            settings,
            "KAKAO_TASK_RESULT_POLL_DELAY_SECONDS",
            KAKAO_TASK_RESULT_POLL_DELAY_SECONDS,
        )
        base_delay = max(0.0, float(configured_delay))
        return base_delay * (2 ** (attempt - 1))

    @staticmethod
    async def _get_task_result_counts_once(
        client: httpx.AsyncClient,
        task_id: str,
        batch_size: int,
        attempt: int
    ) -> Tuple[Optional[Tuple[int, int]], bool]:
        """단일 task 결과 조회 시도에서 파싱 가능한 성공/실패 건수를 반환"""
        try:
            task_response = await client.get(
                NotificationService._kakao_task_url(task_id),
                headers=NotificationService._kakao_event_headers(),
                timeout=settings.NOTIFICATION_TIMEOUT
            )
        except httpx.HTTPError as e:
            logger.error(
                f"카카오 Event API task 조회 실패: attempt={attempt}, "
                f"taskId={task_id}, batch_size={batch_size}, reason={str(e)}"
            )
            return None, True

        if task_response.status_code != 200:
            logger.error(
                f"카카오 Event API task 조회 HTTP 실패: attempt={attempt}, "
                f"taskId={task_id}, status={task_response.status_code}, batch_size={batch_size}"
            )
            return None, True

        try:
            task_payload = task_response.json()
        except ValueError as e:
            logger.error(
                f"카카오 Event API task 응답 JSON 파싱 실패: attempt={attempt}, "
                f"taskId={task_id}, batch_size={batch_size}, reason={str(e)}"
            )
            return None, True

        parsed_counts = NotificationService._parse_task_result_counts(task_payload, batch_size)
        if parsed_counts is None:
            if NotificationService._is_task_result_pending(task_payload):
                logger.info(
                    f"카카오 Event API task 처리 대기: attempt={attempt}, "
                    f"taskId={task_id}, batch_size={batch_size}, status={task_payload.get('status')}"
                )
                return None, True

            logger.error(
                f"카카오 Event API task 집계 파싱 실패: attempt={attempt}, "
                f"taskId={task_id}, batch_size={batch_size}"
            )
            return None, False

        return parsed_counts, False

    @staticmethod
    def _is_task_result_pending(payload: Dict[str, Any]) -> bool:
        """아직 최종 집계가 준비되지 않은 task 상태인지 판별"""
        status = payload.get("status")
        if not isinstance(status, str):
            return False
        return status.upper() in KAKAO_TASK_PENDING_STATUSES

    @staticmethod
    def _parse_task_result_counts(payload: Dict[str, Any], batch_size: int) -> Optional[Tuple[int, int]]:
        """카카오 task 결과에서 검증된 성공/실패 건수를 추출"""
        success_count = NotificationService._non_negative_int(payload.get("successCount"))
        if success_count is None:
            return None

        fail_count = NotificationService._parse_fail_count(payload, success_count, batch_size)
        if fail_count is None:
            return None

        if success_count > batch_size or fail_count > batch_size:
            return None
        if success_count + fail_count != batch_size:
            return None

        return success_count, fail_count

    @staticmethod
    def _parse_fail_count(
        payload: Dict[str, Any],
        success_count: int,
        batch_size: int
    ) -> Optional[int]:
        """카카오 task 결과의 실패 건수 필드 또는 검증 가능한 fallback으로 실패 건수 계산"""
        fail_data = payload.get("fail")
        if isinstance(fail_data, dict) and "count" in fail_data:
            return NotificationService._non_negative_int(fail_data.get("count"))

        all_request_count = NotificationService._non_negative_int(payload.get("allRequestCount"))
        if all_request_count is not None:
            return all_request_count - success_count if all_request_count >= success_count else None

        return batch_size - success_count if batch_size >= success_count else None

    @staticmethod
    def _non_negative_int(value: Any) -> Optional[int]:
        """bool을 제외한 0 이상의 정수만 허용"""
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value if value >= 0 else None

    @staticmethod
    async def send_route_alert(user_id: str, events: List[Dict[str, Any]], id_type: str = "plusfriendUserKey") -> Dict[str, Any]:
        """경로 기반 집회 알림 전송"""
        if not events:
            return {"success": False, "error": "전송할 집회 정보가 없습니다"}

        message_text = NotificationService._format_event_message(events)

        # 첫 번째 집회 정보에서 이미지 경로 추출 (SMPA 집회들은 동일한 PDF 이미지를 공유함)
        image_url = None
        for event in events:
            if event.get("image_path"):
                base_url = settings.RENDER_EXTERNAL_URL or f"http://localhost:{settings.PORT}"
                image_url = f"{base_url}/{event['image_path']}"
                break

        # 알림 전송
        alarm_data = {"message": message_text}
        if image_url:
            alarm_data["image_url"] = image_url

        alarm_request = AlarmRequest(
            user_id=user_id,
            event_name="morning_demo_alarm",
            data=alarm_data
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

        # 이미지 URL 추출
        image_url = None
        for event in events_data:
            if event.get("image_path"):
                base_url = settings.RENDER_EXTERNAL_URL or f"http://localhost:{settings.PORT}"
                image_url = f"{base_url}/{event['image_path']}"
                break

        alarm_data = {"message": message_text}
        if image_url:
            alarm_data["image_url"] = image_url

        # Event API로 일괄 전송
        return await NotificationService.send_bulk_alarm(
            user_ids=user_ids,
            event_name="morning_demo_alarm",
            data=alarm_data,
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
        if event_name == "morning_demo_alarm":
            if "message" not in data:
                return {"valid": False, "error": "message 필드가 필요합니다"}
        
        return {"valid": True}
