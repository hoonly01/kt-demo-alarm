"""사용자 읽기 저장소."""
import sqlite3
from typing import Any, Dict, List, Optional


USER_INFO_FIELDS = """
    is_alarm_on, favorite_zone, marked_bus,
    departure_name, arrival_name,
    plusfriend_user_key, bot_user_key
"""

USER_ROUTE_INFO_FIELDS = """
    departure_name, departure_address, departure_x, departure_y,
    arrival_name, arrival_address, arrival_x, arrival_y,
    route_updated_at
"""

USER_LIST_FIELDS = """
    bot_user_key, first_message_at, last_message_at, message_count,
    location, active, departure_name, departure_address,
    departure_x, departure_y, arrival_name, arrival_address,
    arrival_x, arrival_y, route_updated_at, marked_bus, language
"""


class UserReadRepository:
    """호출자가 제공한 SQLite 연결로 사용자 read SQL을 실행한다."""

    @staticmethod
    def list_users_with_route_info(db: sqlite3.Connection) -> List[Dict[str, Any]]:
        cursor = db.cursor()
        cursor.execute(
            f"""
            SELECT {USER_LIST_FIELDS}
            FROM users
            ORDER BY last_message_at DESC
            """
        )
        return UserReadRepository._fetch_dicts(cursor)

    @staticmethod
    def get_route_info_by_bot_user_key(
        db: sqlite3.Connection,
        bot_user_key: str,
    ) -> Optional[Dict[str, Any]]:
        cursor = db.cursor()
        cursor.execute(
            f"""
            SELECT {USER_ROUTE_INFO_FIELDS}
            FROM users
            WHERE bot_user_key = ?
            """,
            (bot_user_key,),
        )
        return UserReadRepository._fetch_one_dict(cursor)

    @staticmethod
    def get_user_info(
        db: sqlite3.Connection,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        row = UserReadRepository._find_user_info_by_identifier(
            db,
            identifier_column="plusfriend_user_key",
            user_id=user_id,
        )
        if row:
            return row

        return UserReadRepository._find_user_info_by_identifier(
            db,
            identifier_column="bot_user_key",
            user_id=user_id,
        )

    @staticmethod
    def _find_user_info_by_identifier(
        db: sqlite3.Connection,
        *,
        identifier_column: str,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        cursor = db.cursor()
        cursor.execute(
            f"""
            SELECT {USER_INFO_FIELDS}
            FROM users
            WHERE {identifier_column} = ?
            LIMIT 1
            """,
            (user_id,),
        )
        return UserReadRepository._fetch_one_dict(cursor)

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
