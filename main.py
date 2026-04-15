"""
KT Demo Alarm API - Main Application

모듈화된 FastAPI 애플리케이션의 진입점
Router-Service-Repository 패턴을 적용한 깔끔한 아키텍처
"""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
import logging
import os

# 분리된 모듈들 import
from app.database.connection import init_db
from app.utils.scheduler_utils import (
    scheduler, setup_scheduler, start_scheduler, shutdown_scheduler
)
from app.routers import users, events, alarms, kakao, kakao_skills, admin
from app.routers import scheduler as scheduler_router
from app.routers.bus_notice import router as bus_router
from app.config.settings import settings, setup_logging
from app.services.crawling_service import CrawlingService
from app.services.bus_notice_service import BusNoticeService

from app.models.responses import HealthCheckResponse

# 로깅 설정
setup_logging()
logger = logging.getLogger(__name__)


def _log_bus_notice_init_result(task: asyncio.Task) -> None:
    """백그라운드 초기화 태스크 종료 상태를 기록한다."""
    if task.cancelled():
        logger.info("🛑 BusNoticeService 초기화 태스크가 취소되었습니다.")
        return

    exc = task.exception()
    if exc:
        logger.error(f"❌ BusNoticeService 백그라운드 초기화 실패: {exc}")
        return

    logger.info("✅ BusNoticeService 백그라운드 초기화 완료")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 애플리케이션 생명주기 관리"""
    # 애플리케이션 시작 시 실행
    logger.info("🚀 KT Demo Alarm API 시작")
    
    # 데이터베이스 초기화
    init_db()
    
    # 스케줄러 설정 및 시작
    from app.services.event_service import EventService
    from app.services.zone_alarm_service import ZoneAlarmService
    setup_scheduler(
        crawling_func=CrawlingService.crawl_and_sync_events,  # 실제 크롤링 서비스 연동
        route_check_func=EventService.scheduled_route_check,
        bus_crawling_func=BusNoticeService.refresh,           # 버스 통제 공지 재크롤링
        zone_check_func=ZoneAlarmService.scheduled_zone_check,
    )
    start_scheduler()

    logger.info(
        f"스케줄러가 시작되었습니다: "
        f"{settings.CRAWLING_HOUR:02d}:{settings.CRAWLING_MINUTE:02d} 크롤링, "
        f"{settings.ROUTE_CHECK_HOUR:02d}:{settings.ROUTE_CHECK_MINUTE:02d} 경로체크, "
        f"{settings.ZONE_CHECK_HOUR:02d}:{settings.ZONE_CHECK_MINUTE:02d} 구역체크"
    )

    # 버스 알림 초기화는 백그라운드로 넘겨서 헬스체크를 즉시 받을 수 있게 한다.
    app.state.bus_notice_init_task = asyncio.create_task(BusNoticeService.initialize())
    app.state.bus_notice_init_task.add_done_callback(_log_bus_notice_init_result)
    
    yield

    # 애플리케이션 종료 시 실행
    logger.info("🛑 KT Demo Alarm API 종료")

    bus_notice_init_task = getattr(app.state, "bus_notice_init_task", None)
    if bus_notice_init_task and not bus_notice_init_task.done():
        bus_notice_init_task.cancel()
        try:
            await bus_notice_init_task
        except asyncio.CancelledError:
            logger.info("🛑 종료 중 BusNoticeService 초기화 태스크를 정리했습니다.")

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
app.include_router(admin.router)


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

@app.post("/mock_callback")
async def mock_callback_receiver(request: Request):
    """콜백 결과를 터미널에 예쁘게 출력해주는 테스트용 엔드포인트"""
    import json
    try:
        body = await request.json()
        print("\n" + "═"*50)
        print("📢 [실전 시뮬레이션 결과] - 카톡 유저가 받게 될 메시지")
        print("═"*50)
        print(json.dumps(body, indent=2, ensure_ascii=False))
        print("═"*50 + "\n")
    except Exception as e:
        print(f"콜백 수신 중 오류: {e}")
    return {"status": "ok"}




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
