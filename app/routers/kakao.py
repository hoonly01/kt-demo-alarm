"""카카오톡 관련 라우터"""
from fastapi import APIRouter, Request, HTTPException
import logging
import json

from app.models.kakao import KakaoRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/kakao", tags=["kakao"])


@router.post("/chat")
async def kakao_chat_fallback(request: KakaoRequest):
    """
    카카오톡 챗봇 폴백 블록 엔드포인트
    사용자가 메시지를 보내면 여기서 받아서 처리
    """
    user_message = request.userRequest.utterance
    user_id = request.userRequest.user.id
    
    logger.info(f"📨 사용자 메시지: {user_message} (ID: {user_id})")
    
    # 사용자 정보 저장/업데이트
    from app.services.user_service import UserService
    from app.database.connection import get_db_connection
    with get_db_connection() as db:
        UserService.save_or_update_user(user_id, db, user_message)
    
    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "simpleText": {
                        "text": (
                            "안녕하세요! 👋\n\n"
                            "저는 KT 종로구 집회 알림 봇입니다.\n"
                            "출퇴근 경로에 예정된 집회 정보를 미리 알려드려요!\n\n"
                            "🚗 [출퇴근 경로 등록하기] 버튼을 눌러 경로를 설정해주세요.\n"
                            "📢 매일 아침 7시에 경로상의 집회 정보를 안내해드립니다."
                        )
                    }
                }
            ],
            "quickReplies": [
                {
                    "label": "🚗 출퇴근 경로 등록하기",
                    "action": "message",
                    "messageText": "출퇴근 경로를 등록하고 싶어요"
                }
            ]
        }
    }


@router.post("/webhook/channel")
async def kakao_channel_webhook(request: Request):
    """
    카카오톡 채널 추가/차단 웹훅 엔드포인트
    """
    body = await request.json()
    logger.info(f"🔗 카카오 채널 웹훅 수신: {json.dumps(body, ensure_ascii=False)}")
    
    # 이벤트 타입 확인
    event = body.get('event', '')
    # 카카오 웹훅은 'id' 필드로 사용자 ID를 전달함 ('user_id' 아님)
    user_id = body.get('id', '') or body.get('user_id', '')

    if not user_id:
        logger.warning("사용자 ID가 없는 웹훅 요청")
        return {"status": "error", "message": "사용자 ID 필요"}
    
    # 사용자 상태 업데이트
    from app.services.user_service import UserService
    from app.database.connection import get_db_connection
    
    try:
        with get_db_connection() as db:
            if event == 'added' or event == 'chat_room':
                # 채널 추가
                logger.info(f"✅ 채널 추가: {user_id}")
                UserService.save_or_update_user(user_id, db, "채널 추가")
                UserService.update_user_status(user_id, db, active=True)

            elif event == 'blocked' or event == 'leave':
                # 채널 차단
                logger.info(f"❌ 채널 차단: {user_id}")
                UserService.save_or_update_user(user_id, db, "채널 차단")
                UserService.update_user_status(user_id, db, active=False)

            else:
                logger.warning(f"알 수 없는 이벤트: {event}")
    
    except Exception as e:
        logger.error(f"웹훅 처리 중 오류: {str(e)}")
        raise HTTPException(status_code=500, detail="웹훅 처리 실패")
    
    # 성공 응답 (3초 내 2XX 응답 필요)
    return {"status": "ok", "processed_event": event, "user_id": user_id}