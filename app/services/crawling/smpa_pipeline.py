"""SMPA 게시글 수집부터 events 동기화까지의 공개 파이프라인."""

from __future__ import annotations

import logging

from app.database.connection import get_db_connection
from app.services.crawling.smpa_coordinates import select_coordinate_for_event
from app.services.crawling.smpa_event_sync import (
    EventCandidate,
    SyncResult,
    prepare_event_candidate,
    sync_event_candidates,
)
from app.services.crawling.smpa_parser import (
    parse_smpa_events_from_html,
    target_date_from_title,
)
from app.services.crawling.smpa_source import fetch_recent_smpa_posts, fetch_smpa_text

logger = logging.getLogger(__name__)


async def crawl_and_sync_smpa_events() -> dict[str, int]:
    """서울경찰청 오늘의 집회/시위 게시글을 수집해 events 테이블에 반영한다."""
    posts = await fetch_recent_smpa_posts()
    candidates: list[EventCandidate] = []
    coordinate_errors = 0

    for post in posts:
        detail_html = await fetch_smpa_text(post.detail_url)
        parsed_events = parse_smpa_events_from_html(
            detail_html,
            target_date_from_title(post.title),
            post.board_no,
            post.detail_url,
        )

        for parsed_event in parsed_events:
            selected_coordinate = await select_coordinate_for_event(parsed_event)
            if selected_coordinate is None:
                coordinate_errors += 1
                logger.warning("대표 좌표 선택 실패: %s", parsed_event.raw_location)
                continue
            candidates.append(prepare_event_candidate(parsed_event, selected_coordinate))

    with get_db_connection() as conn:
        result = sync_event_candidates(conn, candidates)

    merged = SyncResult(
        inserted=result.inserted,
        updated=result.updated,
        skipped=result.skipped,
        errors=result.errors + coordinate_errors,
    )
    logger.info("SMPA 동기화 결과: %s", merged.to_dict())
    return merged.to_dict()
