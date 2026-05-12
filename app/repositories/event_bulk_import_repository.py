"""크롤링 이벤트 bulk import 저장소."""
import sqlite3
from collections.abc import Sequence


type EventBulkImportRow = tuple[
    object,
    object,
    object,
    object,
    object,
    object,
    object,
    object,
    object,
    object,
    object,
]

EVENT_LOCATION_DATE_INDEX_NAME = "idx_events_location_date"


class EventBulkImportRepository:
    """호출자가 제공한 SQLite 연결로 크롤링 이벤트 bulk import SQL을 실행한다."""

    @staticmethod
    def ensure_location_date_unique_index(db: sqlite3.Connection) -> None:
        cursor = db.cursor()
        _ = cursor.execute(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS {EVENT_LOCATION_DATE_INDEX_NAME}
            ON events(location_name, start_date)
            """
        )

    @staticmethod
    def insert_or_ignore_events(
        db: sqlite3.Connection,
        rows: Sequence[EventBulkImportRow],
    ) -> int:
        cursor = db.cursor()
        _ = cursor.executemany(
            """
            INSERT OR IGNORE INTO events (
                title, description, location_name, location_address,
                latitude, longitude, start_date, end_date,
                category, severity_level, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        return cursor.rowcount
