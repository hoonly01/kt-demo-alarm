"""스케줄러 관련 유틸리티 함수들"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

# 전역 스케줄러 인스턴스
scheduler = AsyncIOScheduler()


def setup_scheduler(crawling_func, route_check_func):
    """
    스케줄러 설정 및 작업 등록
    
    Args:
        crawling_func: 크롤링 함수
        route_check_func: 경로 확인 함수
    """
    # 매일 오전 8시 30분에 SMPA 집회 데이터 크롤링 및 동기화
    scheduler.add_job(
        crawling_func,
        CronTrigger(hour=8, minute=30),  # 매일 08:30
        id="daily_crawling_sync",
        name="Daily SMPA Crawling & Sync",
        replace_existing=True
    )
    
    # 매일 오전 7시에 정기 집회 확인 스케줄 추가
    scheduler.add_job(
        route_check_func,
        CronTrigger(hour=7, minute=0),  # 매일 07:00
        id="daily_route_check",
        name="Daily Route Rally Check",
        replace_existing=True
    )
    
    logger.info("🚀 스케줄러 작업 등록 완료: 매일 08:30 크롤링, 07:00 경로 확인")


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