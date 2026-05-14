"""User settings/preference repository integration tests."""
import os
import sqlite3
import tempfile
from datetime import datetime
from typing import Iterator

import pytest

from app.database.models import USERS_TABLE_SCHEMA
from app.repositories.user_preference_repository import UserPreferenceRepository
from app.repositories.user_settings_repository import UserSettingsRepository


@pytest.fixture
def user_settings_db_pair() -> Iterator[tuple[sqlite3.Connection, sqlite3.Connection]]:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    writer = sqlite3.connect(db_path)
    reader = sqlite3.connect(db_path)
    writer.row_factory = sqlite3.Row
    reader.row_factory = sqlite3.Row
    writer.execute(USERS_TABLE_SCHEMA)
    writer.commit()

    try:
        yield writer, reader
    finally:
        writer.close()
        reader.close()
        try:
            os.remove(db_path)
        except FileNotFoundError:
            pass


def _insert_user(
    db: sqlite3.Connection,
    *,
    bot_user_key: str,
    plusfriend_user_key: str | None = None,
) -> None:
    db.execute(
        """
        INSERT INTO users (
            bot_user_key, plusfriend_user_key, first_message_at, last_message_at,
            message_count, active, is_alarm_on
        )
        VALUES (?, ?, ?, ?, 1, 1, 1)
        """,
        (bot_user_key, plusfriend_user_key, "2026-05-12T09:00:00", "2026-05-12T09:00:00"),
    )


def _user_row(db: sqlite3.Connection, bot_user_key: str) -> sqlite3.Row:
    row = db.execute(
        "SELECT * FROM users WHERE bot_user_key = ?",
        (bot_user_key,),
    ).fetchone()
    assert row is not None
    return row


def test_alarm_and_favorite_updates_prefer_plusfriend_before_bot(user_settings_db_pair):
    writer, reader = user_settings_db_pair
    _insert_user(writer, bot_user_key="bot-owner", plusfriend_user_key="shared-id")
    _insert_user(writer, bot_user_key="shared-id")
    writer.commit()

    alarm_count = UserSettingsRepository.update_alarm_setting(
        writer,
        user_id="shared-id",
        is_alarm_on=False,
    )
    zone_count = UserSettingsRepository.update_favorite_zone(
        writer,
        user_id="shared-id",
        zone=2,
    )

    assert alarm_count == 1
    assert zone_count == 1
    assert _user_row(reader, "bot-owner")["is_alarm_on"] == 1
    assert _user_row(reader, "shared-id")["is_alarm_on"] == 1

    writer.commit()

    plusfriend_row = _user_row(reader, "bot-owner")
    bot_row = _user_row(reader, "shared-id")
    assert plusfriend_row["is_alarm_on"] == 0
    assert plusfriend_row["favorite_zone"] == 2
    assert bot_row["is_alarm_on"] == 1
    assert bot_row["favorite_zone"] is None


def test_marked_bus_falls_back_to_bot_user_key(user_settings_db_pair):
    writer, reader = user_settings_db_pair
    _insert_user(writer, bot_user_key="bot-only")
    writer.commit()

    rowcount = UserSettingsRepository.update_marked_bus(
        writer,
        user_id="bot-only",
        marked_bus="470",
        now=datetime(2026, 5, 12, 10, 0, 0),
    )

    assert rowcount == 1
    assert _user_row(reader, "bot-only")["marked_bus"] is None

    writer.commit()

    saved = _user_row(reader, "bot-only")
    assert saved["marked_bus"] == "470"
    assert saved["last_message_at"] == "2026-05-12 10:00:00"


def test_preferences_keep_bot_user_key_only_lookup(user_settings_db_pair):
    writer, reader = user_settings_db_pair
    _insert_user(writer, bot_user_key="bot-owner", plusfriend_user_key="shared-id")
    _insert_user(writer, bot_user_key="shared-id")
    writer.commit()

    assert UserPreferenceRepository.exists_by_bot_user_key(writer, "shared-id") is True
    rowcount = UserPreferenceRepository.update_preferences(
        writer,
        user_id="shared-id",
        marked_bus="7016",
        language="ko",
    )

    assert rowcount == 1
    writer.commit()

    plusfriend_row = _user_row(reader, "bot-owner")
    bot_row = _user_row(reader, "shared-id")
    assert plusfriend_row["marked_bus"] is None
    assert plusfriend_row["language"] is None
    assert bot_row["marked_bus"] == "7016"
    assert bot_row["language"] == "ko"
