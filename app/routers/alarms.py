"""알림 관련 라우터"""
from fastapi import APIRouter, Depends, HTTPException
import sqlite3
from typing import Dict, Any
import logging

from app.models.alarm import AlarmRequest, FilteredAlarmRequest
from app.database.connection import get_db
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/alarms", tags=["alarms"])


@router.post("/send")
async def send_individual_alarm(alarm_request: AlarmRequest):
    """개별 사용자에게 알림 전송"""
    # 이벤트 데이터 검증
    validation = NotificationService.validate_event_data(
        alarm_request.event_name, 
        alarm_request.data
    )
    
    if not validation["valid"]:
        raise HTTPException(status_code=400, detail=validation["error"])
    
    result = await NotificationService.send_individual_alarm(alarm_request)
    
    if result["success"]:
        return {
            "message": "알림이 성공적으로 전송되었습니다",
            "user_id": alarm_request.user_id,
            "event_name": alarm_request.event_name
        }
    else:
        raise HTTPException(status_code=500, detail=result["error"])


@router.post("/send-to-all")
async def send_alarm_to_all(
    event_name: str,
    data: Dict[str, Any],
    db: sqlite3.Connection = Depends(get_db)
):
    """전체 활성 사용자에게 알림 전송"""
    try:
        cursor = db.cursor()
        cursor.execute("SELECT bot_user_key FROM users WHERE active = 1")
        
        user_ids = [row[0] for row in cursor.fetchall()]
        
        if not user_ids:
            raise HTTPException(status_code=404, detail="활성 사용자가 없습니다")
        
        result = await NotificationService.send_bulk_alarm(
            user_ids=user_ids,
            event_name=event_name,
            data=data
        )
        
        return {
            "message": f"전체 알림 전송 완료",
            "total_users": result["total_users"],
            "sent": result["total_sent"],
            "failed": result["total_failed"]
        }
        
    except Exception as e:
        logger.error(f"전체 알림 전송 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send-filtered")
async def send_filtered_alarm(
    request: FilteredAlarmRequest,
    db: sqlite3.Connection = Depends(get_db)
):
    """필터링된 사용자에게 알림 전송"""
    try:
        cursor = db.cursor()
        
        # 기본 쿼리
        query = "SELECT bot_user_key FROM users WHERE active = 1"
        params = []
        
        # 필터 조건 추가
        if request.filter_location:
            query += " AND location LIKE ?"
            params.append(f"%{request.filter_location}%")
        
        if request.filter_marked_bus:
            query += " AND marked_bus = ?"
            params.append(request.filter_marked_bus)
        
        if request.filter_has_route:
            if request.filter_has_route:
                query += " AND departure_x IS NOT NULL AND arrival_x IS NOT NULL"
            else:
                query += " AND (departure_x IS NULL OR arrival_x IS NULL)"
        
        cursor.execute(query, params)
        user_ids = [row[0] for row in cursor.fetchall()]
        
        if not user_ids:
            raise HTTPException(status_code=404, detail="필터 조건에 맞는 사용자가 없습니다")
        
        result = await NotificationService.send_bulk_alarm(
            user_ids=user_ids,
            event_name=request.event_name,
            data=request.data
        )
        
        return {
            "message": f"필터링된 알림 전송 완료",
            "filter_applied": {
                "location": request.filter_location,
                "marked_bus": request.filter_marked_bus,
                "has_route": request.filter_has_route
            },
            "total_users": result["total_users"],
            "sent": result["total_sent"],
            "failed": result["total_failed"]
        }
        
    except Exception as e:
        logger.error(f"필터링된 알림 전송 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{task_id}")
async def get_alarm_status(task_id: str):
    """알림 전송 상태 확인"""
    # TODO: 실제 상태 추적 시스템 구현 필요
    # 현재는 placeholder 응답
    return {
        "task_id": task_id,
        "status": "completed",
        "message": "상태 추적 시스템 구현 예정"
    }