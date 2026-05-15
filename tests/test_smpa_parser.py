from datetime import date, datetime

from app.services.crawling.smpa_parser import (
    extract_smpa_detail_text,
    normalize_attendees,
    parse_smpa_events_from_html,
    parse_smpa_list_posts,
    target_date_from_title,
)
from app.services.crawling.smpa_source import build_smpa_detail_url


LIST_HTML = """
<table>
  <tr>
    <td>5499</td>
    <td><a href="javascript:goBoardView('/user/nd54882.do','View','00336270');">오늘의 집회 260515 금</a></td>
    <td>오늘의-주요집회-담당</td>
    <td>2026-05-14</td>
    <td>618</td>
  </tr>
</table>
"""

DETAIL_HTML = """
<html><body>
<h3>공지사항 상세</h3>
1.
집회 일시 : 11:00~13:00
집회 장소 : 교보빌딩 남측 -> 청진공원 <세종로>
신고 인원 : 100
관할서 : 종로
2.
집회 일시 : 19:00~20:30
집회 장소 : 송현공원 앞
신고 인원 :
관할서 : 종로
이전글
</body></html>
"""


def test_parse_smpa_list_posts_extracts_board_no_and_title():
    posts = parse_smpa_list_posts(LIST_HTML)

    assert len(posts) == 1
    assert posts[0].title == "오늘의 집회 260515 금"
    assert posts[0].board_no == "00336270"
    assert posts[0].date_text == "2026-05-14"
    assert build_smpa_detail_url(posts[0].board_no).endswith("boardNo=00336270")


def test_parse_smpa_detail_html_extracts_required_fields():
    events = parse_smpa_events_from_html(
        DETAIL_HTML,
        date(2026, 5, 15),
        "00336270",
        "https://smpa.go.kr/user/nd54882.do?View&boardNo=00336270",
    )

    assert len(events) == 2
    first = events[0]
    assert first.raw_location == "교보빌딩 남측 -> 청진공원 <세종로>"
    assert first.endpoint_candidates == ("교보빌딩 남측", "청진공원")
    assert first.attendees == "100명"
    assert first.police_station == "종로"
    assert first.start_date == datetime(2026, 5, 15, 11, 0)
    assert first.end_date == datetime(2026, 5, 15, 13, 0)
    assert first.source_id == "00336270"
    assert events[1].attendees == "미상"


def test_extract_detail_text_keeps_smpa_body_fields():
    text = extract_smpa_detail_text(DETAIL_HTML)

    assert "집회 일시 : 11:00~13:00" in text
    assert "집회 장소 : 교보빌딩 남측 -> 청진공원 <세종로>" in text
    assert "신고 인원 : 100" in text
    assert "관할서 : 종로" in text


def test_title_date_and_attendees_normalization():
    assert target_date_from_title("오늘의 집회 260515 금") == date(2026, 5, 15)
    assert normalize_attendees("") == "미상"
    assert normalize_attendees("10,000") == "10,000명"
    assert normalize_attendees("약 100명") == "약 100명"
