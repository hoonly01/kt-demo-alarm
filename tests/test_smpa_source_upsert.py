import sqlite3
from datetime import datetime, timezone

from app.database.models import EVENTS_TABLE_SCHEMA
from app.database.connection import _ensure_events_contract
from app.services.crawling.smpa_coordinates import SelectedCoordinate
from app.services.crawling.smpa_event_sync import (
    EventCandidate,
    attendees_to_int,
    prepare_event_candidate,
    severity_from_attendees,
    sync_event_candidates,
)
from app.services.crawling.smpa_parser import ParsedSmpaEvent


def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(EVENTS_TABLE_SCHEMA)
    _ensure_events_contract(conn.cursor())
    return conn


def parsed_event(attendees="100명", police_station="종로"):
    return ParsedSmpaEvent(
        title="SMPA 집회 - 교보빌딩 남측",
        raw_location="교보빌딩 남측 -> 청진공원 <세종로>",
        endpoint_candidates=("교보빌딩 남측", "청진공원"),
        attendees=attendees,
        police_station=police_station,
        start_date=datetime(2026, 5, 15, 11, 0),
        end_date=datetime(2026, 5, 15, 13, 0),
        source_id="00336270",
        source_url="https://smpa.go.kr/user/nd54882.do?View&boardNo=00336270",
    )


def selected_coordinate(address="서울특별시 종로구 종로1가", latitude=37.5705, longitude=126.9770):
    return SelectedCoordinate(
        raw_location="교보빌딩 남측 -> 청진공원 <세종로>",
        selected_name="교보빌딩 남측",
        selected_address=address,
        latitude=latitude,
        longitude=longitude,
    )


def test_insert_skip_update_with_real_sqlite_connection():
    conn = make_conn()
    first_collected_at = datetime(2026, 5, 16, 1, 0, tzinfo=timezone.utc)
    first = prepare_event_candidate(
        parsed_event(),
        selected_coordinate(),
        collected_at=first_collected_at,
    )

    assert sync_event_candidates(conn, [first]).to_dict() == {
        "inserted": 1,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
    }
    assert sync_event_candidates(conn, [first]).to_dict() == {
        "inserted": 0,
        "updated": 0,
        "skipped": 1,
        "errors": 0,
    }

    updated_collected_at = datetime(2026, 5, 16, 2, 0, tzinfo=timezone.utc)
    updated = prepare_event_candidate(
        parsed_event(attendees="500명"),
        selected_coordinate(),
        collected_at=updated_collected_at,
    )
    result = sync_event_candidates(conn, [updated])

    assert result.to_dict() == {"inserted": 0, "updated": 1, "skipped": 0, "errors": 0}
    row = conn.execute(
        """
        SELECT attendees, source_payload_hash, start_date, end_date,
               collected_at, created_at, updated_at
        FROM events
        """
    ).fetchone()
    assert row["attendees"] == "500명"
    assert row["source_payload_hash"] == updated.source_payload_hash
    assert row["start_date"] == "2026-05-15 11:00:00"
    assert row["end_date"] == "2026-05-15 13:00:00"
    assert row["collected_at"] == "2026-05-16T02:00:00+00:00"
    assert row["created_at"].endswith("+00:00")
    assert row["updated_at"].endswith("+00:00")


def test_empty_source_record_hash_is_rejected_without_db_write():
    conn = make_conn()
    valid = prepare_event_candidate(parsed_event(), selected_coordinate())
    invalid = EventCandidate(**{**valid.__dict__, "source_record_hash": ""})

    result = sync_event_candidates(conn, [invalid])

    assert result.to_dict() == {"inserted": 0, "updated": 0, "skipped": 0, "errors": 1}
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_attendees_helpers_support_display_text():
    assert attendees_to_int("10,000명") == 10000
    assert attendees_to_int("미상") is None
    assert severity_from_attendees("70명") == 1
    assert severity_from_attendees("300명") == 2
    assert severity_from_attendees("1,000명") == 3
