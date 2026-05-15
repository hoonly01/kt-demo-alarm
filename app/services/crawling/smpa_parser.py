"""SMPA 상세 HTML/text를 집회 원천 레코드로 파싱한다."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Iterable

from bs4 import BeautifulSoup

PARSER_VERSION = "smpa-html-v1"
UNKNOWN_ATTENDEES = "미상"
SMPA_SOURCE_NAME = "SMPA"
LIST_ROW_VIEW_RE = re.compile(r"goBoardView\('([^']+)','([^']+)','([^']+)'\)")
DETAIL_ENTRY_RE = re.compile(
    r"(?:^|\n)\s*(?P<seq>\d+)\.\s*\n"
    r"\s*집회\s*일시\s*:\s*(?P<time>[^\n]+)\n"
    r"\s*집회\s*장소\s*:\s*(?P<location>[^\n]+)\n"
    r"\s*신고\s*인원\s*:\s*(?P<attendees>[^\n]*)\n"
    r"\s*관할서\s*:\s*(?P<station>.*?)(?=\n\s*\d+\.\s*\n\s*집회\s*일시|\n이전글|\Z)",
    re.S,
)
TIME_RANGE_RE = re.compile(r"(?P<start>\d{1,2}:\d{2})\s*[~∼-]\s*(?P<end>\d{1,2}:\d{2})")
TITLE_DATE_RE = re.compile(r"(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})")


@dataclass(frozen=True)
class SmpaListPost:
    """SMPA 목록 row."""

    title: str
    board_no: str
    date_text: str = ""
    detail_url: str = ""

    def with_detail_url(self, detail_url: str) -> "SmpaListPost":
        return replace(self, detail_url=detail_url)


@dataclass(frozen=True)
class ParsedSmpaEvent:
    """상세 본문에서 얻은 집회 원천 레코드."""

    title: str
    raw_location: str
    endpoint_candidates: tuple[str, ...]
    attendees: str
    police_station: str
    start_date: datetime
    end_date: datetime
    source_id: str
    source_url: str
    parser_version: str = PARSER_VERSION


def _clean_text(value: str) -> str:
    return html.unescape(" ".join(value.split())).strip()


def parse_smpa_list_posts(html_text: str) -> list[SmpaListPost]:
    """SMPA 목록 HTML에서 boardNo 기반 게시글 목록을 추출한다."""
    rows: list[SmpaListPost] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html_text, flags=re.I | re.S):
        match = LIST_ROW_VIEW_RE.search(tr)
        if not match:
            continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.I | re.S)
        title = _clean_text(BeautifulSoup(cells[1], "html.parser").get_text(" ")) if len(cells) > 1 else ""
        date_text = _clean_text(BeautifulSoup(cells[3], "html.parser").get_text(" ")) if len(cells) > 3 else ""
        rows.append(SmpaListPost(title=title, board_no=match.group(3), date_text=date_text))
    return rows


def extract_smpa_detail_text(html_text: str) -> str:
    """상세 HTML에서 script/style을 제외한 사람이 읽는 텍스트를 줄 단위로 추출한다."""
    soup = BeautifulSoup(html_text, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    lines = [_clean_text(line) for line in soup.get_text("\n").splitlines()]
    return "\n".join(line for line in lines if line)


def target_date_from_title(title: str, fallback: date | None = None) -> date:
    """`오늘의 집회 260515 금` 형식 제목에서 대상 날짜를 얻는다."""
    match = TITLE_DATE_RE.search(title)
    if match:
        return date(
            year=2000 + int(match.group("yy")),
            month=int(match.group("mm")),
            day=int(match.group("dd")),
        )
    if fallback is not None:
        return fallback
    return datetime.now().date()


def normalize_attendees(value: str | None) -> str:
    """신고 인원 표시값을 적재 전 기본값까지 정규화한다."""
    text = _clean_text(value or "")
    if not text or text in {"-", "미정", "없음"}:
        return UNKNOWN_ATTENDEES
    if re.fullmatch(r"[\d,]+", text):
        return f"{text}명"
    return text


def parse_time_range(target_date: date, value: str) -> tuple[datetime, datetime]:
    """상세의 `HH:MM~HH:MM` 값을 시작/종료 datetime으로 변환한다."""
    match = TIME_RANGE_RE.search(value)
    if not match:
        start = datetime.combine(target_date, time.min)
        return start, start

    start_time = time.fromisoformat(match.group("start"))
    end_time = time.fromisoformat(match.group("end"))
    start_at = datetime.combine(target_date, start_time)
    end_at = datetime.combine(target_date, end_time)
    if end_at < start_at:
        end_at += timedelta(days=1)
    return start_at, end_at


def split_endpoint_candidates(raw_location: str) -> tuple[str, ...]:
    """원문 장소/경로에서 지오코딩 후보 endpoint를 추출한다."""
    without_angle_notes = re.sub(r"<[^>]+>", " ", raw_location)
    parts = [
        _clean_text(part)
        for part in re.split(r"\s*(?:->|→|↔|/)\s*", without_angle_notes)
        if _clean_text(part)
    ]
    if not parts:
        cleaned = _clean_text(without_angle_notes)
        return (cleaned,) if cleaned else ()
    if len(parts) == 1:
        return (parts[0],)
    return (parts[0], parts[-1])


def parse_smpa_events_from_text(
    text: str,
    target_date: date,
    board_no: str,
    source_url: str,
) -> list[ParsedSmpaEvent]:
    """상세 텍스트에서 집회 레코드들을 파싱한다."""
    events: list[ParsedSmpaEvent] = []
    for match in DETAIL_ENTRY_RE.finditer(text):
        raw_location = _clean_text(match.group("location"))
        start_at, end_at = parse_time_range(target_date, match.group("time"))
        police_station = _clean_text(match.group("station"))
        title_location = raw_location.split("<", 1)[0].strip()
        events.append(
            ParsedSmpaEvent(
                title=f"SMPA 집회 - {title_location}",
                raw_location=raw_location,
                endpoint_candidates=split_endpoint_candidates(raw_location),
                attendees=normalize_attendees(match.group("attendees")),
                police_station=police_station,
                start_date=start_at,
                end_date=end_at,
                source_id=board_no,
                source_url=source_url,
            )
        )
    return events


def parse_smpa_events_from_html(
    html_text: str,
    target_date: date,
    board_no: str,
    source_url: str,
) -> list[ParsedSmpaEvent]:
    """상세 HTML에서 집회 레코드를 파싱한다."""
    return parse_smpa_events_from_text(
        extract_smpa_detail_text(html_text),
        target_date,
        board_no,
        source_url,
    )


def flatten_events(groups: Iterable[Iterable[ParsedSmpaEvent]]) -> list[ParsedSmpaEvent]:
    """게시글별 이벤트 묶음을 단일 리스트로 평탄화한다."""
    return [event for group in groups for event in group]
