"""크롤링 이벤트 bulk import 저장소 통합 테스트."""

from app.database.connection import get_db_connection
from app.repositories.event_bulk_import_repository import EventBulkImportRepository


def _bulk_row(
    *,
    title: str = "광화문 집회",
    location_name: str = "광화문",
    start_date: str = "2026-05-12 10:00:00",
):
    return (
        title,
        "집회 설명",
        location_name,
        "서울 종로구 세종대로",
        37.571,
        126.976,
        start_date,
        "2026-05-12 12:00:00",
        "집회",
        3,
        "active",
    )


def test_event_bulk_import_repository_preserves_insert_or_ignore_idempotency(clean_test_db):
    with get_db_connection() as conn:
        EventBulkImportRepository.ensure_location_date_unique_index(conn)

        first_count = EventBulkImportRepository.insert_or_ignore_events(
            conn,
            [_bulk_row(), _bulk_row(title="중복 집회")],
        )
        second_count = EventBulkImportRepository.insert_or_ignore_events(
            conn,
            [_bulk_row(title="중복 재시도")],
        )
        conn.commit()

        cursor = conn.cursor()
        cursor.execute("SELECT title, location_name, start_date FROM events")
        rows = [tuple(row) for row in cursor.fetchall()]

    assert first_count == 1
    assert second_count == 0
    assert rows == [("광화문 집회", "광화문", "2026-05-12 10:00:00")]


def test_event_bulk_import_repository_allows_different_location_or_date(clean_test_db):
    with get_db_connection() as conn:
        EventBulkImportRepository.ensure_location_date_unique_index(conn)

        inserted_count = EventBulkImportRepository.insert_or_ignore_events(
            conn,
            [
                _bulk_row(location_name="광화문", start_date="2026-05-12 10:00:00"),
                _bulk_row(location_name="시청", start_date="2026-05-12 10:00:00"),
                _bulk_row(location_name="광화문", start_date="2026-05-12 13:00:00"),
            ],
        )
        conn.commit()

        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM events")
        total_count = cursor.fetchone()[0]

    assert inserted_count == 3
    assert total_count == 3
