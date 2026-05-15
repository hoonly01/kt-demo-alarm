"""SMPA 원천 레코드를 events 테이블에 INSERT/SKIP/UPDATE한다."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.services.crawling.smpa_coordinates import SelectedCoordinate
from app.services.crawling.smpa_parser import ParsedSmpaEvent, SMPA_SOURCE_NAME

LOW_SEVERITY_MAX_ATTENDEES = 99
MEDIUM_SEVERITY_MAX_ATTENDEES = 499
COORDINATE_HASH_PRECISION = 7
SOURCE_HASH_SEPARATOR = "|"


@dataclass(frozen=True)
class EventCandidate:
    """events 테이블 적재 후보."""

    title: str
    description: str | None
    attendees: str
    police_station: str
    location_name: str
    location_address: str
    latitude: float
    longitude: float
    start_date: datetime
    end_date: datetime
    category: str
    severity_level: int
    source: str
    source_id: str
    source_url: str
    source_record_hash: str
    source_payload_hash: str
    collected_at: datetime
    parser_version: str


@dataclass(frozen=True)
class SyncResult:
    """SMPA 동기화 결과."""

    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": self.errors,
        }


def _hash_parts(parts: list[Any]) -> str:
    canonical = SOURCE_HASH_SEPARATOR.join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_coordinate(value: float) -> str:
    return f"{value:.{COORDINATE_HASH_PRECISION}f}"


def attendees_to_int(attendees: str) -> int | None:
    """`10,000명` 같은 표시값에서 신고 인원 숫자를 추출한다."""
    digits = re.sub(r"[^\d]", "", attendees or "")
    return int(digits) if digits else None


def severity_from_attendees(attendees: str) -> int:
    """신고 인원 기준 심각도를 계산한다."""
    count = attendees_to_int(attendees)
    if count is None or count <= LOW_SEVERITY_MAX_ATTENDEES:
        return 1
    if count <= MEDIUM_SEVERITY_MAX_ATTENDEES:
        return 2
    return 3


def build_source_record_hash(event: ParsedSmpaEvent) -> str:
    """동일 원천 집회 row를 식별하는 stable hash를 만든다."""
    return _hash_parts(
        [
            SMPA_SOURCE_NAME,
            event.source_id,
            event.start_date.isoformat(),
            event.end_date.isoformat(),
            event.raw_location,
        ]
    )


def build_source_payload_hash(
    event: ParsedSmpaEvent,
    selected_coordinate: SelectedCoordinate,
    source_record_hash: str,
) -> str:
    """동일 identity의 내용 변경 감지 hash를 만든다."""
    return _hash_parts(
        [
            source_record_hash,
            event.attendees,
            event.police_station,
            selected_coordinate.selected_address,
            _canonical_coordinate(selected_coordinate.latitude),
            _canonical_coordinate(selected_coordinate.longitude),
            event.parser_version,
        ]
    )


def prepare_event_candidate(
    event: ParsedSmpaEvent,
    selected_coordinate: SelectedCoordinate,
    collected_at: datetime | None = None,
) -> EventCandidate:
    """파싱+좌표 선택 결과를 DB 적재 후보로 변환한다."""
    source_record_hash = build_source_record_hash(event)
    source_payload_hash = build_source_payload_hash(event, selected_coordinate, source_record_hash)
    return EventCandidate(
        title=event.title,
        description=None,
        attendees=event.attendees,
        police_station=event.police_station,
        location_name=selected_coordinate.raw_location,
        location_address=selected_coordinate.selected_address,
        latitude=selected_coordinate.latitude,
        longitude=selected_coordinate.longitude,
        start_date=event.start_date,
        end_date=event.end_date,
        category="protest",
        severity_level=severity_from_attendees(event.attendees),
        source=SMPA_SOURCE_NAME,
        source_id=event.source_id,
        source_url=event.source_url,
        source_record_hash=source_record_hash,
        source_payload_hash=source_payload_hash,
        collected_at=collected_at or datetime.now(timezone.utc),
        parser_version=event.parser_version,
    )


def _insert_candidate(cursor: sqlite3.Cursor, candidate: EventCandidate) -> None:
    cursor.execute(
        """
        INSERT INTO events (
            title, description, attendees, police_station, location_name, location_address,
            latitude, longitude, start_date, end_date, category, severity_level, status,
            source, source_id, source_url, source_record_hash, source_payload_hash,
            collected_at, parser_version
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            candidate.title,
            candidate.description,
            candidate.attendees,
            candidate.police_station,
            candidate.location_name,
            candidate.location_address,
            candidate.latitude,
            candidate.longitude,
            candidate.start_date,
            candidate.end_date,
            candidate.category,
            candidate.severity_level,
            candidate.source,
            candidate.source_id,
            candidate.source_url,
            candidate.source_record_hash,
            candidate.source_payload_hash,
            candidate.collected_at,
            candidate.parser_version,
        ),
    )


def _update_candidate(cursor: sqlite3.Cursor, candidate: EventCandidate, event_id: int) -> None:
    cursor.execute(
        """
        UPDATE events
           SET title = ?,
               description = ?,
               attendees = ?,
               police_station = ?,
               location_name = ?,
               location_address = ?,
               latitude = ?,
               longitude = ?,
               start_date = ?,
               end_date = ?,
               category = ?,
               severity_level = ?,
               source = ?,
               source_id = ?,
               source_url = ?,
               source_payload_hash = ?,
               collected_at = ?,
               parser_version = ?,
               updated_at = CURRENT_TIMESTAMP
         WHERE id = ?
        """,
        (
            candidate.title,
            candidate.description,
            candidate.attendees,
            candidate.police_station,
            candidate.location_name,
            candidate.location_address,
            candidate.latitude,
            candidate.longitude,
            candidate.start_date,
            candidate.end_date,
            candidate.category,
            candidate.severity_level,
            candidate.source,
            candidate.source_id,
            candidate.source_url,
            candidate.source_payload_hash,
            candidate.collected_at,
            candidate.parser_version,
            event_id,
        ),
    )


def sync_event_candidates(
    conn: sqlite3.Connection,
    candidates: list[EventCandidate],
) -> SyncResult:
    """SMPA 이벤트 후보를 실제 SQLite DB에 동기화한다."""
    inserted = updated = skipped = errors = 0
    cursor = conn.cursor()

    for candidate in candidates:
        if not candidate.source_record_hash:
            errors += 1
            continue

        cursor.execute(
            "SELECT id, source_payload_hash FROM events WHERE source_record_hash = ?",
            (candidate.source_record_hash,),
        )
        existing = cursor.fetchone()
        if existing is None:
            _insert_candidate(cursor, candidate)
            inserted += 1
            continue

        if existing["source_payload_hash"] == candidate.source_payload_hash:
            skipped += 1
            continue

        _update_candidate(cursor, candidate, existing["id"])
        updated += 1

    conn.commit()
    return SyncResult(inserted=inserted, updated=updated, skipped=skipped, errors=errors)
