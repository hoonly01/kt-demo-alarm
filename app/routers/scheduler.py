"""스케줄러 관련 라우터"""
from fastapi import APIRouter, HTTPException
import logging

from app.utils.scheduler_utils import get_scheduler_status

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scheduler", tags=["scheduler"])


@router.get("/status")
async def scheduler_status():
    """스케줄러 상태 조회"""
    try:
        status = get_scheduler_status()
        return {
            "scheduler": status,
            "message": "스케줄러 상태 조회 성공"
        }
    except Exception as e:
        logger.error(f"스케줄러 상태 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="스케줄러 상태 조회 실패")


@router.post("/manual-test")
async def manual_schedule_test():
    """
    수동 스케줄 테스트 실행
    개발/테스트용으로 스케줄된 작업을 즉시 실행
    """
    try:
        # 스케줄된 함수들을 수동으로 실행
        from app.database.connection import DATABASE_PATH
        import sqlite3
        
        logger.info("🧪 수동 스케줄 테스트 시작")
        
        # scheduled_route_check 함수 실행
        from main import scheduled_route_check
        await scheduled_route_check()
        
        return {
            "message": "수동 스케줄 테스트가 성공적으로 실행되었습니다",
            "test_completed": True
        }
        
    except Exception as e:
        logger.error(f"수동 스케줄 테스트 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"테스트 실행 실패: {str(e)}")