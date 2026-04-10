"""사용자 관련 라우터"""
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
import sqlite3
from typing import List, Dict, Any
import logging

from app.models.user import UserPreferences, InitialSetupRequest
from app.database.connection import get_db
from app.services.user_service import UserService
from app.services.auth_service import verify_api_key

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


@router.get("")
async def get_users(
    db: sqlite3.Connection = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """등록된 사용자 목록 조회 (경로 정보 포함)"""
    try:
        cursor = db.cursor()
        cursor.execute('''
            SELECT bot_user_key, first_message_at, last_message_at, message_count, 
                   location, active, departure_name, departure_address, 
                   departure_x, departure_y, arrival_name, arrival_address, 
                   arrival_x, arrival_y, route_updated_at, marked_bus, language
            FROM users 
            ORDER BY last_message_at DESC
        ''')
        
        users = []
        for row in cursor.fetchall():
            user_data = {
                "bot_user_key": row["bot_user_key"],
                "first_message_at": row["first_message_at"],
                "last_message_at": row["last_message_at"],
                "message_count": row["message_count"],
                "location": row["location"],
                "active": bool(row["active"]),
                "marked_bus": row["marked_bus"],
                "language": row["language"]
            }

            # 경로 정보가 있는 경우만 포함
            if all([row["departure_x"], row["departure_y"], row["arrival_x"], row["arrival_y"]]):
                user_data["route_info"] = {
                    "departure": {
                        "name": row["departure_name"],
                        "address": row["departure_address"],
                        "x": row["departure_x"],
                        "y": row["departure_y"]
                    },
                    "arrival": {
                        "name": row["arrival_name"],
                        "address": row["arrival_address"],
                        "x": row["arrival_x"],
                        "y": row["arrival_y"]
                    },
                    "updated_at": row["route_updated_at"]
                }
            else:
                user_data["route_info"] = None
            
            users.append(user_data)
        
        return {
            "total": len(users),
            "users": users
        }
        
    except Exception as e:
        logger.error(f"사용자 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="사용자 조회 중 오류가 발생했습니다")


@router.post("/{user_id}/preferences")
async def update_user_preferences(
    user_id: str,
    preferences: UserPreferences,
    db: sqlite3.Connection = Depends(get_db)
):
    """사용자 설정 업데이트"""
    result = UserService.update_user_preferences(user_id, preferences, db)
    
    if result["success"]:
        return {"message": "설정이 성공적으로 업데이트되었습니다"}
    else:
        raise HTTPException(status_code=400, detail=result["error"])


@router.post("/save_user_info")
async def save_user_info(request: dict, background_tasks: BackgroundTasks):
    """
    카카오톡 스킬 블록에서 사용자 경로 정보를 저장하는 엔드포인트
    (DEPRECATED: /users/initial-setup 사용 권장)
    """
    logger.info(f"🔍 save_user_info 요청 body: {request}")

    # 기본값 초기화
    bot_user_key = None
    plusfriend_key = None

    # Skill Block에서 사용자 ID 추출 (plusfriendUserKey 우선)
    if 'userRequest' in request:
        user_info = request['userRequest']['user']
        bot_user_key = user_info.get('id')
        properties = user_info.get('properties', {})
        plusfriend_key = properties.get('plusfriendUserKey')
        # plusfriend_key 우선 사용
        user_id = plusfriend_key if plusfriend_key else bot_user_key
    else:  # 로컬 테스트용
        user_id = request.get('userId', 'test-user')
        bot_user_key = "test_user_key" # 테스트용 기본값

    # 사용자 생성/업데이트
    if 'userRequest' in request:
        from app.services.user_service import UserService
        from app.database.connection import get_db_connection
        
        # [REFACTOR] 통합된 사용자 동기화 로직 사용
        with get_db_connection() as db:
            UserService.sync_kakao_user(bot_user_key, plusfriend_key, db)
    
    # 출발지와 도착지 정보 추출
    departure = request.get('action', {}).get('params', {}).get('departure', '')
    arrival = request.get('action', {}).get('params', {}).get('arrival', '')
    
    # 백그라운드에서 경로 정보 저장
    # user_id는 plusfriend_key가 있으면 그것을, 없으면 bot_user_key를 사용 (기존 로직 유지)
    target_user_id = plusfriend_key if plusfriend_key else bot_user_key
    background_tasks.add_task(save_route_to_db, target_user_id, departure, arrival)
    
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
                            "🔄 경로를 변경하고 싶으실 땐, 언제든 [🚗 이동 경로 등록하기] 버튼을 눌러주세요."
                        )
                    }
                }
            ]
        }
    }


@router.post("/initial-setup")
async def initial_setup(request: dict, db: sqlite3.Connection = Depends(get_db)):
    """
    사용자 초기 설정 (Skill Block 전용)
    - Skill Block에서 경로 등록 시 호출
    - plusfriendUserKey를 primary identifier로 사용
    """
    try:
        logger.info(f"🔍 /users/initial-setup 요청 body: {request}")

        # Skill Block 형식 파싱
        user_request = request.get('userRequest', {})
        user_info = user_request.get('user', {})
        action = request.get('action', {})
        params = action.get('params', {})

        # ID 추출
        bot_user_key = user_info.get('id')
        properties = user_info.get('properties', {})
        plusfriend_key = properties.get('plusfriendUserKey')  # ← 핵심!

        if not plusfriend_key:
            return {
                "version": "2.0",
                "template": {
                    "outputs": [
                        {
                            "simpleText": {
                                "text": "사용자 식별 정보가 누락되었습니다. 카카오톡 채널을 통해 다시 시도해주세요."
                            }
                        }
                    ]
                }
            }

        # 파라미터 추출
        departure = params.get('departure')
        arrival = params.get('arrival')
        marked_bus = params.get('marked_bus')
        language = params.get('language')

        logger.info(f"📝 사용자 ID: botUserKey={bot_user_key}, plusfriend={plusfriend_key}")
        logger.info(f"📍 경로: {departure} → {arrival}, 버스={marked_bus}, 언어={language}")

        # InitialSetupRequest 생성 (plusfriend_key를 bot_user_key로 사용!)
        setup_request = InitialSetupRequest(
            bot_user_key=plusfriend_key,  # ← plusfriend_key를 primary key로 사용!
            departure=departure,
            arrival=arrival,
            marked_bus=marked_bus,
            language=language
        )

        # [REFACTOR] 통합된 사용자 동기화 로직 사용
        UserService.sync_kakao_user(bot_user_key, plusfriend_key, db)

        # [REFACTOR] 전체 프로필 설정 (경로 + 설정)
        result = await UserService.setup_user_profile(setup_request, db)

        if result["success"]:
            # Skill 응답 형식 (카카오톡 말풍선)
            return {
                "version": "2.0",
                "template": {
                    "outputs": [
                        {
                            "simpleText": {
                                "text": (
                                    f"📍 출발지: {departure}\n"
                                    f"📍 도착지: {arrival}\n\n"
                                    "✅ 경로 등록이 완료되었습니다!\n"
                                    "📢 매일 아침, 등록하신 경로에 예정된 집회 정보를 안내해드립니다."
                                )
                            }
                        }
                    ]
                }
            }
        else:
            # 실패 시에도 200 OK 리턴하고 에러 메시지를 사용자에게 전달
            return {
                "version": "2.0",
                "template": {
                    "outputs": [
                        {
                            "simpleText": {
                                "text": result["error"]
                            }
                        }
                    ]
                }
            }

    except Exception as e:
        logger.exception("초기 설정 중 시스템 오류 발생")
        # 시스템 오류 시에도 200 OK 리턴
        return {
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": "시스템 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
                        }
                    }
                ]
            }
        }


@router.post("/alarm-setting")
async def alarm_setting(request: dict, db: sqlite3.Connection = Depends(get_db)):
    """
    사용자 알람 설정 (Skill Block 전용)
    - 알람 on/off 기능
    """
    try:
        logger.info(f"🔍 /users/alarm-setting 요청 body: {request}")

        # Skill Block 형식 파싱
        user_request = request.get('userRequest', {})
        user_info = user_request.get('user', {})
        action = request.get('action', {})
        params = action.get('params', {})

        # ID 추출
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
        alarm_status_str = params.get('alarm_status', '').lower()
        
        if alarm_status_str == 'on':
            is_alarm_on = True
            msg = "✅ 매일 아침 알림이 켜졌습니다.\n등록하신 이동 경로에 영향을 주는 집회 정보를 안내해 드립니다."
        elif alarm_status_str == 'off':
            is_alarm_on = False
            msg = "🔕 매일 아침 알림이 꺼졌습니다.\이동 경로 집회 알림이 더 이상 발송되지 않습니다."
        else:
            return {
                "version": "2.0",
                "template": {
                    "outputs": [{"simpleText": {"text": f"올바르지 않은 알림 설정 값입니다 ('{alarm_status_str}'). 'on' 또는 'off'여야 합니다."}}]
                }
            }

        logger.info(f"📝 알림 설정 변경: user_id={user_id}, status={alarm_status_str}")

        # 통합된 사용자 동기화 로직 사용 (사용자가 없을 경우 대비)
        UserService.sync_kakao_user(bot_user_key, plusfriend_key, db)

        # 설정 업데이트
        result = UserService.update_alarm_setting(user_id, is_alarm_on, db)

        if result["success"]:
            return {
                "version": "2.0",
                "template": {
                    "outputs": [
                        {
                            "simpleText": {
                                "text": msg
                            }
                        }
                    ]
                }
            }
        else:
            return {
                "version": "2.0",
                "template": {
                    "outputs": [{"simpleText": {"text": result.get("error", "알람 설정 업데이트에 실패했습니다.")}}]
                }
            }

    except Exception as e:
        logger.exception("알람 설정 중 시스템 오류 발생")
        return {
            "version": "2.0",
            "template": {
                "outputs": [{"simpleText": {"text": "시스템 오류가 발생했습니다. 잠시 후 다시 시도해주세요."}}]
            }
        }


async def save_route_to_db(user_id: str, departure: str, arrival: str):
    """백그라운드 작업: 경로 정보만 업데이트"""
    from app.database.connection import get_db_connection
    try:
        with get_db_connection() as conn:
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

@router.post("/save_marked_bus")
async def save_marked_bus_users(
    request: dict,
    db: sqlite3.Connection = Depends(get_db)
):
    """
    사용자 marked_bus(자주 타는 버스) 저장 (Skill Block 전용)
    - action.params.marked_bus 사용
    """
    logger.info(f"🔍 /users/save_marked_bus 요청 body: {request}")

    bot_user_key = None
    plusfriend_key = None

    if 'userRequest' in request:
        user_info = request['userRequest']['user']
        bot_user_key = user_info.get('id')
        properties = user_info.get('properties', {})
        plusfriend_key = properties.get('plusfriendUserKey')
    else:
        bot_user_key = request.get('userId', 'test-user')
        plusfriend_key = request.get('plusfriendUserKey')

    user_id = plusfriend_key if plusfriend_key else bot_user_key

    if not user_id:
        logger.warning("save_marked_bus 요청에서 사용자 식별 정보(bot_user_key/plusfriend_key)가 누락되었습니다.")
        return {
            "version": "2.0",
            "template": {
                "outputs": [
                    {"simpleText": {"text": "사용자 식별 정보를 찾을 수 없습니다.\n카카오톡에서 다시 시도해 주세요."}}
                ]
            }
        }

    marked_bus = request.get('action', {}).get('params', {}).get('marked_bus', '')
    marked_bus = (marked_bus or "").strip()

    if not marked_bus:
        return {
            "version": "2.0",
            "template": {
                "outputs": [
                    {"simpleText": {"text": "🚌 버스 번호가 비어있어요. 예: 7016"}}
                ]
            }
        }

    try:
        # 사용자 동기화
        UserService.sync_kakao_user(bot_user_key, plusfriend_key, db)

        # 즉시 저장
        result = await UserService.update_marked_bus(
            user_id=user_id,
            marked_bus=marked_bus,
            db=db
        )

        if result["success"]:
            return {
                "version": "2.0",
                "template": {
                    "outputs": [
                        {
                            "simpleText": {
                                "text": (
                                    f"✅ 자주 타는 버스가 등록되었습니다!\n"
                                    f"🚌 {marked_bus}\n\n"
                                    "🔄 변경하고 싶으면 다시 등록해 주세요."
                                )
                            }
                        }
                    ]
                }
            }
        else:
            logger.warning(f"marked_bus 저장 실패 - user_id: {user_id}, error: {result.get('error')}")
            return {
                "version": "2.0",
                "template": {
                    "outputs": [
                        {
                            "simpleText": {
                                "text": "버스 저장에 실패했습니다. 잠시 후 다시 시도해주세요."
                            }
                        }
                    ]
                }
            }

    except Exception as e:
        logger.exception("save_marked_bus 처리 중 오류 발생")
        return {
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": "시스템 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
                        }
                    }
                ]
            }
        }