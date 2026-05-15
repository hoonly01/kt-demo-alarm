import os

import pytest

from app.services.crawling.smpa_parser import (
    extract_smpa_detail_text,
    parse_smpa_events_from_html,
    target_date_from_title,
)
from app.services.crawling.smpa_source import fetch_recent_smpa_posts, fetch_smpa_text


@pytest.mark.asyncio
async def test_smpa_list_and_detail_live_smoke():
    if os.environ.get("RUN_LIVE_SMPA") != "1":
        pytest.skip("RUN_LIVE_SMPA=1 이 설정되지 않아 live SMPA smoke를 건너뜁니다.")

    posts = await fetch_recent_smpa_posts(limit=1)

    assert posts
    assert posts[0].board_no
    detail_html = await fetch_smpa_text(posts[0].detail_url)
    detail_text = extract_smpa_detail_text(detail_html)
    for required_text in ("집회 일시", "집회 장소", "신고 인원", "관할서"):
        assert required_text in detail_text

    events = parse_smpa_events_from_html(
        detail_html,
        target_date_from_title(posts[0].title),
        posts[0].board_no,
        posts[0].detail_url,
    )
    assert events
