"""스케줄러 관련 라우터"""
from fastapi import APIRouter, HTTPException
import logging
from app.services.crawling_service import CrawlingService
from app.services.event_service import EventService
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
        from app.services.event_service import EventService
        await EventService.scheduled_route_check()
        
        return {
            "message": "수동 스케줄 테스트가 성공적으로 실행되었습니다",
            "test_completed": True
        }
        
    except Exception as e:
        logger.error(f"수동 스케줄 테스트 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"테스트 실행 실패: {str(e)}")

@router.post("/crawl-events")
async def crawl_events():
    """
    ✅ v4.2: 집회 데이터 크롤링 수동 트리거
    
    SMPA + SPATIC에서 데이터를 크롤링하고 지오코딩을 수행합니다.
    
    Returns:
        dict: 크롤링 결과 (성공 여부, 저장된 데이터 수 등)
    """
    logger.info("🔄 [API] 크롤링 엔드포인트 호출됨")
    
    try:
        # 크롤링 서비스 실행
        result = await CrawlingService.crawl_and_sync_events()
        
        logger.info(f"✅ [API] 크롤링 완료: {result}")
        return result
        
    except Exception as e:
        logger.error(f"❌ [API] 크롤링 실패: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "total_crawled": 0
        }
