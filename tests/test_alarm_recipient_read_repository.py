"""Alarm recipient read repository integration tests."""
import os
import sqlite3
import tempfile
from typing import Iterator

import pytest

from app.database.models import USERS_TABLE_SCHEMA
from app.repositories.alarm_recipient_read_repository import AlarmRecipientReadRepository


@pytest.fixture
def recipient_db() -> Iterator[sqlite3.Connection]:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(USERS_TABLE_SCHEMA)
    conn.commit()

    try:
        yield conn
    finally:
        conn.close()
        try:
            os.remove(db_path)
        except FileNotFoundError:
            pass


def _insert_user(
    db: sqlite3.Connection,
    *,
    bot_user_key: str | None,
    plusfriend_user_key: str | None,
    active: int = 1,
    is_alarm_on: int = 1,
    marked_bus: str | None = None,
    location: str | None = None,
    has_route: bool = False,
) -> None:
    route_values = (127.0, 37.5, 126.9, 37.4) if has_route else (None, None, None, None)
    db.execute(
        """
        INSERT INTO users (
            bot_user_key, plusfriend_user_key, first_message_at, last_message_at,
            message_count, active, is_alarm_on, marked_bus, location,
            departure_x, departure_y, arrival_x, arrival_y
        )
        VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            bot_user_key,
            plusfriend_user_key,
            active,
            is_alarm_on,
            marked_bus,
            location,
            *route_values,
        ),
    )


def test_list_active_recipients_preserves_plusfriend_and_bot_separation(recipient_db):
    _insert_user(recipient_db, bot_user_key="bot-with-pf", plusfriend_user_key="pf-1")
    _insert_user(recipient_db, bot_user_key="bot-only", plusfriend_user_key=None)
    _insert_user(recipient_db, bot_user_key="inactive", plusfriend_user_key="pf-inactive", active=0)
    _insert_user(recipient_db, bot_user_key="off", plusfriend_user_key="pf-off", is_alarm_on=0)
    recipient_db.commit()

    recipients = AlarmRecipientReadRepository.list_active_recipients(recipient_db)

    assert recipients == {
        "plusfriend_user_keys": ["pf-1"],
        "bot_user_keys": ["bot-only"],
    }


def test_list_filtered_recipients_applies_marked_bus_location_and_route_filters(recipient_db):
    _insert_user(
        recipient_db,
        bot_user_key="bot-with-pf",
        plusfriend_user_key="pf-1",
        marked_bus="470",
        location="서울 종로",
        has_route=True,
    )
    _insert_user(
        recipient_db,
        bot_user_key="bot-only",
        plusfriend_user_key=None,
        marked_bus="470",
        location="서울 종로",
        has_route=True,
    )
    _insert_user(
        recipient_db,
        bot_user_key="wrong-bus",
        plusfriend_user_key="pf-wrong-bus",
        marked_bus="7016",
        location="서울 종로",
        has_route=True,
    )
    _insert_user(
        recipient_db,
        bot_user_key="no-route",
        plusfriend_user_key="pf-no-route",
        marked_bus="470",
        location="서울 종로",
        has_route=False,
    )
    recipient_db.commit()

    recipients = AlarmRecipientReadRepository.list_filtered_recipients(
        recipient_db,
        filter_location="종로",
        filter_marked_bus="470",
        filter_has_route=True,
    )

    assert recipients == {
        "plusfriend_user_keys": ["pf-1"],
        "bot_user_keys": ["bot-only"],
    }
