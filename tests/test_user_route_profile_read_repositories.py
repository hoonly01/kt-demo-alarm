"""사용자 route/profile/read 저장소 통합 테스트."""
import os
import sqlite3
import tempfile
from datetime import datetime
from typing import Iterator

import pytest

from app.database.models import USERS_TABLE_SCHEMA
from app.repositories.user_profile_repository import UserProfileRepository
from app.repositories.user_read_repository import UserReadRepository
from app.repositories.user_route_repository import UserRouteRepository


ROUTE_NOW = datetime(2026, 5, 12, 10, 30, 0)
PROFILE_NOW = datetime(2026, 5, 12, 11, 30, 0)

DEPARTURE_INFO = {
    "name": "출발지",
    "address": "서울 출발 주소",
    "x": 127.01,
    "y": 37.51,
}

ARRIVAL_INFO = {
    "name": "도착지",
    "address": "서울 도착 주소",
    "x": 126.98,
    "y": 37.56,
}


@pytest.fixture
def user_repo_db() -> Iterator[sqlite3.Connection]:
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
    bot_user_key: str,
    plusfriend_user_key: str | None,
) -> None:
    db.execute(
        """
        INSERT INTO users (
            bot_user_key, plusfriend_user_key, first_message_at, last_message_at,
            message_count, active, is_alarm_on
        )
        VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, 1, 1)
        """,
        (bot_user_key, plusfriend_user_key),
    )
    db.commit()


def test_route_repository_updates_plusfriend_route(user_repo_db):
    _insert_user(user_repo_db, bot_user_key="bot-route", plusfriend_user_key="pf-route")

    updated_count = UserRouteRepository.update_route(
        user_repo_db,
        user_id="pf-route",
        departure_info=DEPARTURE_INFO,
        arrival_info=ARRIVAL_INFO,
        now=ROUTE_NOW,
    )

    assert updated_count == 1

    route = UserReadRepository.get_route_info_by_bot_user_key(user_repo_db, "bot-route")

    assert route is not None
    assert route["departure_name"] == "출발지"
    assert route["departure_address"] == "서울 출발 주소"
    assert route["departure_x"] == 127.01
    assert route["arrival_name"] == "도착지"
    assert route["arrival_address"] == "서울 도착 주소"
    assert route["arrival_y"] == 37.56
    assert route["route_updated_at"] == str(ROUTE_NOW)


def test_route_repository_clear_route_falls_back_to_bot_user_key(user_repo_db):
    _insert_user(user_repo_db, bot_user_key="bot-only", plusfriend_user_key=None)
    UserRouteRepository.update_route(
        user_repo_db,
        user_id="missing-plusfriend",
        departure_info=DEPARTURE_INFO,
        arrival_info=ARRIVAL_INFO,
        now=ROUTE_NOW,
    )
    user_repo_db.execute(
        """
        UPDATE users
        SET departure_name = ?, departure_address = ?, departure_x = ?, departure_y = ?,
            arrival_name = ?, arrival_address = ?, arrival_x = ?, arrival_y = ?,
            route_updated_at = ?
        WHERE bot_user_key = ?
        """,
        (
            DEPARTURE_INFO["name"],
            DEPARTURE_INFO["address"],
            DEPARTURE_INFO["x"],
            DEPARTURE_INFO["y"],
            ARRIVAL_INFO["name"],
            ARRIVAL_INFO["address"],
            ARRIVAL_INFO["x"],
            ARRIVAL_INFO["y"],
            ROUTE_NOW,
            "bot-only",
        ),
    )
    user_repo_db.commit()

    updated_count = UserRouteRepository.clear_route(
        user_repo_db,
        user_id="bot-only",
        now=PROFILE_NOW,
    )

    assert updated_count == 1

    route = UserReadRepository.get_route_info_by_bot_user_key(user_repo_db, "bot-only")

    assert route is not None
    assert route["departure_name"] is None
    assert route["departure_x"] is None
    assert route["arrival_name"] is None
    assert route["arrival_y"] is None
    assert route["route_updated_at"] == str(PROFILE_NOW)


def test_profile_repository_updates_route_and_preferences(user_repo_db):
    _insert_user(user_repo_db, bot_user_key="bot-profile", plusfriend_user_key="pf-profile")

    updated_count = UserProfileRepository.update_profile(
        user_repo_db,
        plusfriend_user_key="pf-profile",
        departure_info=DEPARTURE_INFO,
        arrival_info=ARRIVAL_INFO,
        marked_bus="7016",
        language="ko",
        now=PROFILE_NOW,
    )

    assert updated_count == 1

    user_info = UserReadRepository.get_user_info(user_repo_db, "pf-profile")

    assert user_info is not None
    assert user_info["marked_bus"] == "7016"
    assert user_info["departure_name"] == "출발지"
    assert user_info["arrival_name"] == "도착지"
    assert user_info["plusfriend_user_key"] == "pf-profile"
    assert user_info["bot_user_key"] == "bot-profile"


def test_read_repository_preserves_plusfriend_priority_and_bot_fallback(user_repo_db):
    _insert_user(user_repo_db, bot_user_key="shared-id", plusfriend_user_key="pf-first")
    _insert_user(user_repo_db, bot_user_key="bot-fallback", plusfriend_user_key=None)
    user_repo_db.execute(
        "UPDATE users SET marked_bus = ?, departure_name = ? WHERE plusfriend_user_key = ?",
        ("plus-bus", "plus-departure", "pf-first"),
    )
    user_repo_db.execute(
        "UPDATE users SET marked_bus = ?, departure_name = ? WHERE bot_user_key = ?",
        ("bot-bus", "bot-departure", "bot-fallback"),
    )
    user_repo_db.commit()

    plusfriend_info = UserReadRepository.get_user_info(user_repo_db, "pf-first")
    bot_info = UserReadRepository.get_user_info(user_repo_db, "bot-fallback")

    assert plusfriend_info is not None
    assert plusfriend_info["marked_bus"] == "plus-bus"
    assert plusfriend_info["departure_name"] == "plus-departure"
    assert bot_info is not None
    assert bot_info["marked_bus"] == "bot-bus"
    assert bot_info["departure_name"] == "bot-departure"
