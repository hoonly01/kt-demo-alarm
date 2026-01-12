"""사용자 관련 라우터"""
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
import sqlite3
from typing import List, Dict, Any
import logging

from app.models.user import UserPreferences, InitialSetupRequest
from app.database.connection import get_db
from app.services.user_service import UserService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


@router.get("")
async def get_users(db: sqlite3.Connection = Depends(get_db)):
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
                "bot_user_key": row[0],
                "first_message_at": row[1],
                "last_message_at": row[2],
                "message_count": row[3],
                "location": row[4],
                "active": bool(row[5]),
                "marked_bus": row[15],
                "language": row[16]
            }
            
            # 경로 정보가 있는 경우만 포함
            if all([row[8], row[9], row[12], row[13]]):  # departure_x, y, arrival_x, y
                user_data["route_info"] = {
                    "departure": {
                        "name": row[6],
                        "address": row[7],
                        "x": row[8],
                        "y": row[9]
                    },
                    "arrival": {
                        "name": row[10],
                        "address": row[11],
                        "x": row[12],
                        "y": row[13]
                    },
                    "updated_at": row[14]
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

    # 사용자 생성/업데이트
    if 'userRequest' in request:
        from app.services.user_service import UserService
        from app.database.connection import get_db_connection
        with get_db_connection() as db:
            UserService.save_or_update_user(user_id, db, f"경로 등록: {request.get('action', {}).get('params', {}).get('departure', '')} → {request.get('action', {}).get('params', {}).get('arrival', '')}")
    
    # 출발지와 도착지 정보 추출
    departure = request.get('action', {}).get('params', {}).get('departure', '')
    arrival = request.get('action', {}).get('params', {}).get('arrival', '')
    
    # 백그라운드에서 경로 정보 저장
    background_tasks.add_task(save_route_to_db, user_id, departure, arrival)
    
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


@router.post("/initial-setup")
async def initial_setup(request: dict, db: sqlite3.Connection = Depends(get_db)):
    """
    사용자 초기 설정 (Skill Block 전용)
    - Skill Block에서 경로 등록 시 호출
    - plusfriendUserKey를 primary identifier로 사용
    """
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

    # 사용자 정보 저장 (3개 ID 모두 저장)
    from app.database.connection import get_db_connection
    from datetime import datetime

    with get_db_connection() as db_conn:
        cursor = db_conn.cursor()

        # plusfriend_key로 조회 (primary identifier)
        cursor.execute(
            "SELECT id, open_id FROM users WHERE plusfriend_user_key = ?",
            (plusfriend_key,)
        )
        existing = cursor.fetchone()

        if existing:
            # 기존 사용자 업데이트
            logger.info(f"✅ 기존 사용자 발견: plusfriend={plusfriend_key}")
            cursor.execute("""
                UPDATE users
                SET bot_user_key = ?, last_message_at = ?, message_count = message_count + 1
                WHERE plusfriend_user_key = ?
            """, (bot_user_key, datetime.now(), plusfriend_key))
        else:
            # 웹훅 사용자 찾기 시도 (open_id만 있는 경우)
            cursor.execute("""
                SELECT id, open_id FROM users
                WHERE bot_user_key IS NULL AND plusfriend_user_key IS NULL
                LIMIT 1
            """)
            orphan = cursor.fetchone()

            if orphan:
                # 웹훅 사용자 연결
                logger.info(f"✅ 웹훅 사용자 연결: open_id={orphan[1]} → plusfriend={plusfriend_key}")
                cursor.execute("""
                    UPDATE users
                    SET bot_user_key = ?, plusfriend_user_key = ?, last_message_at = ?
                    WHERE id = ?
                """, (bot_user_key, plusfriend_key, datetime.now(), orphan[0]))
            else:
                # 완전 신규 사용자
                logger.info(f"✅ 신규 사용자 생성: plusfriend={plusfriend_key}")
                cursor.execute("""
                    INSERT INTO users (bot_user_key, plusfriend_user_key, first_message_at, last_message_at, message_count, active)
                    VALUES (?, ?, ?, ?, 1, 1)
                """, (bot_user_key, plusfriend_key, datetime.now(), datetime.now()))

        db_conn.commit()

    # 경로 정보 저장
    result = await UserService.save_user_route_info(setup_request, db)

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
        raise HTTPException(status_code=400, detail=result["error"])


async def save_route_to_db(user_id: str, departure: str, arrival: str):
    """백그라운드 작업: 경로 정보 저장"""
    from app.database.connection import DATABASE_PATH
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        user_setup = InitialSetupRequest(
            bot_user_key=user_id,
            departure=departure,
            arrival=arrival
        )
        result = await UserService.save_user_route_info(user_setup, conn)
        conn.close()
        
        if result["success"]:
            logger.info(f"사용자 {user_id} 경로 정보 저장 완료")
        else:
            logger.error(f"사용자 {user_id} 경로 정보 저장 실패: {result.get('error')}")
            
    except Exception as e:
        logger.error(f"경로 정보 저장 중 오류: {str(e)}")