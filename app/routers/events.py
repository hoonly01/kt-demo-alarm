"""이벤트/집회 관련 라우터"""
from fastapi import APIRouter, Depends, HTTPException, Query
import sqlite3
from typing import List, Optional
import logging
import asyncio

from app.models.event import EventCreate, EventResponse, RouteEventCheck
from app.database.connection import get_db
from app.services.event_service import EventService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/events", tags=["events"])


@router.post("", response_model=EventResponse)
async def create_event(event_data: EventCreate, db: sqlite3.Connection = Depends(get_db)):
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


@router.get("/check-route/{user_id}", response_model=RouteEventCheck)
async def check_user_route_events(
    user_id: str, 
    auto_notify: bool = Query(False, description="자동 알림 여부"),
    db: sqlite3.Connection = Depends(get_db)
):
    """사용자의 경로상에 있는 집회들을 확인"""
    return await EventService.check_route_events(user_id, auto_notify, db)


@router.post("/auto-check-all-routes")
async def auto_check_all_routes(db: sqlite3.Connection = Depends(get_db)):
    """모든 사용자의 경로를 확인하고 집회 발견 시 자동 알림 전송"""
    cursor = db.cursor()
    
    # 경로 등록된 활성 사용자 조회
    cursor.execute('''
        SELECT bot_user_key FROM users 
        WHERE active = 1 
        AND departure_x IS NOT NULL 
        AND departure_y IS NOT NULL
        AND arrival_x IS NOT NULL 
        AND arrival_y IS NOT NULL
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
async def crawl_and_sync_events():
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


@router.get("/upcoming-protests", response_model=List[EventResponse])
async def get_upcoming_protests(
    limit: int = Query(5, description="조회 제한", ge=1, le=50),
    db: sqlite3.Connection = Depends(get_db)
):
    """다가오는 집회 정보 조회"""
    return EventService.get_upcoming_events(limit, db)


@router.get("/today-protests", response_model=List[EventResponse])
async def get_today_protests(db: sqlite3.Connection = Depends(get_db)):
    """오늘 집회 정보 조회"""
    return EventService.get_today_events(db)