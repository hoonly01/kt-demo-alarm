"""
KT Demo Alarm API - Main Application

모듈화된 FastAPI 애플리케이션의 진입점
Router-Service-Repository 패턴을 적용한 깔끔한 아키텍처
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
import logging

# 분리된 모듈들 import
from app.database.connection import init_db
from app.utils.scheduler_utils import (
    scheduler, setup_scheduler, start_scheduler, shutdown_scheduler
)
from app.routers import users, events, alarms, kakao
from app.routers import scheduler as scheduler_router
from app.config.settings import settings, setup_logging
from app.services.crawling_service import CrawlingService

# 로깅 설정
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 애플리케이션 생명주기 관리"""
    # 애플리케이션 시작 시 실행
    logger.info("🚀 KT Demo Alarm API 시작")
    
    # 데이터베이스 초기화
    init_db()
    
    # 스케줄러 설정 및 시작
    from app.services.event_service import EventService
    setup_scheduler(
        crawling_func=CrawlingService.crawl_and_sync_events,  # 실제 크롤링 서비스 연동
        route_check_func=EventService.scheduled_route_check
    )
    start_scheduler()
    
    logger.info(f"스케줄러가 시작되었습니다: {settings.CRAWLING_HOUR:02d}:{settings.CRAWLING_MINUTE:02d} 크롤링, {settings.ROUTE_CHECK_HOUR:02d}:{settings.ROUTE_CHECK_MINUTE:02d} 경로체크")
    
    yield
    
    # 애플리케이션 종료 시 실행
    logger.info("🛑 KT Demo Alarm API 종료")
    shutdown_scheduler()


# FastAPI 앱 설정
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="KT 종로구 집회 알림 시스템 API - Router-Service-Repository 패턴 적용",
    lifespan=lifespan
)

# 라우터 등록
app.include_router(users.router)
app.include_router(events.router)
app.include_router(alarms.router)
app.include_router(kakao.router)
app.include_router(scheduler_router.router)


@app.get("/")
def read_root():
    """서버가 살아있는지 확인하는 기본 엔드포인트"""
    return {
        "message": "KT Demo Alarm API is running!",
        "version": settings.APP_VERSION,
        "status": "healthy"
    }




# 애플리케이션 진입점
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower()
    )