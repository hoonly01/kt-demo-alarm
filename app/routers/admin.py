import os
import secrets
import asyncio
import logging
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from app.database.connection import get_db_connection
from app.config.settings import settings
import math

from app.utils.scheduler_utils import get_scheduler_status
from app.services.event_service import EventService
from app.services.bus_notice_service import BusNoticeService
from app.services.crawling_service import CrawlingService

router = APIRouter(
    prefix="/admin",
    tags=["admin"]
)

security = HTTPBasic()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"))

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    # Using environment variables for admin credentials.
    # These must be configured via environment (.env, deployment config).
    admin_user = settings.ADMIN_USER
    admin_pass = settings.ADMIN_PASS
    
    # Fail fast if admin credentials are not configured
    if not admin_user or not admin_user.strip() or not admin_pass or not admin_pass.strip():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Admin credentials are not configured on the server",
        )
    
    correct_username = secrets.compare_digest(credentials.username, admin_user)
    correct_password = secrets.compare_digest(credentials.password, admin_pass)
    
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

def fetch_recent_events() -> List[Dict[str, Any]]:
    # Synchronous DB query
    with get_db_connection() as conn:
        conn.row_factory = dict_factory
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, title, location_name, severity_level, start_date, created_at, status 
            FROM events 
            ORDER BY id DESC 
            LIMIT 100
        """)
        return cursor.fetchall()

def fetch_recent_alarms() -> List[Dict[str, Any]]:
    # Synchronous DB query
    with get_db_connection() as conn:
        conn.row_factory = dict_factory
        cursor = conn.cursor()
        cursor.execute("""
            SELECT task_id, alarm_type, status, total_recipients, successful_sends, failed_sends, created_at
            FROM alarm_tasks 
            ORDER BY created_at DESC 
            LIMIT 100
        """)
        return cursor.fetchall()

# Helper for sqlite row to dict
def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def get_total_users() -> int:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        result = cursor.fetchone()
        return result[0] if result else 0

def fetch_paginated_users(limit: int, offset: int) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        conn.row_factory = dict_factory
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, bot_user_key, plusfriend_user_key, open_id, active, is_alarm_on, 
                   departure_name, arrival_name, marked_bus, 
                   COALESCE(favorite_zone, 0) as favorite_zone,
                   first_message_at as created_at, message_count 
            FROM users 
            ORDER BY id DESC 
            LIMIT ? OFFSET ?
        """, (limit, offset))
        return cursor.fetchall()

@router.get("/dashboard")
async def dashboard(
    request: Request, 
    page: int = Query(1, ge=1, description="Page number"), 
    page_size: int = Query(50, ge=1, le=200, description="Items per page"), 
    _username: str = Depends(verify_admin)
):
    """Render the back-office dashboard"""
    
    offset = (page - 1) * page_size
    
    # Run database queries in parallel
    events, alarms, users, total_users = await asyncio.gather(
        asyncio.to_thread(fetch_recent_events),
        asyncio.to_thread(fetch_recent_alarms),
        asyncio.to_thread(fetch_paginated_users, page_size, offset),
        asyncio.to_thread(get_total_users)
    )
    
    total_pages = math.ceil(total_users / page_size) if total_users > 0 else 1
    
    # Get Scheduler Status
    scheduler_status = get_scheduler_status()
    
    # Calculate some summary statistics
    total_events = len(events)
    total_alarms = len(alarms)
    total_alarms_sent = sum(a.get("total_recipients", 0) for a in alarms)
    successful_sends = sum(a.get("successful_sends", 0) for a in alarms)
    failed_sends = sum(a.get("failed_sends", 0) for a in alarms)
    
    success_rate = 0
    if total_alarms_sent > 0:
        success_rate = round((successful_sends / total_alarms_sent) * 100, 1)

    return templates.TemplateResponse(
        "admin_dashboard.html",
        {
            "request": request,
            "events": events,
            "alarms": alarms,
            "users": users,
            "scheduler_status": scheduler_status,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_users": total_users,
                "total_pages": total_pages,
                "has_previous": page > 1,
                "has_next": page < total_pages,
                "previous_page": page - 1,
                "next_page": page + 1
            },
            "stats": {
                "total_events": total_events,
                "total_alarms": total_alarms,
                "total_alarms_sent": total_alarms_sent,
                "success_rate": success_rate,
                "failed_sends": failed_sends
            }
        }
    )

def _task_exception_handler(task: asyncio.Task):
    try:
        task.result()
    except Exception as e:
        logger.error(f"Background task failed: {e}", exc_info=True)

@router.post("/trigger-crawling")
async def trigger_crawling(_username: str = Depends(verify_admin)):
    """수동으로 서울경찰청 집회 정보 크롤링을 트리거합니다."""
    task = asyncio.create_task(CrawlingService.crawl_and_sync_events())
    task.add_done_callback(_task_exception_handler)
    return {"message": "Success"}

@router.post("/trigger-bus-notice")
async def trigger_bus_notice(_username: str = Depends(verify_admin)):
    """수동으로 TOPIS 버스 우회 공지 크롤링을 트리거합니다."""
    task = asyncio.create_task(BusNoticeService.refresh())
    task.add_done_callback(_task_exception_handler)
    return {"message": "Success"}

@router.post("/trigger-test-alarm-for-user")
async def trigger_test_alarm_for_user(user_id: str = Query(..., description="Target user ID to test"), _username: str = Depends(verify_admin)):
    """수동으로 특정 사용자의 경로 점검 및 알림 발송 로직을 테스트합니다."""
    
    # helper for background task that requires DB connection
    async def _run_route_check_for_user(uid: str):
        import sqlite3
        from app.database.connection import DATABASE_PATH
        db = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        try:
            await EventService.check_route_events(user_id=uid, auto_notify=True, db=db)
        finally:
            db.close()
            
    task = asyncio.create_task(_run_route_check_for_user(user_id))
    task.add_done_callback(_task_exception_handler)
    return {"message": f"Successfully triggered test for user: {user_id}"}
