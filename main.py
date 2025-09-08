"""
KT Demo Alarm API - Main Application

모듈화된 FastAPI 애플리케이션의 진입점
Router-Service-Repository 패턴을 적용한 깔끔한 아키텍처
"""

from fastapi import FastAPI
import logging
import sqlite3
from datetime import datetime

# 분리된 모듈들 import
from app.database.connection import init_db, DATABASE_PATH
from app.utils.scheduler_utils import (
    scheduler, setup_scheduler, start_scheduler, shutdown_scheduler
)
from app.routers import users, events, alarms, kakao
from app.routers import scheduler as scheduler_router
from app.config.settings import settings, setup_logging
from apscheduler.triggers.cron import CronTrigger

# 로깅 설정
setup_logging()
logger = logging.getLogger(__name__)

# FastAPI 앱 설정
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="KT 종로구 집회 알림 시스템 API - Router-Service-Repository 패턴 적용"
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


async def scheduled_route_check():
    """
    매일 아침 자동 실행되는 경로 기반 집회 확인 함수
    """
    logger.info("=== 정기 집회 확인 시작 ===")
    
    try:
        from app.services.event_service import EventService
        
        # 데이터베이스 연결
        db = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        
        # 활성 사용자 조회
        cursor = db.cursor()
        cursor.execute('''
            SELECT bot_user_key FROM users 
            WHERE active = 1 
            AND departure_x IS NOT NULL 
            AND departure_y IS NOT NULL
            AND arrival_x IS NOT NULL 
            AND arrival_y IS NOT NULL
        ''')
        
        users = cursor.fetchall()
        total_notifications = 0
        
        logger.info(f"경로 등록된 사용자 {len(users)}명 확인 중...")
        
        for user_row in users:
            user_id = user_row[0]
            
            try:
                # EventService를 통한 경로 확인 (자동 알림 포함)
                result = await EventService.check_route_events(user_id, auto_notify=True, db=db)
                
                if result.events_found:
                    total_notifications += 1
                    logger.info(f"✅ {user_id}: {len(result.events_found)}개 집회 감지 및 알림 전송")
                    
            except Exception as e:
                logger.error(f"❌ 사용자 {user_id} 처리 실패: {str(e)}")
        
        db.close()
        
        logger.info(f"=== 정기 집회 확인 완료: {total_notifications}명에게 알림 전송 ===")
        
    except Exception as e:
        logger.error(f"정기 집회 확인 중 오류 발생: {str(e)}")


@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 실행"""
    logger.info("🚀 KT Demo Alarm API 시작")
    
    # 데이터베이스 초기화
    init_db()
    
    # 스케줄러 설정 및 시작
    setup_scheduler(
        crawling_func=lambda: logger.info("크롤링 스케줄 실행 (구현 예정)"),
        route_check_func=scheduled_route_check
    )
    start_scheduler()
    
    logger.info(f"스케줄러가 시작되었습니다: {settings.CRAWLING_HOUR:02d}:{settings.CRAWLING_MINUTE:02d} 크롤링, {settings.ROUTE_CHECK_HOUR:02d}:{settings.ROUTE_CHECK_MINUTE:02d} 경로체크")


@app.on_event("shutdown")
async def shutdown_event():
    """애플리케이션 종료 시 실행"""
    logger.info("🛑 KT Demo Alarm API 종료")
    shutdown_scheduler()


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