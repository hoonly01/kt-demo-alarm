"""사용자 경로 쓰기 저장소."""
import sqlite3
from datetime import datetime
from typing import Any, Dict


class UserRouteRepository:
    """호출자가 제공한 SQLite 연결로 사용자 route SQL을 실행한다."""

    @staticmethod
    def update_route(
        db: sqlite3.Connection,
        *,
        user_id: str,
        departure_info: Dict[str, Any],
        arrival_info: Dict[str, Any],
        now: datetime,
    ) -> int:
        cursor = db.cursor()
        cursor.execute(
            """
            UPDATE users SET
                departure_name = ?, departure_address = ?, departure_x = ?, departure_y = ?,
                arrival_name = ?, arrival_address = ?, arrival_x = ?, arrival_y = ?,
                route_updated_at = ?
            WHERE plusfriend_user_key = ?
            """,
            (
                departure_info["name"],
                departure_info["address"],
                departure_info["x"],
                departure_info["y"],
                arrival_info["name"],
                arrival_info["address"],
                arrival_info["x"],
                arrival_info["y"],
                now,
                user_id,
            ),
        )
        return cursor.rowcount

    @staticmethod
    def clear_route(
        db: sqlite3.Connection,
        *,
        user_id: str,
        now: datetime,
    ) -> int:
        rowcount = UserRouteRepository._clear_route_by_identifier(
            db,
            identifier_column="plusfriend_user_key",
            user_id=user_id,
            now=now,
        )
        if rowcount == 0:
            rowcount = UserRouteRepository._clear_route_by_identifier(
                db,
                identifier_column="bot_user_key",
                user_id=user_id,
                now=now,
            )
        return rowcount

    @staticmethod
    def _clear_route_by_identifier(
        db: sqlite3.Connection,
        *,
        identifier_column: str,
        user_id: str,
        now: datetime,
    ) -> int:
        cursor = db.cursor()
        cursor.execute(
            f"""
            UPDATE users SET
                departure_name = NULL, departure_address = NULL,
                departure_x = NULL, departure_y = NULL,
                arrival_name = NULL, arrival_address = NULL,
                arrival_x = NULL, arrival_y = NULL,
                route_updated_at = ?
            WHERE {identifier_column} = ?
            """,
            (now, user_id),
        )
        return cursor.rowcount
