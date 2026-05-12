"""관리자 대시보드 읽기 저장소."""
import sqlite3
from collections.abc import Sequence
from typing import cast


type DashboardRow = dict[str, object]
type SqliteRowSequence = Sequence[object]


ADMIN_DASHBOARD_RECENT_LIMIT = 100
USERS_TABLE_NAME = "users"
ALLOWED_SCHEMA_TABLES = frozenset({USERS_TABLE_NAME})

PAGINATED_USER_BASE_FIELDS = [
    "id",
    "bot_user_key",
    "active",
    "departure_name",
    "arrival_name",
    "marked_bus",
    "first_message_at as created_at",
    "message_count",
]

PAGINATED_USER_OPTIONAL_FIELDS = {
    "plusfriend_user_key": "plusfriend_user_key",
    "open_id": "open_id",
    "is_alarm_on": "is_alarm_on",
    "favorite_zone": "COALESCE(favorite_zone, 0) as favorite_zone",
}


class AdminDashboardReadRepository:
    """관리자 대시보드의 read-model SQL을 담당한다."""

    @staticmethod
    def list_recent_events(
        db: sqlite3.Connection,
        limit: int = ADMIN_DASHBOARD_RECENT_LIMIT,
    ) -> list[DashboardRow]:
        cursor = db.cursor()
        try:
            _ = cursor.execute(
                """
                SELECT id, title, location_name, severity_level, start_date, created_at, status
                FROM events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
        except sqlite3.OperationalError as exc:
            if AdminDashboardReadRepository._is_missing_table_error(exc):
                return []
            raise
        return AdminDashboardReadRepository._fetch_dicts(cursor)

    @staticmethod
    def list_recent_alarms(
        db: sqlite3.Connection,
        limit: int = ADMIN_DASHBOARD_RECENT_LIMIT,
    ) -> list[DashboardRow]:
        cursor = db.cursor()
        try:
            _ = cursor.execute(
                """
                SELECT task_id, alarm_type, status, total_recipients, successful_sends, failed_sends, created_at
                FROM alarm_tasks
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        except sqlite3.OperationalError as exc:
            if AdminDashboardReadRepository._is_missing_table_error(exc):
                return []
            raise
        return AdminDashboardReadRepository._fetch_dicts(cursor)

    @staticmethod
    def count_users(db: sqlite3.Connection) -> int:
        cursor = db.cursor()
        try:
            _ = cursor.execute("SELECT COUNT(*) FROM users")
        except sqlite3.OperationalError as exc:
            if AdminDashboardReadRepository._is_missing_table_error(exc):
                return 0
            raise
        result = cast(SqliteRowSequence | None, cursor.fetchone())
        return cast(int, result[0]) if result else 0

    @staticmethod
    def list_paginated_users(
        db: sqlite3.Connection,
        *,
        limit: int,
        offset: int,
    ) -> list[DashboardRow]:
        try:
            user_columns = AdminDashboardReadRepository._get_table_columns(db, USERS_TABLE_NAME)
        except sqlite3.OperationalError as exc:
            if AdminDashboardReadRepository._is_missing_table_error(exc):
                return []
            raise
        if not user_columns:
            return []
        select_fields = list(PAGINATED_USER_BASE_FIELDS)

        for column_name, sql in PAGINATED_USER_OPTIONAL_FIELDS.items():
            if column_name in user_columns:
                select_fields.append(sql)
            elif column_name == "favorite_zone":
                select_fields.append("0 as favorite_zone")
            else:
                select_fields.append(f"NULL as {column_name}")

        cursor = db.cursor()
        _ = cursor.execute(
            f"""
            SELECT {', '.join(select_fields)}
            FROM users
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        return AdminDashboardReadRepository._fetch_dicts(cursor)

    @staticmethod
    def _get_table_columns(db: sqlite3.Connection, table_name: str) -> set[str]:
        if table_name not in ALLOWED_SCHEMA_TABLES:
            raise ValueError(f"Unsupported table for dashboard schema inspection: {table_name}")

        cursor = db.cursor()
        _ = cursor.execute(f"PRAGMA table_info({table_name})")
        columns: set[str] = set()
        for row in cast(list[sqlite3.Row | SqliteRowSequence], cursor.fetchall()):
            if isinstance(row, sqlite3.Row):
                column_name = cast(object, row["name"])
                columns.add(str(column_name))
            else:
                columns.add(str(row[1]))
        return columns

    @staticmethod
    def _fetch_dicts(cursor: sqlite3.Cursor) -> list[DashboardRow]:
        rows = cast(list[SqliteRowSequence], cursor.fetchall())
        columns = [str(desc[0]) for desc in cursor.description or ()]
        return [dict(zip(columns, row)) for row in rows]

    @staticmethod
    def _is_missing_table_error(exc: sqlite3.OperationalError) -> bool:
        return "no such table" in str(exc).lower()
