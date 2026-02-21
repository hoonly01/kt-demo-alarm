"""카카오톡 Skill Block 전용 라우터 (prefix 없음)"""
from fastapi import APIRouter, Depends, BackgroundTasks
import sqlite3
import logging

from app.database.connection import get_db
from app.services.event_service import EventService
from app.services.user_service import UserService

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


@router.post("/save_user_info")
async def save_user_info(request: dict, background_tasks: BackgroundTasks):
    """
    카카오톡 스킬 블록에서 사용자 경로 정보를 저장하는 엔드포인트
    - 출발지와 도착지만 저장 (간단 버전)
    - 백그라운드 처리로 빠른 응답

    Parameters in action.params:
    - departure: 출발지 (예: "영통역")
    - arrival: 도착지 (예: "광화문역")
    """
    logger.info(f"🔍 /save_user_info 요청: {request}")

    # Skill Block에서 사용자 ID 추출 (plusfriendUserKey 우선)
    user_request = request.get('userRequest', {})
    user_info = user_request.get('user', {})
    bot_user_key = user_info.get('id')
    properties = user_info.get('properties', {})
    plusfriend_key = properties.get('plusfriendUserKey')

    # plusfriend_key 우선 사용
    user_id = plusfriend_key if plusfriend_key else bot_user_key

    logger.info(f"📝 사용자 ID: botUserKey={bot_user_key}, plusfriend={plusfriend_key}")

    # 출발지와 도착지 정보 추출
    params = request.get('action', {}).get('params', {})
    departure = params.get('departure', '')
    arrival = params.get('arrival', '')

    logger.info(f"📍 경로: {departure} → {arrival}")

    # 사용자 생성/업데이트 (동기화)
    from app.services.user_service import UserService
    from app.database.connection import get_db_connection

    with get_db_connection() as db:
        # [REFACTOR] 통합된 사용자 동기화 로직 사용
        UserService.sync_kakao_user(bot_user_key, plusfriend_key, db)

    # 백그라운드에서 경로 정보 저장 (Route Only Update)
    async def save_route_to_db_task(user_id: str, departure: str, arrival: str):
        """백그라운드 작업: 경로 정보만 업데이트"""
        from app.database.connection import get_db_connection
        try:
            with get_db_connection() as conn:
                # [REFACTOR] 경로 정보만 업데이트하는 메서드 호출
                result = await UserService.update_user_route(
                    user_id=user_id,
                    departure=departure,
                    arrival=arrival,
                    db=conn
                )

                if result["success"]:
                    logger.info(f"사용자 {user_id} 경로 정보 저장 완료")
                else:
                    logger.error(f"사용자 {user_id} 경로 정보 저장 실패: {result.get('error')}")

        except Exception as e:
            logger.error(f"경로 정보 저장 중 오류: {str(e)}")

    background_tasks.add_task(save_route_to_db_task, user_id, departure, arrival)

    # 즉시 응답 (사용자 대기 시간 단축)
    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "simpleText": {
                        "text": (
                            f"📍 출발지: {departure}\n"
                            f"📍 도착지: {arrival}\n\n"
                            "✅ 출발지와 도착지가 정상적으로 등록되었습니다.\n"
                            "📢 매일 아침, 등록하신 경로에 예정된 집회 정보를 안내해드립니다.\n"
                            "🔄 경로를 변경하고 싶으실 땐, 언제든 [🚗 출퇴근 경로 등록하기] 버튼을 눌러주세요."
                        )
                    }
                }
            ]
        }
    }


# ─── 관심장소 알림 설정 ─────────────────────────────────────

# 구역 정보 상수
ZONE_INFO = {
    1: {
        "title": "1구역",
        "description": "광화문광장 중심 반경 2KM\n(삼청동, 청운효자동, 가회동, 사직동, 종로1·4가동)",
    },
    2: {
        "title": "2구역",
        "description": "세검정 중심 반경 1.3KM\n(평창동, 부암동)",
    },
    3: {
        "title": "3구역",
        "description": "한국방송통신대학교 중심 반경 1.3KM\n(혜화동, 이화동, 종로5·6가동, 창신제1~3동, 숭인제1~2동)",
    },
}

# zone 파라미터 값 → zone 매핑
ZONE_PARAM_MAP = {
    "1구역": 1,
    "2구역": 2,
    "3구역": 3,
    "미설정": None,
}


@router.post("/favorite-zone")
async def get_favorite_zone_selection(request: dict):
    """
    관심장소 구역 선택 UI 반환 (카카오톡 Skill Block)
    - ListCard 형식으로 4개 구역 옵션 표시
    """
    logger.info(f"🔍 /favorite-zone 요청: {request}")

    items = []
    for zone_num, info in ZONE_INFO.items():
        items.append({
            "title": info["title"],
            "description": info["description"],
            "action": "message",
            "messageText": info["title"],
        })

    # 미설정 옵션 추가
    items.append({
        "title": "미설정",
        "description": "기존 관심장소 정보를 삭제합니다",
        "action": "message",
        "messageText": "미설정",
    })

    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "listCard": {
                        "header": {
                            "title": "📍 관심장소를 선택해 주세요"
                        },
                        "items": items
                    }
                }
            ]
        }
    }


@router.post("/favorite-zone/save")
async def save_favorite_zone(
    request: dict,
    db: sqlite3.Connection = Depends(get_db)
):
    """
    관심장소 구역 선택 저장 (카카오톡 Skill Block)
    - 사용자가 선택한 구역을 DB에 저장
    - params.zone: "1구역", "2구역", "3구역", "미설정"
    """
    try:
        logger.info(f"🔍 /favorite-zone/save 요청: {request}")

        # Skill Block에서 사용자 ID 추출
        user_request = request.get('userRequest', {})
        user_info = user_request.get('user', {})
        bot_user_key = user_info.get('id')
        properties = user_info.get('properties', {})
        plusfriend_key = properties.get('plusfriendUserKey')

        user_id = plusfriend_key if plusfriend_key else bot_user_key

        if not user_id:
            return {
                "version": "2.0",
                "template": {
                    "outputs": [{"simpleText": {"text": "사용자 식별 정보가 누락되었습니다. 카카오톡 채널을 통해 다시 시도해주세요."}}]
                }
            }

        # 파라미터 추출
        params = request.get('action', {}).get('params', {})
        zone_param = params.get('zone', '').strip()

        if zone_param not in ZONE_PARAM_MAP:
            return {
                "version": "2.0",
                "template": {
                    "outputs": [{"simpleText": {"text": f"올바르지 않은 구역 값입니다 ('{zone_param}'). 1구역, 2구역, 3구역, 미설정 중 선택해주세요."}}]
                }
            }

        zone_value = ZONE_PARAM_MAP[zone_param]

        logger.info(f"📝 관심장소 설정 변경: user_id={user_id}, zone={zone_param}")

        # 사용자 동기화
        UserService.sync_kakao_user(bot_user_key, plusfriend_key, db)

        # 구역 설정 업데이트
        result = UserService.update_favorite_zone(user_id, zone_value, db)

        if result["success"]:
            if zone_value is not None:
                zone_info = ZONE_INFO[zone_value]
                msg = (
                    f"✅ 관심장소가 [{zone_info['title']}]으로 설정되었습니다.\n\n"
                    f"📍 {zone_info['description']}\n\n"
                    "해당 구역 내 집회 정보가 있을 때 알림을 보내드립니다."
                )
            else:
                msg = "🔕 관심장소 설정이 해제되었습니다.\n기존 관심장소 정보가 삭제되었습니다."

            return {
                "version": "2.0",
                "template": {
                    "outputs": [{"simpleText": {"text": msg}}]
                }
            }
        else:
            return {
                "version": "2.0",
                "template": {
                    "outputs": [{"simpleText": {"text": result.get("error", "관심장소 설정에 실패했습니다.")}}]
                }
            }

    except Exception as e:
        logger.exception("관심장소 설정 중 시스템 오류 발생")
        return {
            "version": "2.0",
            "template": {
                "outputs": [{"simpleText": {"text": "시스템 오류가 발생했습니다. 잠시 후 다시 시도해주세요."}}]
            }
        }


@router.post("/save_marked_bus")
async def save_marked_bus(request: dict, background_tasks: BackgroundTasks):
    """
    카카오톡 스킬 블록에서 사용자의 marked_bus 정보를 저장하는 엔드포인트

    Parameters in action.params:
    - marked_bus: 버스 번호/노선명 (예: "7016")
    """
    logger.info(f"🔍 /save_marked_bus 요청: {request}")

    # Skill Block에서 사용자 ID 추출 (plusfriendUserKey 우선)
    user_request = request.get('userRequest', {})
    user_info = user_request.get('user', {})
    bot_user_key = user_info.get('id')
    properties = user_info.get('properties', {})
    plusfriend_key = properties.get('plusfriendUserKey')

    user_id = plusfriend_key if plusfriend_key else bot_user_key
    logger.info(f"📝 사용자 ID: botUserKey={bot_user_key}, plusfriend={plusfriend_key} -> user_id={user_id}")

    # params에서 marked_bus 추출
    params = request.get('action', {}).get('params', {})
    marked_bus = (params.get('marked_bus') or "").strip()

    if not marked_bus:
        return {
            "version": "2.0",
            "template": {"outputs": [{"simpleText": {"text": "🚌 버스 번호가 비어있어요. 예: 7016"}}]}
        }

    from app.services.user_service import UserService
    from app.database.connection import get_db_connection

    # 사용자 동기화
    with get_db_connection() as db:
        UserService.sync_kakao_user(bot_user_key, plusfriend_key, db)

    # 백그라운드 저장
    async def save_marked_bus_task(user_id: str, marked_bus: str):
        from app.database.connection import get_db_connection
        from app.services.user_service import UserService
        try:
            with get_db_connection() as conn:
                result = await UserService.update_marked_bus(
                    user_id=user_id,
                    marked_bus=marked_bus,
                    db=conn
                )
                if result["success"]:
                    logger.info(f"✅ marked_bus 저장 완료: {user_id} -> {marked_bus}")
                else:
                    logger.error(f"❌ marked_bus 저장 실패: {result.get('error')}")
        except Exception as e:
            logger.error(f"🚨 marked_bus 저장 중 오류: {str(e)}")

    background_tasks.add_task(save_marked_bus_task, user_id, marked_bus)

    return {
        "version": "2.0",
        "template": {
            "outputs": [{
                "simpleText": {
                    "text": (
                        f"✅ 자주 타는 버스가 등록되었습니다!\n"
                        f"🚌 {marked_bus}\n\n"
                        "🔄 변경하고 싶으면 다시 등록해 주세요."
                    )
                }
            }]
        }
    }
