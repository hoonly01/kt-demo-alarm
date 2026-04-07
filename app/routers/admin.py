import os
import secrets
import asyncio
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from app.database.connection import get_db_connection
from app.config.settings import settings
import math

from app.utils.scheduler_utils import get_scheduler_status
from app.services.event_service import EventService
from app.services.bus_notice_service import BusNoticeService

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
            SELECT id, bot_user_key, active, is_alarm_on, 
                   departure_name, arrival_name, marked_bus, 
                   COALESCE(favorite_zone, 0) as favorite_zone,
                   created_at, message_count 
            FROM users 
            ORDER BY id DESC 
            LIMIT ? OFFSET ?
        """, (limit, offset))
        return cursor.fetchall()

@router.get("/dashboard")
async def dashboard(request: Request, page: int = 1, page_size: int = 50, _username: str = Depends(verify_admin)):
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

@router.post("/trigger-crawling")
async def trigger_crawling(_username: str = Depends(verify_admin)):
    """Manually trigger SMPA Rally Crawler"""
    try:
        # Run in background to not block the UI waiting for it
        asyncio.create_task(EventService.collect_smpa_events())
        return {"message": "Success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/trigger-bus-notice")
async def trigger_bus_notice(_username: str = Depends(verify_admin)):
    """Manually trigger TOPIS Bus Notice Crawler"""
    try:
        asyncio.create_task(BusNoticeService.refresh())
        return {"message": "Success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/trigger-test-alarm")
async def trigger_test_alarm(_username: str = Depends(verify_admin)):
    """Manually trigger scheduled route check tasks"""
    try:
        asyncio.create_task(EventService.scheduled_route_check())
        return {"message": "Success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
