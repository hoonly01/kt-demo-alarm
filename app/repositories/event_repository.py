"""events 테이블 저장소."""
import sqlite3
from typing import Any, Dict, List, Optional


EVENT_COLUMNS = """
    id, title, description, location_name, location_address,
    latitude, longitude, start_date, end_date, category,
    severity_level, status, created_at, updated_at
"""


class EventRepository:
    """호출자가 제공한 SQLite 연결로 events SQL을 실행한다."""

    @staticmethod
    def create_event(
        db: sqlite3.Connection,
        *,
        title: str,
        description: Optional[str],
        location_name: str,
        location_address: Optional[str],
        latitude: float,
        longitude: float,
        start_date: Any,
        end_date: Any,
        category: Optional[str],
        severity_level: int,
        status: str,
    ) -> int:
        cursor = db.cursor()
        cursor.execute(
            """
            INSERT INTO events (title, description, location_name, location_address,
                                latitude, longitude, start_date, end_date, category,
                                severity_level, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                description,
                location_name,
                location_address,
                latitude,
                longitude,
                start_date,
                end_date,
                category,
                severity_level,
                status,
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def get_by_id(
        db: sqlite3.Connection,
        event_id: int,
    ) -> Optional[Dict[str, Any]]:
        cursor = db.cursor()
        cursor.execute(
            f"""
            SELECT {EVENT_COLUMNS}
            FROM events
            WHERE id = ?
            """,
            (event_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))

    @staticmethod
    def list_events(
        db: sqlite3.Connection,
        *,
        category: Optional[str],
        status: Optional[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        where_conditions = []
        params: List[Any] = []

        if category:
            where_conditions.append("category = ?")
            params.append(category)

        if status:
            where_conditions.append("status = ?")
            params.append(status)

        where_clause = " WHERE " + " AND ".join(where_conditions) if where_conditions else ""
        params.append(limit)

        cursor = db.cursor()
        cursor.execute(
            f"""
            SELECT {EVENT_COLUMNS}
            FROM events{where_clause}
            ORDER BY start_date DESC
            LIMIT ?
            """,
            params,
        )
        return EventRepository._fetch_dicts(cursor)

    @staticmethod
    def list_upcoming(
        db: sqlite3.Connection,
        *,
        now: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        cursor = db.cursor()
        cursor.execute(
            f"""
            SELECT {EVENT_COLUMNS}
            FROM events
            WHERE status = 'active' AND start_date >= ?
            ORDER BY start_date ASC
            LIMIT ?
            """,
            (now, limit),
        )
        return EventRepository._fetch_dicts(cursor)

    @staticmethod
    def list_today_by_location_pattern(
        db: sqlite3.Connection,
        *,
        today: str,
        location_pattern: str,
    ) -> List[Dict[str, Any]]:
        cursor = db.cursor()
        cursor.execute(
            f"""
            SELECT {EVENT_COLUMNS}
            FROM events
            WHERE status = 'active'
              AND date(start_date) = ?
              AND (location_name LIKE ? OR location_address LIKE ?)
            ORDER BY start_date ASC
            """,
            (today, location_pattern, location_pattern),
        )
        return EventRepository._fetch_dicts(cursor)

    @staticmethod
    def _fetch_dicts(cursor: sqlite3.Cursor) -> List[Dict[str, Any]]:
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in rows]
