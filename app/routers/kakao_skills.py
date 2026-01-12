"""카카오톡 Skill Block 전용 라우터 (prefix 없음)"""
from fastapi import APIRouter, Depends
import sqlite3
import logging

from app.database.connection import get_db
from app.services.event_service import EventService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["kakao-skills"])


@router.post("/upcoming-protests")
async def get_upcoming_protests(
    request: dict,
    db: sqlite3.Connection = Depends(get_db)
):
    """
    다가오는 집회 정보 조회 (카카오톡 Skill Block)
    """
    logger.info(f"🔍 /upcoming-protests 요청: {request}")

    # Skill Block 형식에서 파라미터 추출 (필요시)
    params = request.get('action', {}).get('params', {})
    limit = params.get('limit', 5)

    # 다가오는 집회 조회
    events = EventService.get_upcoming_events(limit, db)

    if not events:
        return {
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": "📅 현재 예정된 집회가 없습니다."
                        }
                    }
                ]
            }
        }

    # 집회 정보를 텍스트로 포맷
    event_messages = []
    for event in events:
        severity_emoji = "🔴" if event.severity_level >= 3 else "🟡" if event.severity_level >= 2 else "🟢"
        event_messages.append(
            f"{severity_emoji} {event.title}\n"
            f"📍 {event.location_name}\n"
            f"⏰ {event.start_date}\n"
            f"🏷️ {event.category if event.category else '일반'}"
        )

    message_text = f"📅 예정된 집회 {len(events)}건:\n\n" + "\n\n".join(event_messages)

    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "simpleText": {
                        "text": message_text
                    }
                }
            ]
        }
    }


@router.post("/today-protests")
async def get_today_protests(
    request: dict,
    db: sqlite3.Connection = Depends(get_db)
):
    """
    오늘 집회 정보 조회 (카카오톡 Skill Block)
    """
    logger.info(f"🔍 /today-protests 요청: {request}")

    # 오늘 집회 조회
    events = EventService.get_today_events(db)

    if not events:
        return {
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": "📅 오늘 예정된 집회가 없습니다."
                        }
                    }
                ]
            }
        }

    # 집회 정보를 텍스트로 포맷
    event_messages = []
    for event in events:
        severity_emoji = "🔴" if event.severity_level >= 3 else "🟡" if event.severity_level >= 2 else "🟢"
        event_messages.append(
            f"{severity_emoji} {event.title}\n"
            f"📍 {event.location_name}\n"
            f"⏰ {event.start_date}\n"
            f"🏷️ {event.category if event.category else '일반'}"
        )

    message_text = f"📅 오늘 예정된 집회 {len(events)}건:\n\n" + "\n\n".join(event_messages)

    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "simpleText": {
                        "text": message_text
                    }
                }
            ]
        }
    }


@router.post("/check-route")
async def check_user_route_events(
    request: dict,
    db: sqlite3.Connection = Depends(get_db)
):
    """
    사용자의 경로상에 있는 집회들을 확인 (카카오톡 Skill Block)
    """
    logger.info(f"🔍 /check-route 요청: {request}")

    # Skill Block에서 사용자 ID 추출 (plusfriendUserKey 우선)
    user_request = request.get('userRequest', {})
    user_info = user_request.get('user', {})
    properties = user_info.get('properties', {})
    plusfriend_key = properties.get('plusfriendUserKey')
    bot_user_key = user_info.get('id')

    # plusfriend_key가 있으면 우선 사용, 없으면 bot_user_key 사용
    user_id = plusfriend_key if plusfriend_key else bot_user_key

    logger.info(f"📝 경로 확인 - user_id: {user_id}")

    # 경로 집회 확인 (알림은 보내지 않음)
    result = await EventService.check_route_events(user_id, auto_notify=False, db=db)

    if not result.events_found:
        return {
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": (
                                "✅ 좋은 소식입니다!\n\n"
                                "등록하신 경로에 예정된 집회가 없습니다.\n"
                                "안전한 출퇴근 되세요! 😊"
                            )
                        }
                    }
                ]
            }
        }

    # 집회 정보 포맷
    event_messages = []
    for event in result.events_found:
        severity_emoji = "🔴" if event.severity_level >= 3 else "🟡" if event.severity_level >= 2 else "🟢"
        event_messages.append(
            f"{severity_emoji} {event.title}\n"
            f"📍 {event.location_name}\n"
            f"⏰ {event.start_date}\n"
            f"🏷️ {event.category if event.category else '일반'}"
        )

    message_text = (
        f"⚠️ 경로상에 {len(result.events_found)}개의 집회가 감지되었습니다:\n\n"
        + "\n\n".join(event_messages)
        + "\n\n출퇴근 시 우회 경로를 고려해주세요."
    )

    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "simpleText": {
                        "text": message_text
                    }
                }
            ]
        }
    }
