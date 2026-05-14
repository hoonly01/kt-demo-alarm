"""카카오톡 관련 라우터"""
from fastapi import APIRouter, Request, HTTPException
import logging
import json
from datetime import datetime
from typing import Any, cast

from app.database.connection import get_db_connection
from app.models.kakao import KakaoRequest
from app.repositories.user_identity_repository import UserIdentityRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/kakao", tags=["kakao"])


@router.post("/chat")
async def kakao_chat_fallback(request: KakaoRequest):
    """
    카카오톡 챗봇 폴백 블록 엔드포인트
    Skill Block에서 botUserKey + plusfriendUserKey 제공
    """
    user_message = request.userRequest.utterance
    bot_user_key = request.userRequest.user.id
    properties = cast(dict[str, Any], request.userRequest.user.properties or {})
    plusfriend_value = properties.get('plusfriendUserKey')
    plusfriend_key = plusfriend_value if isinstance(plusfriend_value, str) else None

    logger.info(f"📨 사용자 메시지: {user_message} (botUserKey: {bot_user_key}, plusfriend: {plusfriend_key})")

    with get_db_connection() as db:
        # plusfriend_user_key로 기존 사용자 조회 (가장 안정적)
        if plusfriend_key:
            existing = UserIdentityRepository.find_by_plusfriend_key(db, plusfriend_key)
            now = datetime.now()

            if existing:
                # 이미 존재 → bot_user_key 업데이트
                UserIdentityRepository.touch_chat_plusfriend_user(
                    db,
                    plusfriend_key=plusfriend_key,
                    bot_user_key=bot_user_key,
                    now=now,
                )
                db.commit()
                logger.info(f"사용자 업데이트: plusfriend={plusfriend_key}")
            else:
                # 웹훅 사용자 찾기 시도
                orphan = UserIdentityRepository.find_first_unlinked_user(db)

                if orphan:
                    # 웹훅 사용자 연결
                    UserIdentityRepository.link_unlinked_user_from_chat(
                        db,
                        user_id=orphan["id"],
                        bot_user_key=bot_user_key,
                        plusfriend_key=plusfriend_key,
                        now=now,
                    )
                    db.commit()
                    logger.info(f"✅ 웹훅 사용자 연결: botUserKey={bot_user_key}, plusfriend={plusfriend_key}")
                else:
                    # 완전 신규 사용자
                    UserIdentityRepository.insert_kakao_identity(
                        db,
                        bot_user_key=bot_user_key,
                        plusfriend_key=plusfriend_key,
                        now=now,
                    )
                    db.commit()
                    logger.info(f"새 사용자 등록: botUserKey={bot_user_key}, plusfriend={plusfriend_key}")

    # 응답 생성 (기존 코드 유지)
    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "simpleText": {
                        "text": (
                            "안녕하세요! 👋\n\n"
                            "저는 KT 종로구 집회 알림 봇입니다.\n"
                            "이동 경로에 예정된 집회 정보를 미리 알려드려요!\n\n"
                            "🚗 [이동 경로 등록하기] 버튼을 눌러 경로를 설정해주세요.\n"
                            "📢 매일 아침 7시에 경로상의 집회 정보를 안내해드립니다."
                        )
                    }
                }
            ],
            "quickReplies": [
                {
                    "label": "🚗 이동 경로 등록하기",
                    "action": "message",
                    "messageText": "이동 경로를 등록하고 싶어요"
                }
            ]
        }
    }


@router.post("/webhook/channel")
async def kakao_channel_webhook(request: Request):
    """
    카카오톡 채널 추가/차단 웹훅 엔드포인트
    웹훅에서는 open_id만 제공됨
    """
    body = cast(dict[str, Any], await request.json())
    logger.info(f"🔗 카카오 채널 웹훅 수신: {json.dumps(body, ensure_ascii=False)}")

    event_value = body.get('event', '')
    open_id_value = body.get('id', '')
    event = event_value if isinstance(event_value, str) else ""
    open_id = open_id_value if isinstance(open_id_value, str) else ""

    if not open_id:
        logger.warning("사용자 ID가 없는 웹훅 요청")
        return {"status": "error", "message": "사용자 ID 필요"}

    try:
        with get_db_connection() as db:
            # open_id로 기존 사용자 조회 (plusfriend_user_key도 확인)
            existing_user = UserIdentityRepository.find_by_open_id(db, open_id)
            now = datetime.now()

            if event == 'added' or event == 'chat_room':
                logger.info(f"✅ 채널 추가: open_id={open_id}")

                if existing_user:
                    # 이미 존재 → active만 업데이트
                    plusfriend_value = existing_user["plusfriend_user_key"]
                    plusfriend_key = plusfriend_value if isinstance(plusfriend_value, str) else None
                    if plusfriend_key:
                        # plusfriend_key로 업데이트 (더 안정적)
                        UserIdentityRepository.set_active_by_plusfriend_key(
                            db,
                            plusfriend_key=plusfriend_key,
                            active=True,
                        )
                    else:
                        UserIdentityRepository.set_active_by_open_id(
                            db,
                            open_id=open_id,
                            active=True,
                        )
                    db.commit()
                else:
                    # 신규 → open_id만 저장 (Skill Block 접속 시 나머지 추가)
                    UserIdentityRepository.insert_open_id_user(
                        db,
                        open_id=open_id,
                        now=now,
                    )
                    db.commit()
                    logger.info(f"신규 사용자 생성 (open_id만): {open_id}")

            elif event == 'blocked' or event == 'leave':
                logger.info(f"❌ 채널 차단: open_id={open_id}")

                if existing_user:
                    plusfriend_value = existing_user["plusfriend_user_key"]
                    plusfriend_key = plusfriend_value if isinstance(plusfriend_value, str) else None
                    if plusfriend_key:
                        UserIdentityRepository.set_active_by_plusfriend_key(
                            db,
                            plusfriend_key=plusfriend_key,
                            active=False,
                        )
                    else:
                        UserIdentityRepository.set_active_by_open_id(
                            db,
                            open_id=open_id,
                            active=False,
                        )
                    db.commit()

            else:
                logger.warning(f"알 수 없는 이벤트: {event}")

    except Exception as e:
        logger.error(f"웹훅 처리 중 오류: {str(e)}")
        raise HTTPException(status_code=500, detail="웹훅 처리 실패")

    # 성공 응답 (3초 내 2XX 응답 필요)
    return {"status": "ok", "processed_event": event, "open_id": open_id}
