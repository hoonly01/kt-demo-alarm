"""카카오톡 관련 라우터"""
from fastapi import APIRouter, Request, HTTPException
import logging
import json
from datetime import datetime

from app.models.kakao import KakaoRequest

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
    properties = request.userRequest.user.properties
    plusfriend_key = properties.get('plusfriendUserKey') if properties else None

    logger.info(f"📨 사용자 메시지: {user_message} (botUserKey: {bot_user_key}, plusfriend: {plusfriend_key})")

    from app.database.connection import get_db_connection

    with get_db_connection() as db:
        cursor = db.cursor()

        # plusfriend_user_key로 기존 사용자 조회 (가장 안정적)
        if plusfriend_key:
            cursor.execute(
                "SELECT bot_user_key, open_id FROM users WHERE plusfriend_user_key = ?",
                (plusfriend_key,)
            )
            existing = cursor.fetchone()

            if existing:
                # 이미 존재 → bot_user_key 업데이트
                cursor.execute(
                    "UPDATE users SET bot_user_key = ?, last_message_at = ?, message_count = message_count + 1 WHERE plusfriend_user_key = ?",
                    (bot_user_key, datetime.now(), plusfriend_key)
                )
                db.commit()
                logger.info(f"사용자 업데이트: plusfriend={plusfriend_key}")
            else:
                # 웹훅 사용자 찾기 시도
                cursor.execute(
                    "SELECT id FROM users WHERE bot_user_key IS NULL AND plusfriend_user_key IS NULL LIMIT 1"
                )
                orphan = cursor.fetchone()

                if orphan:
                    # 웹훅 사용자 연결
                    cursor.execute(
                        "UPDATE users SET bot_user_key = ?, plusfriend_user_key = ?, last_message_at = ? WHERE id = ?",
                        (bot_user_key, plusfriend_key, datetime.now(), orphan[0])
                    )
                    db.commit()
                    logger.info(f"✅ 웹훅 사용자 연결: botUserKey={bot_user_key}, plusfriend={plusfriend_key}")
                else:
                    # 완전 신규 사용자
                    cursor.execute('''
                        INSERT INTO users (bot_user_key, plusfriend_user_key, first_message_at, last_message_at, message_count, active)
                        VALUES (?, ?, ?, ?, 1, 1)
                    ''', (bot_user_key, plusfriend_key, datetime.now(), datetime.now()))
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
    웹훅에서는 open_id만 제공됨
    """
    body = await request.json()
    logger.info(f"🔗 카카오 채널 웹훅 수신: {json.dumps(body, ensure_ascii=False)}")

    event = body.get('event', '')
    open_id = body.get('id', '')

    if not open_id:
        logger.warning("사용자 ID가 없는 웹훅 요청")
        return {"status": "error", "message": "사용자 ID 필요"}

    from app.database.connection import get_db_connection

    try:
        with get_db_connection() as db:
            cursor = db.cursor()

            # open_id로 기존 사용자 조회 (plusfriend_user_key도 확인)
            cursor.execute(
                "SELECT bot_user_key, plusfriend_user_key, active FROM users WHERE open_id = ?",
                (open_id,)
            )
            existing_user = cursor.fetchone()

            if event == 'added' or event == 'chat_room':
                logger.info(f"✅ 채널 추가: open_id={open_id}")

                if existing_user:
                    # 이미 존재 → active만 업데이트
                    plusfriend_key = existing_user[1]
                    if plusfriend_key:
                        # plusfriend_key로 업데이트 (더 안정적)
                        cursor.execute("UPDATE users SET active = 1 WHERE plusfriend_user_key = ?", (plusfriend_key,))
                    else:
                        cursor.execute("UPDATE users SET active = 1 WHERE open_id = ?", (open_id,))
                    db.commit()
                else:
                    # 신규 → open_id만 저장 (Skill Block 접속 시 나머지 추가)
                    cursor.execute('''
                        INSERT INTO users (open_id, first_message_at, last_message_at, message_count, active)
                        VALUES (?, ?, ?, 1, 1)
                    ''', (open_id, datetime.now(), datetime.now()))
                    db.commit()
                    logger.info(f"신규 사용자 생성 (open_id만): {open_id}")

            elif event == 'blocked' or event == 'leave':
                logger.info(f"❌ 채널 차단: open_id={open_id}")

                if existing_user:
                    plusfriend_key = existing_user[1]
                    if plusfriend_key:
                        cursor.execute("UPDATE users SET active = 0 WHERE plusfriend_user_key = ?", (plusfriend_key,))
                    else:
                        cursor.execute("UPDATE users SET active = 0 WHERE open_id = ?", (open_id,))
                    db.commit()

            else:
                logger.warning(f"알 수 없는 이벤트: {event}")

    except Exception as e:
        logger.error(f"웹훅 처리 중 오류: {str(e)}")
        raise HTTPException(status_code=500, detail="웹훅 처리 실패")

    # 성공 응답 (3초 내 2XX 응답 필요)
    return {"status": "ok", "processed_event": event, "open_id": open_id}