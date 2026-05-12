"""사용자 경로 읽기 저장소."""
import sqlite3
from typing import Any, Dict, List, Optional


ROUTE_FIELDS = """
    departure_name, departure_address, departure_x, departure_y,
    arrival_name, arrival_address, arrival_x, arrival_y
"""


class UserRouteReadRepository:
    """사용자 경로 조회 SQL을 담당한다."""

    @staticmethod
    def get_route_for_user(
        db: sqlite3.Connection,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        cursor = db.cursor()
        cursor.execute(
            f"""
            SELECT {ROUTE_FIELDS}
            FROM users
            WHERE plusfriend_user_key = ? OR bot_user_key = ?
            """,
            (user_id, user_id),
        )
        return UserRouteReadRepository._fetch_one_dict(cursor)

    @staticmethod
    def list_scheduled_route_users(db: sqlite3.Connection) -> List[Dict[str, Any]]:
        cursor = db.cursor()
        cursor.execute(
            """
            SELECT plusfriend_user_key, departure_name, arrival_name
            FROM users
            WHERE active = 1
              AND is_alarm_on = 1
              AND plusfriend_user_key IS NOT NULL
              AND departure_x IS NOT NULL
              AND departure_y IS NOT NULL
              AND arrival_x IS NOT NULL
              AND arrival_y IS NOT NULL
            """
        )
        return UserRouteReadRepository._fetch_dicts(cursor)

    @staticmethod
    def list_auto_check_route_user_ids(db: sqlite3.Connection) -> List[Dict[str, Any]]:
        cursor = db.cursor()
        cursor.execute(
            """
            SELECT COALESCE(plusfriend_user_key, bot_user_key) as user_id
            FROM users
            WHERE active = 1
              AND is_alarm_on = 1
              AND departure_x IS NOT NULL
              AND departure_y IS NOT NULL
              AND arrival_x IS NOT NULL
              AND arrival_y IS NOT NULL
              AND (plusfriend_user_key IS NOT NULL OR bot_user_key IS NOT NULL)
            """
        )
        return UserRouteReadRepository._fetch_dicts(cursor)

    @staticmethod
    def _fetch_one_dict(cursor: sqlite3.Cursor) -> Optional[Dict[str, Any]]:
        row = cursor.fetchone()
        if not row:
            return None

        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))

    @staticmethod
    def _fetch_dicts(cursor: sqlite3.Cursor) -> List[Dict[str, Any]]:
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in rows]
