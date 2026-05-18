import os
import secrets
import asyncio
import logging
import json
from collections.abc import Callable, Coroutine
from datetime import timezone, tzinfo
from typing import Dict, Any, List, Set

from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from app.database.connection import get_db_connection
from app.config.settings import settings
import math

from app.utils.scheduler_utils import get_scheduler_status
from app.services.event_service import EventService
from app.services.bus_notice_service import BusNoticeService
from app.services.crawling import crawl_and_sync_smpa_events
from app.services.zone_alarm_service import ZoneAlarmService
from app.utils.time_utils import KST, parse_datetime_value

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

DASHBOARD_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S KST"
DASHBOARD_DATE_FORMAT = "%Y-%m-%d KST"
DASHBOARD_RECENT_LIMIT = 100
HASH_PREVIEW_LENGTH = 24
TASK_ID_PREVIEW_LENGTH = 32
TEXT_PREVIEW_LENGTH = 120
DASHBOARD_REFRESH_SECONDS = 60
SCHEMA_TABLE_ALLOWLIST = frozenset({"users", "events", "alarm_tasks"})

ADMIN_ACTION_CATALOG = [
    {
        "label": "Sync SMPA Rally Data",
        "endpoint": "/admin/trigger-crawling",
        "risk": "External SMPA fetch",
        "external_call": True,
        "verification": "Schedules the existing crawler only; Basic Auth/API-key and CSRF guard stay unchanged.",
        "tone": "blue",
    },
    {
        "label": "Sync TOPIS Bus Notices",
        "endpoint": "/admin/trigger-bus-notice",
        "risk": "External TOPIS fetch",
        "external_call": True,
        "verification": "Schedules the existing bus notice refresh only; dashboard rendering never refreshes it.",
        "tone": "green",
    },
    {
        "label": "Run Route Check",
        "endpoint": "/admin/trigger-route-check",
        "risk": "Notification path",
        "external_call": False,
        "verification": "Schedules the existing route checker without changing delivery policy.",
        "tone": "indigo",
    },
    {
        "label": "Run Zone Check",
        "endpoint": "/admin/trigger-zone-check",
        "risk": "Notification path",
        "external_call": False,
        "verification": "Schedules the existing zone checker without destructive side effects.",
        "tone": "purple",
    },
    {
        "label": "Test Route Alarm for User",
        "endpoint": "/admin/trigger-test-alarm-for-user",
        "risk": "Single-user diagnostic",
        "external_call": False,
        "verification": "Requires an explicit user id and reuses the existing per-user route check.",
        "tone": "amber",
        "requires_user_id": True,
    },
]

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


def _preview_text(value: Any, length: int = TEXT_PREVIEW_LENGTH) -> str:
    if value in (None, ""):
        return ""

    text = str(value).strip()
    if len(text) <= length:
        return text
    return f"{text[:length]}..."


def _format_event_hash_summary(record_hash: Any, payload_hash: Any) -> str:
    hash_items = [
        ("record", _preview_text(record_hash, HASH_PREVIEW_LENGTH)),
        ("payload", _preview_text(payload_hash, HASH_PREVIEW_LENGTH)),
    ]
    return " / ".join(f"{label}: {hash_value}" for label, hash_value in hash_items if hash_value)


def _safe_json_summary(value: Any) -> str:
    if value in (None, ""):
        return ""

    text = str(value).strip()
    if not text:
        return ""

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return _preview_text(text)

    if isinstance(parsed, dict):
        summary = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
    elif isinstance(parsed, list):
        summary = json.dumps(parsed[:5], ensure_ascii=False)
    else:
        summary = str(parsed)
    return _preview_text(summary)


def _mask_identifier(value: Any) -> str:
    if value in (None, ""):
        return "-"

    text = str(value)
    if len(text) <= HASH_PREVIEW_LENGTH:
        return text
    return f"{text[:8]}...{text[-4:]}"


def _http_url_or_empty(value: Any) -> str:
    if value in (None, ""):
        return ""

    text = str(value).strip()
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return text
    return ""


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _first_column_value(row: Any, default: Any = 0) -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return next(iter(row.values()), default)
    return row[0] if len(row) > 0 else default


def _schema_select_field(
    columns: Set[str],
    column_name: str,
    *,
    alias: str | None = None,
    default_sql: str = "NULL",
    expression_sql: str | None = None,
) -> str:
    output_name = alias or column_name
    if column_name in columns:
        expression = expression_sql or column_name
        return f"{expression} AS {output_name}"
    return f"{default_sql} AS {output_name}"


def _select_field(
    columns: Set[str],
    column_name: str,
    *,
    alias: str | None = None,
    default_expression: str = "NULL",
    expression: str | None = None,
) -> str:
    return _schema_select_field(
        columns,
        column_name,
        alias=alias,
        default_sql=default_expression,
        expression_sql=expression,
    )


def fetch_recent_events() -> List[Dict[str, Any]]:
    # Synchronous DB query
    with get_db_connection() as conn:
        conn.row_factory = dict_factory
        cursor = conn.cursor()

        event_columns = _get_table_columns(cursor, "events")
        select_fields = [
            _schema_select_field(event_columns, "id", default_sql="0"),
            _schema_select_field(event_columns, "title", default_sql="'Untitled event'"),
            _schema_select_field(event_columns, "location_name", default_sql="'Unknown location'"),
            _schema_select_field(event_columns, "severity_level", default_sql="1"),
            _schema_select_field(event_columns, "start_date"),
            _schema_select_field(event_columns, "end_date"),
            _schema_select_field(event_columns, "created_at"),
            _schema_select_field(event_columns, "updated_at"),
            _schema_select_field(event_columns, "status", default_sql="'unknown'"),
            _schema_select_field(event_columns, "source", default_sql="'legacy schema'"),
            _schema_select_field(event_columns, "source_url"),
            _schema_select_field(event_columns, "source_record_hash"),
            _schema_select_field(event_columns, "source_payload_hash"),
            _schema_select_field(event_columns, "collected_at"),
            _schema_select_field(event_columns, "parser_version"),
            _schema_select_field(event_columns, "attendees", default_sql="'미상'"),
            _schema_select_field(event_columns, "police_station"),
            _schema_select_field(event_columns, "location_address"),
        ]
        order_column = "id" if "id" in event_columns else "rowid"
        cursor.execute(f"""
            SELECT {', '.join(select_fields)}
            FROM events
            ORDER BY {order_column} DESC
            LIMIT ?
        """, (DASHBOARD_RECENT_LIMIT,))
        events = cursor.fetchall()
        for event in events:
            event["created_at_display"] = _format_utc_timestamp_as_kst(event.get("created_at"))
            event["start_date_display"] = _format_kst_local_datetime(event.get("start_date"))
            event["end_date_display"] = _format_kst_local_datetime(event.get("end_date"))
            event["collected_at_display"] = _format_utc_timestamp_as_kst(event.get("collected_at"))
            event["updated_at_display"] = _format_utc_timestamp_as_kst(event.get("updated_at"))
            event["source_label"] = event.get("source") or "legacy schema"
            event["source_url_href"] = _http_url_or_empty(event.get("source_url"))
            event["source_hash_display"] = _format_event_hash_summary(
                event.get("source_record_hash"),
                event.get("source_payload_hash"),
            )
            event["parser_version_display"] = event.get("parser_version") or "not recorded"
            event["collection_status"] = "Collected" if event.get("collected_at") else "No collection timestamp"
        return events

def fetch_recent_alarms() -> List[Dict[str, Any]]:
    # Synchronous DB query
    with get_db_connection() as conn:
        conn.row_factory = dict_factory
        cursor = conn.cursor()

        alarm_columns = _get_table_columns(cursor, "alarm_tasks")
        select_fields = [
            _schema_select_field(alarm_columns, "task_id", default_sql="'unknown-task'"),
            _schema_select_field(alarm_columns, "alarm_type", default_sql="'unknown'"),
            _schema_select_field(alarm_columns, "status", default_sql="'unknown'"),
            _schema_select_field(alarm_columns, "total_recipients", default_sql="0"),
            _schema_select_field(alarm_columns, "successful_sends", default_sql="0"),
            _schema_select_field(alarm_columns, "failed_sends", default_sql="0"),
            _schema_select_field(alarm_columns, "event_id"),
            _schema_select_field(alarm_columns, "request_data"),
            _schema_select_field(alarm_columns, "error_messages"),
            _schema_select_field(alarm_columns, "created_at"),
            _schema_select_field(alarm_columns, "updated_at"),
            _schema_select_field(alarm_columns, "completed_at"),
        ]
        order_column = "created_at" if "created_at" in alarm_columns else "rowid"
        cursor.execute(f"""
            SELECT {', '.join(select_fields)}
            FROM alarm_tasks
            ORDER BY {order_column} DESC
            LIMIT ?
        """, (DASHBOARD_RECENT_LIMIT,))
        alarms = cursor.fetchall()
        for alarm in alarms:
            alarm["task_id_display"] = _preview_text(alarm.get("task_id"), TASK_ID_PREVIEW_LENGTH) or "unknown-task"
            alarm["created_at_display"] = _format_kst_local_datetime(alarm.get("created_at"))
            alarm["updated_at_display"] = _format_kst_local_datetime(alarm.get("updated_at"))
            alarm["completed_at_display"] = _format_kst_local_datetime(alarm.get("completed_at"))
            alarm["request_summary"] = _safe_json_summary(alarm.get("request_data"))
            alarm["error_summary"] = _safe_json_summary(alarm.get("error_messages"))
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
    if table_name not in SCHEMA_TABLE_ALLOWLIST:
        raise ValueError(f"Unsupported table name: {table_name}")
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
            _select_field(user_columns, "id"),
            _select_field(user_columns, "bot_user_key"),
            _select_field(user_columns, "active", default_expression="0"),
            _select_field(user_columns, "departure_name"),
            _select_field(user_columns, "departure_x"),
            _select_field(user_columns, "departure_y"),
            _select_field(user_columns, "arrival_name"),
            _select_field(user_columns, "arrival_x"),
            _select_field(user_columns, "arrival_y"),
            _select_field(user_columns, "marked_bus"),
            "first_message_at AS created_at" if "first_message_at" in user_columns else "NULL AS created_at",
            _select_field(user_columns, "last_message_at"),
            _select_field(user_columns, "message_count", default_expression="0"),
        ]

        optional_fields = {
            "plusfriend_user_key": "plusfriend_user_key",
            "open_id": "open_id",
            "is_alarm_on": "is_alarm_on",
            "favorite_zone": "COALESCE(favorite_zone, 0) as favorite_zone",
            "route_updated_at": "route_updated_at",
            "language": "language",
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
        users = cursor.fetchall()
        for user in users:
            has_coordinate_route = all(
                user.get(column_name) is not None
                for column_name in ("departure_x", "departure_y", "arrival_x", "arrival_y")
            )
            has_named_route = bool(user.get("departure_name") and user.get("arrival_name"))
            user["route_ready"] = has_coordinate_route or has_named_route
            user["readiness_label"] = "Route ready" if user["route_ready"] else "Route incomplete"
            user["last_message_at_display"] = _format_kst_local_datetime(user.get("last_message_at"))
            user["route_updated_at_display"] = _format_kst_local_datetime(user.get("route_updated_at"))
            user["language_display"] = user.get("language") or "not set"
            user["display_identifier"] = _mask_identifier(
                user.get("plusfriend_user_key") or user.get("bot_user_key") or user.get("open_id")
            )
        return users


def _count_rows(cursor, table_name: str) -> int:
    if table_name not in SCHEMA_TABLE_ALLOWLIST:
        raise ValueError(f"Unsupported table name: {table_name}")
    cursor.execute(f"SELECT COUNT(*) AS count FROM {table_name}")
    return _coerce_int(_first_column_value(cursor.fetchone()))


def _count_where(cursor, table_name: str, where_sql: str) -> int:
    if table_name not in SCHEMA_TABLE_ALLOWLIST:
        raise ValueError(f"Unsupported table name: {table_name}")
    cursor.execute(f"SELECT COUNT(*) AS count FROM {table_name} WHERE {where_sql}")
    return _coerce_int(_first_column_value(cursor.fetchone()))


def _sum_column(cursor, table_name: str, columns: Set[str], column_name: str) -> int:
    if table_name not in SCHEMA_TABLE_ALLOWLIST:
        raise ValueError(f"Unsupported table name: {table_name}")
    if column_name not in columns:
        return 0
    cursor.execute(f"SELECT COALESCE(SUM({column_name}), 0) AS total FROM {table_name}")
    return _coerce_int(_first_column_value(cursor.fetchone()))


def _max_column(cursor, table_name: str, columns: Set[str], column_name: str) -> Any:
    if table_name not in SCHEMA_TABLE_ALLOWLIST:
        raise ValueError(f"Unsupported table name: {table_name}")
    if column_name not in columns:
        return None
    cursor.execute(f"SELECT MAX({column_name}) AS latest FROM {table_name}")
    return _first_column_value(cursor.fetchone(), None)


def fetch_admin_overview() -> Dict[str, Any]:
    with get_db_connection() as conn:
        conn.row_factory = dict_factory
        cursor = conn.cursor()

        event_columns = _get_table_columns(cursor, "events")
        alarm_columns = _get_table_columns(cursor, "alarm_tasks")
        user_columns = _get_table_columns(cursor, "users")

        total_events = _count_rows(cursor, "events")
        active_events = (
            _count_where(cursor, "events", "status = 'active'")
            if "status" in event_columns
            else 0
        )
        latest_collected_at = _max_column(cursor, "events", event_columns, "collected_at")
        latest_event_updated_at = (
            _max_column(cursor, "events", event_columns, "updated_at")
            or _max_column(cursor, "events", event_columns, "created_at")
        )

        total_alarms = _count_rows(cursor, "alarm_tasks")
        failed_alarm_tasks = (
            _count_where(cursor, "alarm_tasks", "status IN ('failed', 'partial')")
            if "status" in alarm_columns
            else 0
        )
        total_alarms_sent = _sum_column(cursor, "alarm_tasks", alarm_columns, "total_recipients")
        successful_sends = _sum_column(cursor, "alarm_tasks", alarm_columns, "successful_sends")
        failed_sends = _sum_column(cursor, "alarm_tasks", alarm_columns, "failed_sends")

        total_users = _count_rows(cursor, "users")
        active_users = (
            _count_where(cursor, "users", "active = 1")
            if "active" in user_columns
            else 0
        )
        subscribed_users = (
            _count_where(cursor, "users", "COALESCE(active, 0) = 1 AND COALESCE(is_alarm_on, 0) = 1")
            if {"active", "is_alarm_on"}.issubset(user_columns)
            else 0
        )
        route_ready_conditions: list[str] = []
        if {"departure_x", "departure_y", "arrival_x", "arrival_y"}.issubset(user_columns):
            route_ready_conditions.append(
                "departure_x IS NOT NULL AND departure_y IS NOT NULL "
                + "AND arrival_x IS NOT NULL AND arrival_y IS NOT NULL"
            )
        if {"departure_name", "arrival_name"}.issubset(user_columns):
            route_ready_conditions.append(
                "COALESCE(departure_name, '') != '' AND COALESCE(arrival_name, '') != ''"
            )

        route_ready_users = (
            _count_where(
                cursor,
                "users",
                " OR ".join(f"({condition})" for condition in route_ready_conditions),
            )
            if route_ready_conditions
            else 0
        )

    success_rate = 0
    if total_alarms_sent > 0:
        success_rate = round((successful_sends / total_alarms_sent) * 100, 1)

    readiness_rate = 0
    if total_users > 0:
        readiness_rate = round((route_ready_users / total_users) * 100, 1)

    return {
        "total_events": total_events,
        "active_events": active_events,
        "latest_collected_at": latest_collected_at,
        "latest_collected_at_display": _format_utc_timestamp_as_kst(latest_collected_at),
        "latest_event_updated_at": latest_event_updated_at,
        "latest_event_updated_at_display": _format_utc_timestamp_as_kst(latest_event_updated_at),
        "total_alarms": total_alarms,
        "total_alarms_sent": total_alarms_sent,
        "successful_sends": successful_sends,
        "failed_sends": failed_sends,
        "failed_alarm_tasks": failed_alarm_tasks,
        "success_rate": success_rate,
        "total_users": total_users,
        "active_users": active_users,
        "subscribed_users": subscribed_users,
        "route_ready_users": route_ready_users,
        "readiness_rate": readiness_rate,
    }


def get_bus_notice_snapshot() -> Dict[str, Any]:
    cached_notices = BusNoticeService.cached_notices
    if isinstance(cached_notices, dict):
        cached_count = len(cached_notices)
    elif isinstance(cached_notices, list):
        cached_count = len(cached_notices)
    else:
        cached_count = 0

    return {
        "crawler_initialized": BusNoticeService.crawler is not None,
        "cached_count": cached_count,
        "last_update": BusNoticeService.last_update,
        "last_update_display": _format_datetime_as_kst(
            BusNoticeService.last_update,
            naive_source_tz=KST,
            output_format="%Y-%m-%d %H:%M:%S KST",
        ),
    }

def _format_datetime_as_kst(
    value: Any,
    *,
    naive_source_tz: tzinfo,
    output_format: str = DASHBOARD_DATETIME_FORMAT,
) -> str:
    parsed = parse_datetime_value(value)
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
    parsed = parse_datetime_value(value)
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=KST)
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
        events, alarms, users, overview = await asyncio.gather(
            asyncio.to_thread(fetch_recent_events),
            asyncio.to_thread(fetch_recent_alarms),
            asyncio.to_thread(fetch_paginated_users, page_size, offset),
            asyncio.to_thread(fetch_admin_overview),
        )
        total_users = overview["total_users"]

        total_pages = math.ceil(total_users / page_size) if total_users > 0 else 1

        # Get Scheduler Status
        scheduler_status = _apply_scheduler_time_displays(get_scheduler_status())
        bus_notice_status = get_bus_notice_snapshot()

        for user in users:
            user["created_at_display"] = _format_user_created_at(user.get("created_at"))

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
                "stats": overview,
                "bus_notice_status": bus_notice_status,
                "action_catalog": ADMIN_ACTION_CATALOG,
                "dashboard_refresh_seconds": DASHBOARD_REFRESH_SECONDS,
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
        crawl_and_sync_smpa_events,
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
