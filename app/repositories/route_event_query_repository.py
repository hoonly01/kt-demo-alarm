"""경로 기반 이벤트 조회 저장소."""
import sqlite3
from typing import Any, Dict, List

from app.repositories.event_repository import EVENT_COLUMNS


class RouteEventQueryRepository:
    """호출자가 제공한 SQLite 연결로 route-check용 events SQL을 실행한다."""

    @staticmethod
    def list_active_future_events(db: sqlite3.Connection) -> List[Dict[str, Any]]:
        cursor = db.cursor()
        cursor.execute(
            f"""
            SELECT {EVENT_COLUMNS}
            FROM events
            WHERE status = 'active' AND start_date > datetime('now', '+9 hours')
            ORDER BY start_date
            """
        )
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in rows]
