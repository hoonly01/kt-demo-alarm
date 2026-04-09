"""이벤트/집회 관련 라우터"""
from fastapi import APIRouter, Depends, HTTPException, Query
import sqlite3
from typing import List, Optional
import logging
import asyncio

from app.models.event import EventCreate, EventResponse, RouteEventCheck
from app.database.connection import get_db
from app.services.event_service import EventService
from app.services.auth_service import verify_api_key

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/events", tags=["events"])


@router.post("", response_model=EventResponse)
async def create_event(
    event_data: EventCreate, 
    db: sqlite3.Connection = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """새로운 집회/이벤트 생성"""
    result = EventService.create_event(event_data, db)
    
    if result["success"]:
        # 생성된 이벤트 조회
        cursor = db.cursor()
        cursor.execute("SELECT * FROM events WHERE id = ?", (result["event_id"],))
        row = cursor.fetchone()
        
        if row:
            return EventResponse(
                id=row[0], title=row[1], description=row[2], location_name=row[3],
                location_address=row[4], latitude=row[5], longitude=row[6],
                start_date=row[7], end_date=row[8], category=row[9],
                severity_level=row[10], status=row[11], created_at=row[12], updated_at=row[13]
            )
    
    raise HTTPException(status_code=400, detail=result.get("error", "이벤트 생성에 실패했습니다"))


@router.get("", response_model=List[EventResponse])
async def get_events(
    category: Optional[str] = Query(None, description="카테고리 필터"),
    status: Optional[str] = Query("active", description="상태 필터"),
    limit: int = Query(100, description="조회 제한", ge=1, le=1000),
    db: sqlite3.Connection = Depends(get_db)
):
    """집회 목록 조회"""
    return EventService.get_events(category, status, limit, db)


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
                                "안전한 이동 되세요! 😊"
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
        + "\n\n우회 경로를 고려해주세요."
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


@router.post("/auto-check-all-routes")
async def auto_check_all_routes(
    db: sqlite3.Connection = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """
    모든 사용자의 경로를 확인하고 집회 발견 시 자동 알림 전송
    (관리자용 또는 수동 트리거)
    """
    cursor = db.cursor()

    # 경로 등록된 활성 사용자 조회 (plusfriend_user_key 우선)
    cursor.execute('''
        SELECT COALESCE(plusfriend_user_key, bot_user_key) as user_id
        FROM users
        WHERE active = 1
        AND is_alarm_on = 1
        AND departure_x IS NOT NULL
        AND departure_y IS NOT NULL
        AND arrival_x IS NOT NULL
        AND arrival_y IS NOT NULL
        AND (plusfriend_user_key IS NOT NULL OR bot_user_key IS NOT NULL)
    ''')
    
    users = cursor.fetchall()
    
    # 병렬 처리를 위한 태스크 생성
    async def process_user(user_id: str):
        try:
            # 각 사용자의 경로 확인 (자동 알림 포함)
            result = await EventService.check_route_events(user_id, auto_notify=True, db=db)
            return {
                "user_id": user_id,
                "events_found": len(result.events_found),
                "success": True
            }
        except Exception as e:
            logger.error(f"사용자 {user_id} 처리 실패: {str(e)}")
            return {
                "user_id": user_id,
                "success": False,
                "error": str(e)
            }
    
    # 모든 사용자에 대한 작업을 병렬로 실행
    tasks = [process_user(user_row[0]) for user_row in users]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 예외 처리 결과 변환
    processed_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            user_id = users[i][0]
            logger.error(f"사용자 {user_id} 처리 중 예외: {str(result)}")
            processed_results.append({
                "user_id": user_id,
                "success": False,
                "error": str(result)
            })
        else:
            processed_results.append(result)
    
    results = processed_results
    
    success_count = sum(1 for r in results if r["success"])
    total_events = sum(r.get("events_found", 0) for r in results if r["success"])
    
    return {
        "message": "모든 사용자 경로 확인 완료",
        "total_users": len(users),
        "success_count": success_count,
        "total_events_found": total_events,
        "results": results
    }


@router.post("/crawl-and-sync")
async def crawl_and_sync_events(api_key: str = Depends(verify_api_key)):
    """SMPA 집회 데이터 크롤링 및 동기화"""
    try:
        from app.services.crawling_service import CrawlingService
        result = await CrawlingService.crawl_and_sync_events()
        
        if result["success"]:
            return {
                "message": result["message"],
                "total_crawled": result["total_crawled"],
                "status": "completed"
            }
        else:
            raise HTTPException(
                status_code=500, 
                detail=f"크롤링 실패: {result['error']}"
            )
        
    except Exception as e:
        logger.error(f"크롤링 중 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=f"크롤링 실패: {str(e)}")


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