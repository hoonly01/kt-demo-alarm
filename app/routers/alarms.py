"""알림 관련 라우터"""
from fastapi import APIRouter, Depends, HTTPException, Query
import sqlite3
from typing import Dict, Any, List
import logging

from app.models.alarm import AlarmRequest, FilteredAlarmRequest
from app.database.connection import get_db
from app.services.notification_service import NotificationService
from app.services.alarm_status_service import AlarmStatusService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/alarms", tags=["alarms"])


@router.post("/send")
async def send_individual_alarm(alarm_request: AlarmRequest):
    """개별 사용자에게 알림 전송"""
    # 1. 이벤트 데이터 검증
    validation = NotificationService.validate_event_data(
        alarm_request.event_name, 
        alarm_request.data
    )
    
    if not validation["valid"]:
        raise HTTPException(status_code=400, detail=validation["error"])
    
    # 2. 알림 작업 생성
    task_id = AlarmStatusService.create_alarm_task(
        alarm_type="individual",
        total_recipients=1,
        request_data=alarm_request.model_dump()
    )
    
    # 3. 상태를 processing으로 업데이트
    AlarmStatusService.update_alarm_task_status(task_id, "processing")
    
    try:
        # 4. 알림 전송
        result = await NotificationService.send_individual_alarm(alarm_request)
        
        if result["success"]:
            # 5. 성공 시 상태 업데이트
            AlarmStatusService.update_alarm_task_status(
                task_id, "completed", successful_sends=1
            )
            return {
                "message": "알림이 성공적으로 전송되었습니다",
                "task_id": task_id,
                "user_id": alarm_request.user_id,
                "event_name": alarm_request.event_name
            }
        else:
            # 6. 실패 시 상태 업데이트
            AlarmStatusService.update_alarm_task_status(
                task_id, "failed", failed_sends=1, 
                error_messages=[result["error"]]
            )
            raise HTTPException(status_code=500, detail=result["error"])
            
    except Exception as e:
        # 7. 예외 발생 시 상태 업데이트
        AlarmStatusService.update_alarm_task_status(
            task_id, "failed", failed_sends=1, 
            error_messages=[str(e)]
        )
        raise HTTPException(status_code=500, detail=str(e))


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
    status_info = AlarmStatusService.get_alarm_task_status(task_id)
    
    if not status_info:
        raise HTTPException(
            status_code=404,
            detail=f"알림 작업 ID {task_id}를 찾을 수 없습니다"
        )
    
    return {
        "task_id": status_info["task_id"],
        "status": status_info["status"],
        "alarm_type": status_info["alarm_type"],
        "progress": {
            "total_recipients": status_info["total_recipients"],
            "successful_sends": status_info["successful_sends"] or 0,
            "failed_sends": status_info["failed_sends"] or 0,
            "success_rate": status_info["success_rate"]
        },
        "timestamps": {
            "created_at": status_info["created_at"],
            "updated_at": status_info["updated_at"],
            "completed_at": status_info["completed_at"]
        },
        "error_messages": status_info["error_messages"],
        "event_id": status_info["event_id"]
    }


@router.get("/status")
async def get_recent_alarm_tasks(limit: int = Query(50, ge=1, le=100)):
    """최근 알림 작업 목록 조회"""
    tasks = AlarmStatusService.get_recent_alarm_tasks(limit)
    
    return {
        "tasks": tasks,
        "total": len(tasks),
        "limit": limit
    }


@router.post("/cleanup-old-tasks")
async def cleanup_old_alarm_tasks(days: int = Query(30, ge=1, le=365)):
    """오래된 알림 작업 정리"""
    deleted_count = AlarmStatusService.cleanup_old_tasks(days)
    
    return {
        "message": f"{deleted_count}개의 오래된 알림 작업이 정리되었습니다",
        "deleted_count": deleted_count,
        "retention_days": days
    }