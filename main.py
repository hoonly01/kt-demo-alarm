"""
KT Demo Alarm API - Main Application

모듈화된 FastAPI 애플리케이션의 진입점
Router-Service-Repository 패턴을 적용한 깔끔한 아키텍처
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import logging
import os

# 분리된 모듈들 import
from app.database.connection import init_db
from app.utils.scheduler_utils import (
    scheduler, setup_scheduler, start_scheduler, shutdown_scheduler
)
from app.routers import users, events, alarms, kakao, kakao_skills
from app.routers import scheduler as scheduler_router
from app.routers.bus_notice import router as bus_router
from app.config.settings import settings, setup_logging
from app.services.crawling_service import CrawlingService
from app.services.bus_notice_service import BusNoticeService

from app.models.responses import HealthCheckResponse

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
    
    # 버스 알림 서비스 초기화
    await BusNoticeService.initialize()

    
    yield
    
    # 애플리케이션 종료 시 실행
    logger.info("🛑 KT Demo Alarm API 종료")
    shutdown_scheduler()


# FastAPI 앱 설정
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
    KT 종로구 집회 알림 시스템 API
    
    ## 기능
    * **집회 데이터 크롤링**: SMPA 사이트에서 자동 크롤링
    * **사용자 경로 관리**: 출발지-도착지 경로 등록 및 관리
    * **실시간 알림**: 경로 상 집회 발견 시 자동 알림 전송
    * **알림 상태 추적**: 알림 전송 상태 실시간 모니터링
    * **스케줄러**: 자동 크롤링 및 경로 확인 스케줄링
    
    ## 아키텍처
    Router-Service-Repository 패턴을 적용한 깔끔한 구조
    """,
    lifespan=lifespan,
    responses={
        400: {"description": "Bad Request", "model": None},
        404: {"description": "Not Found", "model": None}, 
        500: {"description": "Internal Server Error", "model": None}
    }
)

# 정적 파일 마운트 (버스 노선 이미지 전용)
os.makedirs("topis_attachments/route_images", exist_ok=True)
app.mount("/static", StaticFiles(directory="topis_attachments/route_images"), name="static")

# 라우터 등록
app.include_router(users.router)
app.include_router(events.router)
app.include_router(alarms.router)
app.include_router(kakao.router)
app.include_router(kakao_skills.router)  # 카카오톡 Skill Block (prefix 없음)
app.include_router(scheduler_router.router)
app.include_router(bus_router)


@app.get("/", response_model=HealthCheckResponse, tags=["Health"])
def read_root():
    """서버 헬스체크 엔드포인트
    
    애플리케이션이 정상적으로 실행 중인지 확인합니다.
    """
    return HealthCheckResponse(
        message="KT Demo Alarm API is running!",
        version=settings.APP_VERSION,
        status="healthy"
    )




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