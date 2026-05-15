import os
import secrets
import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import datetime, timezone, tzinfo
from typing import Dict, Any, List, Set
from zoneinfo import ZoneInfo

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
from app.services.zone_alarm_service import ZoneAlarmService

from urllib.parse import urlparse

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["admin"]
)

security = HTTPBasic(auto_error=False)
admin_credentials = Depends(security)
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"))

# Task registry and lock to prevent duplicate runs and race conditions
_background_tasks: dict[str, asyncio.Task[Any]] = {}
_task_lock = asyncio.Lock()

KST_ZONE_NAME = "Asia/Seoul"
KST = ZoneInfo(KST_ZONE_NAME)
DASHBOARD_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S KST"
DASHBOARD_DATE_FORMAT = "%Y-%m-%d"

def verify_admin(credentials: HTTPBasicCredentials | None = admin_credentials):
    # Using environment variables for admin credentials.
    # These must be configured via environment (.env, deployment config).
    admin_user = settings.ADMIN_USER
    admin_pass = settings.ADMIN_PASS

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Basic"},
        )
    
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

def verify_admin_action(
    request: Request,
    credentials: HTTPBasicCredentials | None = admin_credentials,
):
    """Allow admin UI Basic Auth or API-key based operational trigger calls."""
    x_api_key = request.headers.get("x-api-key")
    if x_api_key is not None:
        if not settings.API_KEY:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Server Authorization not configured",
            )
        if not secrets.compare_digest(x_api_key, settings.API_KEY):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API Key",
            )
        return "api-key"

    username = verify_admin(credentials)
    verify_csrf_origin(request)
    return username

def verify_csrf_origin(request: Request):
    """
    Strict CSRF/Origin protection for administrative POST actions.
    Ensures the request comes from the exact same origin or host.
    """
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    host_header = request.headers.get("host")
    
    if not origin and not referer:
        raise HTTPException(status_code=403, detail="Forbidden: Missing Origin/Referer headers")
        
    def get_hostname(url_str):
        try:
            parsed = urlparse(url_str)
            return parsed.netloc
        except Exception:
            return None

    # Strict comparison against Host header
    is_valid = False
    if origin:
        if get_hostname(origin) == host_header:
            is_valid = True
    elif referer:
        if get_hostname(referer) == host_header:
            is_valid = True
            
    if not is_valid:
        logger.warning(f"CSRF/Origin validation failed. Origin: {origin}, Referer: {referer}, Host: {host_header}")
        raise HTTPException(status_code=403, detail="Forbidden: CSRF/Origin mismatch")

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
        events = cursor.fetchall()
        for event in events:
            event["created_at_display"] = _format_utc_timestamp_as_kst(event.get("created_at"))
            event["start_date_display"] = _format_kst_local_datetime(event.get("start_date"))
        return events

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
        alarms = cursor.fetchall()
        for alarm in alarms:
            alarm["created_at_display"] = _format_utc_timestamp_as_kst(alarm.get("created_at"))
        return alarms

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

def _get_table_columns(cursor, table_name: str) -> Set[str]:
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = set()
    for row in cursor.fetchall():
        if isinstance(row, dict):
            columns.add(row["name"])
        else:
            columns.add(row[1])
    return columns

def fetch_paginated_users(limit: int, offset: int) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        conn.row_factory = dict_factory
        cursor = conn.cursor()

        user_columns = _get_table_columns(cursor, "users")
        select_fields = [
            "id",
            "bot_user_key",
            "active",
            "departure_name",
            "arrival_name",
            "marked_bus",
            "first_message_at as created_at",
            "message_count",
        ]

        optional_fields = {
            "plusfriend_user_key": "plusfriend_user_key",
            "open_id": "open_id",
            "is_alarm_on": "is_alarm_on",
            "favorite_zone": "COALESCE(favorite_zone, 0) as favorite_zone",
        }

        for column_name, sql in optional_fields.items():
            if column_name in user_columns:
                select_fields.append(sql)
            else:
                select_fields.append(f"NULL as {column_name}" if column_name != "favorite_zone" else "0 as favorite_zone")

        cursor.execute(f"""
            SELECT {', '.join(select_fields)}
            FROM users
            ORDER BY id DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))
        return cursor.fetchall()

def _parse_datetime_value(value: Any) -> datetime | None:
    if value in (None, ""):
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, (int, float)):
        return _datetime_from_epoch(value)

    text = str(value).strip()
    if not text:
        return None

    if text.isdigit() and len(text) >= 10:
        parsed_epoch = _datetime_from_epoch(int(text))
        if parsed_epoch is not None:
            return parsed_epoch

    for parser in (datetime.fromisoformat,):
        try:
            return parser(text.replace("Z", "+00:00"))
        except ValueError:
            pass

    return None


def _datetime_from_epoch(value: int | float) -> datetime | None:
    timestamp = float(value)
    if timestamp > 1_000_000_000_000:
        timestamp /= 1000.0
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _format_datetime_as_kst(
    value: Any,
    *,
    naive_source_tz: tzinfo,
    output_format: str = DASHBOARD_DATETIME_FORMAT,
) -> str:
    parsed = _parse_datetime_value(value)
    if parsed is None:
        return "" if value in (None, "") else str(value)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=naive_source_tz)

    return parsed.astimezone(KST).strftime(output_format)


def _format_utc_timestamp_as_kst(value: Any) -> str:
    return _format_datetime_as_kst(value, naive_source_tz=timezone.utc)


def _format_kst_local_datetime(value: Any) -> str:
    return _format_datetime_as_kst(value, naive_source_tz=KST)


def _format_user_created_at(value: Any) -> str:
    parsed = _parse_datetime_value(value)
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(KST).strftime(DASHBOARD_DATE_FORMAT)

    return "" if value in (None, "") else str(value)[:10]


def _apply_scheduler_time_displays(scheduler_status: Dict[str, Any]) -> Dict[str, Any]:
    for job in scheduler_status.get("jobs", []):
        job["next_run_display"] = _format_datetime_as_kst(
            job.get("next_run"),
            naive_source_tz=KST,
            output_format="%Y-%m-%d %H:%M KST",
        )
    return scheduler_status

@router.get("/dashboard")
async def dashboard(
    request: Request, 
    page: int = Query(1, ge=1, description="Page number"), 
    page_size: int = Query(50, ge=1, le=200, description="Items per page"), 
    _username: str = Depends(verify_admin)
):
    """Render the back-office dashboard"""

    try:
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
        scheduler_status = _apply_scheduler_time_displays(get_scheduler_status())

        # Calculate some summary statistics
        total_events = len(events)
        total_alarms = len(alarms)
        total_alarms_sent = sum(a.get("total_recipients", 0) for a in alarms)
        successful_sends = sum(a.get("successful_sends", 0) for a in alarms)
        failed_sends = sum(a.get("failed_sends", 0) for a in alarms)

        for user in users:
            user["created_at_display"] = _format_user_created_at(user.get("created_at"))

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
    except Exception as e:
        logger.exception("Admin dashboard rendering failed")
        raise HTTPException(status_code=500, detail="Admin dashboard failed") from e

def _task_done_callback(task_key: str):
    def callback(task: asyncio.Task[Any]):
        try:
            _background_tasks.pop(task_key, None)
            task.result()
            logger.info(f"Background task {task_key} completed successfully.")
        except asyncio.CancelledError:
            logger.warning(f"Background task {task_key} was cancelled.")
        except Exception as e:
            logger.error(f"Background task {task_key} failed: {e}", exc_info=True)
    return callback


async def _schedule_background_task(
    task_key: str,
    coroutine_factory: Callable[[], Coroutine[Any, Any, Any]],
    in_progress_message: str = "Task already in progress",
) -> dict[str, str]:
    async with _task_lock:
        task = _background_tasks.get(task_key)
        if task is not None and not task.done():
            return {"message": in_progress_message}

        task = asyncio.create_task(coroutine_factory())
        _background_tasks[task_key] = task
        task.add_done_callback(_task_done_callback(task_key))
    return {"message": "Scheduled"}


@router.post("/trigger-crawling")
async def trigger_crawling(
    _auth: str = Depends(verify_admin_action),
):
    """수동으로 서울경찰청 집회 정보 크롤링을 트리거합니다."""
    return await _schedule_background_task(
        "trigger-crawling",
        CrawlingService.crawl_and_sync_events,
    )

@router.post("/trigger-bus-notice")
async def trigger_bus_notice(
    _auth: str = Depends(verify_admin_action),
):
    """수동으로 TOPIS 버스 우회 공지 크롤링을 트리거합니다."""
    return await _schedule_background_task(
        "trigger-bus-notice",
        BusNoticeService.refresh,
    )

@router.post("/trigger-route-check")
async def trigger_route_check(
    _auth: str = Depends(verify_admin_action),
):
    """수동으로 전체 사용자 경로 집회 알림 체크를 트리거합니다."""
    return await _schedule_background_task(
        "trigger-route-check",
        EventService.scheduled_route_check,
    )

@router.post("/trigger-zone-check")
async def trigger_zone_check(
    _auth: str = Depends(verify_admin_action),
):
    """수동으로 관심구역 집회 알림 체크를 트리거합니다."""
    return await _schedule_background_task(
        "trigger-zone-check",
        ZoneAlarmService.scheduled_zone_check,
    )

@router.post("/trigger-test-alarm-for-user")
async def trigger_test_alarm_for_user(
    user_id: str = Query(..., description="Target user ID to test"), 
    _auth: str = Depends(verify_admin_action),
):
    """수동으로 특정 사용자의 경로 점검 및 알림 발송 로직을 테스트합니다."""
    task_key = f"test-alarm-{user_id}"

    async def _run_route_check_for_user():
        from app.database.connection import get_db_connection
        with get_db_connection() as db:
            await EventService.check_route_events(user_id=user_id, auto_notify=True, db=db)

    return await _schedule_background_task(
        task_key,
        _run_route_check_for_user,
        "Task already in progress for this user",
    )
