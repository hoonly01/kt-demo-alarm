"""User route read repository integration tests."""
import os
import sqlite3
import tempfile
from typing import Iterator

import pytest

from app.database.models import USERS_TABLE_SCHEMA
from app.repositories.user_route_read_repository import UserRouteReadRepository


@pytest.fixture
def route_read_db() -> Iterator[sqlite3.Connection]:
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


def _insert_route_user(
    db: sqlite3.Connection,
    *,
    bot_user_key: str | None,
    plusfriend_user_key: str | None,
    active: int = 1,
    is_alarm_on: int = 1,
    has_route: bool = True,
) -> None:
    route_values = (
        "출발",
        "출발 주소",
        127.0,
        37.5,
        "도착",
        "도착 주소",
        126.9,
        37.4,
    ) if has_route else (None, None, None, None, None, None, None, None)
    db.execute(
        """
        INSERT INTO users (
            bot_user_key, plusfriend_user_key, first_message_at, last_message_at,
            message_count, active, is_alarm_on,
            departure_name, departure_address, departure_x, departure_y,
            arrival_name, arrival_address, arrival_x, arrival_y
        )
        VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (bot_user_key, plusfriend_user_key, active, is_alarm_on, *route_values),
    )


def test_get_route_for_user_supports_plusfriend_and_bot_lookup(route_read_db):
    _insert_route_user(route_read_db, bot_user_key="bot-1", plusfriend_user_key="pf-1")
    _insert_route_user(route_read_db, bot_user_key="bot-only", plusfriend_user_key=None)
    route_read_db.commit()

    plusfriend_route = UserRouteReadRepository.get_route_for_user(route_read_db, "pf-1")
    bot_route = UserRouteReadRepository.get_route_for_user(route_read_db, "bot-only")

    assert plusfriend_route is not None
    assert plusfriend_route["departure_name"] == "출발"
    assert bot_route is not None
    assert bot_route["arrival_name"] == "도착"


def test_list_scheduled_route_users_requires_plusfriend_and_route(route_read_db):
    _insert_route_user(route_read_db, bot_user_key="bot-1", plusfriend_user_key="pf-1")
    _insert_route_user(route_read_db, bot_user_key="bot-only", plusfriend_user_key=None)
    _insert_route_user(route_read_db, bot_user_key="off", plusfriend_user_key="pf-off", is_alarm_on=0)
    _insert_route_user(route_read_db, bot_user_key="no-route", plusfriend_user_key="pf-no-route", has_route=False)
    route_read_db.commit()

    users = UserRouteReadRepository.list_scheduled_route_users(route_read_db)

    assert users == [
        {
            "plusfriend_user_key": "pf-1",
            "departure_name": "출발",
            "arrival_name": "도착",
        }
    ]


def test_list_auto_check_route_user_ids_uses_coalesced_plusfriend_then_bot(route_read_db):
    _insert_route_user(route_read_db, bot_user_key="bot-1", plusfriend_user_key="pf-1")
    _insert_route_user(route_read_db, bot_user_key="bot-only", plusfriend_user_key=None)
    _insert_route_user(route_read_db, bot_user_key="inactive", plusfriend_user_key="pf-inactive", active=0)
    route_read_db.commit()

    users = UserRouteReadRepository.list_auto_check_route_user_ids(route_read_db)

    assert users == [{"user_id": "pf-1"}, {"user_id": "bot-only"}]
