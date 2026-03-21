import os
import secrets
import asyncio
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from app.database.connection import get_db_connection
from app.config.settings import settings

router = APIRouter(
    prefix="/admin",
    tags=["admin"]
)

security = HTTPBasic()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"))

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    # Using environment variables for admin credentials.
    # These must be configured via environment (.env, deployment config).
    admin_user = os.getenv("ADMIN_USER")
    admin_pass = os.getenv("ADMIN_PASS")
    
    # Fail fast if admin credentials are not configured
    if admin_user is None or admin_pass is None:
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

@router.get("/dashboard")
async def dashboard(request: Request, _username: str = Depends(verify_admin)):
    """Render the back-office dashboard"""
    
    # Run database queries in parallel
    events, alarms = await asyncio.gather(
        asyncio.to_thread(fetch_recent_events),
        asyncio.to_thread(fetch_recent_alarms)
    )
    
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
            "stats": {
                "total_events": total_events,
                "total_alarms": total_alarms,
                "total_alarms_sent": total_alarms_sent,
                "success_rate": success_rate,
                "failed_sends": failed_sends
            }
        }
    )
