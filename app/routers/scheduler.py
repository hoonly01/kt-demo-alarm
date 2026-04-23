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
