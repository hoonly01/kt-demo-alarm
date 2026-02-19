"""스케줄러 관련 유틸리티 함수들"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.config.settings import settings

logger = logging.getLogger(__name__)

# 전역 스케줄러 인스턴스
scheduler = AsyncIOScheduler()


def setup_scheduler(crawling_func, route_check_func, bus_crawling_func=None):
    """
    스케줄러 설정 및 작업 등록
    
    Args:
        crawling_func: 크롤링 함수 (SMPA 집회 데이터)
        route_check_func: 경로 확인 함수
        bus_crawling_func: 버스 통제 공지 재크롤링 함수 (선택)
    """
    # 설정된 시간에 SMPA 집회 데이터 크롤링 및 동기화
    scheduler.add_job(
        crawling_func,
        CronTrigger(hour=settings.CRAWLING_HOUR, minute=settings.CRAWLING_MINUTE),
        id="daily_crawling_sync",
        name="Daily SMPA Crawling & Sync",
        replace_existing=True
    )
    
    # 설정된 시간에 정기 집회 확인 스케줄 추가
    scheduler.add_job(
        route_check_func,
        CronTrigger(hour=settings.ROUTE_CHECK_HOUR, minute=settings.ROUTE_CHECK_MINUTE),
        id="daily_route_check",
        name="Daily Route Rally Check",
        replace_existing=True
    )
    
    # 버스 통제 공지 재크롤링 (매일 CRAWLING_HOUR:CRAWLING_MINUTE)
    if bus_crawling_func:
        scheduler.add_job(
            bus_crawling_func,
            CronTrigger(hour=settings.CRAWLING_HOUR, minute=settings.CRAWLING_MINUTE),
            id="daily_bus_crawling",
            name="Daily Bus Control Crawling",
            replace_existing=True
        )

    bus_job_info = f", {settings.CRAWLING_HOUR:02d}:{settings.CRAWLING_MINUTE:02d} 버스 통제 공지 갱신" if bus_crawling_func else ""
    logger.info(f"🚀 스케줄러 작업 등록 완료: 매일 {settings.CRAWLING_HOUR:02d}:{settings.CRAWLING_MINUTE:02d} 크롤링, {settings.ROUTE_CHECK_HOUR:02d}:{settings.ROUTE_CHECK_MINUTE:02d} 경로 확인{bus_job_info}")


def start_scheduler():
    """스케줄러 시작"""
    if not scheduler.running:
        scheduler.start()
        logger.info("🚀 스케줄러 시작됨")


def shutdown_scheduler():
    """스케줄러 종료"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("🛑 스케줄러 종료됨")


def get_scheduler_status():
    """스케줄러 상태 조회"""
    if not scheduler.running:
        return {"status": "stopped", "jobs": []}
    
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger)
        })
    
    return {
        "status": "running",
        "jobs": jobs
    }