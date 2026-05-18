from datetime import datetime, timedelta, timezone

import pytest

from app.utils.time_utils import (
    EPOCH_MILLISECONDS_THRESHOLD,
    KST,
    format_kst_wall_clock_for_db,
    format_utc_datetime_for_db,
    parse_db_timestamp,
    parse_datetime_value,
    utc_now,
    utc_now_for_db,
)


def test_utc_now_returns_timezone_aware_utc_datetime():
    value = utc_now()

    assert value.tzinfo is not None
    assert value.utcoffset() == timedelta(0)


def test_utc_storage_format_requires_aware_datetime():
    with pytest.raises(ValueError):
        format_utc_datetime_for_db(datetime(2026, 5, 16, 1, 0, 0))


def test_utc_storage_format_uses_offset_iso_seconds_precision():
    value = datetime(2026, 5, 16, 10, 0, 1, 987654, tzinfo=KST)

    assert format_utc_datetime_for_db(value) == "2026-05-16T01:00:01+00:00"
    assert utc_now_for_db().endswith("+00:00")


def test_parse_db_timestamp_applies_explicit_legacy_source_timezone():
    legacy_kst = parse_db_timestamp("2026-05-16 10:00:00", naive_source_tz=KST)
    sqlite_utc = parse_db_timestamp("2026-05-16 01:00:00", naive_source_tz=timezone.utc)
    aware_utc = parse_db_timestamp("2026-05-16T01:00:00+00:00", naive_source_tz=KST)

    assert legacy_kst is not None
    assert legacy_kst.tzinfo == KST
    assert sqlite_utc is not None
    assert sqlite_utc.utcoffset() == timedelta(0)
    assert aware_utc is not None
    assert aware_utc.utcoffset() == timedelta(0)


def test_parse_datetime_value_treats_epoch_threshold_as_milliseconds():
    parsed = parse_datetime_value(EPOCH_MILLISECONDS_THRESHOLD)

    assert parsed == datetime.fromtimestamp(
        EPOCH_MILLISECONDS_THRESHOLD / 1000,
        tz=timezone.utc,
    )


def test_kst_wall_clock_storage_preserves_naive_smpa_schedule():
    assert (
        format_kst_wall_clock_for_db(datetime(2026, 5, 16, 10, 30, 45, 123456))
        == "2026-05-16 10:30:45"
    )
