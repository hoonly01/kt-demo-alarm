"""구역 알림 읽기 저장소."""
import sqlite3
from typing import Any, Dict, List


class ZoneAlarmReadRepository:
    """구역 알림 사용자/이벤트 읽기 SQL을 담당한다."""

    @staticmethod
    def list_zone_users(db: sqlite3.Connection) -> List[Dict[str, Any]]:
        cursor = db.cursor()
        cursor.execute(
            """
            SELECT plusfriend_user_key, favorite_zone
            FROM users
            WHERE active = 1
              AND is_alarm_on = 1
              AND favorite_zone IS NOT NULL
              AND plusfriend_user_key IS NOT NULL
            """
        )
        return ZoneAlarmReadRepository._fetch_dicts(cursor)

    @staticmethod
    def list_active_future_events(db: sqlite3.Connection) -> List[Dict[str, Any]]:
        cursor = db.cursor()
        cursor.execute(
            """
            SELECT id, title, location_name, location_address,
                   latitude, longitude, start_date, category, severity_level
            FROM events
            WHERE status = 'active'
              AND latitude IS NOT NULL
              AND longitude IS NOT NULL
              AND start_date > datetime('now', '+9 hours')
            ORDER BY start_date
            """
        )
        return ZoneAlarmReadRepository._fetch_dicts(cursor)

    @staticmethod
    def _fetch_dicts(cursor: sqlite3.Cursor) -> List[Dict[str, Any]]:
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in rows]
