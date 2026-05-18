"""DB timestamp 저장 계약을 한 곳에서 다루는 유틸리티."""

from __future__ import annotations

from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo

UTC = timezone.utc
KST_ZONE_NAME = "Asia/Seoul"
KST = ZoneInfo(KST_ZONE_NAME)
DB_TIMESTAMP_TIMESPEC = "seconds"
EPOCH_MILLISECONDS_THRESHOLD = 1_000_000_000_000


def utc_now() -> datetime:
    """현재 시각을 timezone-aware UTC datetime으로 반환한다."""
    return datetime.now(UTC)


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def format_utc_datetime_for_db(value: datetime) -> str:
    """시점 timestamp를 UTC offset 포함 ISO-8601 문자열로 직렬화한다."""
    if not _is_aware(value):
        raise ValueError("UTC DB timestamp requires a timezone-aware datetime")

    return (
        value.astimezone(UTC)
        .replace(microsecond=0)
        .isoformat(timespec=DB_TIMESTAMP_TIMESPEC)
    )


def utc_now_for_db() -> str:
    """신규 DB write path에 사용할 UTC-aware 저장 문자열을 반환한다."""
    return format_utc_datetime_for_db(utc_now())


def format_kst_wall_clock_for_db(value: datetime) -> str:
    """SMPA 서울 현지 일정 wall-clock 값을 시간 이동 없이 저장 문자열로 만든다."""
    if _is_aware(value):
        value = value.astimezone(KST).replace(tzinfo=None)

    return value.replace(microsecond=0).isoformat(
        sep=" ",
        timespec=DB_TIMESTAMP_TIMESPEC,
    )


def parse_datetime_value(value: object) -> datetime | None:
    """DB/API에서 온 timestamp 값을 datetime으로 파싱한다."""
    if value in (None, ""):
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, (int, float)):
        return _datetime_from_epoch(value)

    text = str(value).strip()
    if not text:
        return None

    if text.isdigit() and len(text) >= 10:
        parsed_epoch = _datetime_from_epoch(int(text))
        if parsed_epoch is not None:
            return parsed_epoch

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_db_timestamp(value: object, *, naive_source_tz: tzinfo) -> datetime | None:
    """legacy naive timestamp에 명시 source timezone 정책을 적용해 파싱한다."""
    parsed = parse_datetime_value(value)
    if parsed is None:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=naive_source_tz)

    return parsed


def _datetime_from_epoch(value: int | float) -> datetime | None:
    timestamp = float(value)
    if timestamp >= EPOCH_MILLISECONDS_THRESHOLD:
        timestamp /= 1000.0
    try:
        return datetime.fromtimestamp(timestamp, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
