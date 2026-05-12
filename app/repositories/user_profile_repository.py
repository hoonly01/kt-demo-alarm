"""사용자 프로필 쓰기 저장소."""
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional


class UserProfileRepository:
    """호출자가 제공한 SQLite 연결로 사용자 profile SQL을 실행한다."""

    @staticmethod
    def update_profile(
        db: sqlite3.Connection,
        *,
        plusfriend_user_key: str,
        departure_info: Optional[Dict[str, Any]],
        arrival_info: Optional[Dict[str, Any]],
        marked_bus: Optional[str],
        language: Optional[str],
        now: datetime,
    ) -> int:
        update_query = "UPDATE users SET route_updated_at = ?"
        params: List[Any] = [now]

        if departure_info:
            update_query += ", departure_name=?, departure_address=?, departure_x=?, departure_y=?"
            params.extend(
                [
                    departure_info["name"],
                    departure_info["address"],
                    departure_info["x"],
                    departure_info["y"],
                ]
            )

        if arrival_info:
            update_query += ", arrival_name=?, arrival_address=?, arrival_x=?, arrival_y=?"
            params.extend(
                [
                    arrival_info["name"],
                    arrival_info["address"],
                    arrival_info["x"],
                    arrival_info["y"],
                ]
            )

        if marked_bus:
            update_query += ", marked_bus=?"
            params.append(marked_bus)

        if language:
            update_query += ", language=?"
            params.append(language)

        update_query += " WHERE plusfriend_user_key = ?"
        params.append(plusfriend_user_key)

        cursor = db.cursor()
        cursor.execute(update_query, params)
        return cursor.rowcount
