"""User identity repository integration tests."""
import os
import sqlite3
import tempfile
from datetime import datetime
from typing import Iterator

import pytest

from app.database.models import USERS_TABLE_SCHEMA
from app.repositories.user_identity_repository import UserIdentityRepository


@pytest.fixture
def user_identity_db_pair() -> Iterator[tuple[sqlite3.Connection, sqlite3.Connection]]:
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


def test_insert_bot_user_uses_caller_transaction(user_identity_db_pair):
    writer, reader = user_identity_db_pair
    now = datetime(2026, 5, 12, 9, 0, 0)

    UserIdentityRepository.insert_bot_user(writer, bot_user_key="bot-1", now=now)

    assert UserIdentityRepository.find_by_bot_user_key(writer, "bot-1") is not None
    assert UserIdentityRepository.find_by_bot_user_key(reader, "bot-1") is None

    writer.commit()

    saved = UserIdentityRepository.find_by_bot_user_key(reader, "bot-1")
    assert saved is not None
    assert saved["bot_user_key"] == "bot-1"
    assert saved["plusfriend_user_key"] is None


def test_identity_link_methods_return_rowcounts_without_committing(user_identity_db_pair):
    writer, reader = user_identity_db_pair
    now = datetime(2026, 5, 12, 9, 0, 0)
    UserIdentityRepository.insert_bot_user(writer, bot_user_key="bot-1", now=now)
    writer.commit()

    rowcount = UserIdentityRepository.link_plusfriend_to_bot(
        writer,
        bot_user_key="bot-1",
        plusfriend_key="pf-1",
        now=datetime(2026, 5, 12, 9, 1, 0),
    )

    assert rowcount == 1
    before_commit = UserIdentityRepository.find_by_bot_user_key(reader, "bot-1")
    assert before_commit is not None
    assert before_commit["plusfriend_user_key"] is None

    writer.commit()

    after_commit = UserIdentityRepository.find_by_plusfriend_key(reader, "pf-1")
    assert after_commit is not None
    assert after_commit["bot_user_key"] == "bot-1"
    assert after_commit["plusfriend_user_key"] == "pf-1"
    assert after_commit["message_count"] == 2


def test_orphan_lookup_and_link_uses_oldest_unlinked_user(user_identity_db_pair):
    writer, reader = user_identity_db_pair
    writer.execute(
        """
        INSERT INTO users (open_id, first_message_at, last_message_at, message_count, active)
        VALUES (?, ?, ?, 1, 1)
        """,
        ("old-open", "2026-05-12T08:00:00", "2026-05-12T08:00:00"),
    )
    writer.execute(
        """
        INSERT INTO users (open_id, first_message_at, last_message_at, message_count, active)
        VALUES (?, ?, ?, 1, 1)
        """,
        ("new-open", "2026-05-12T09:00:00", "2026-05-12T09:00:00"),
    )
    writer.commit()

    orphan = UserIdentityRepository.find_oldest_unlinked_user(writer)
    assert orphan is not None
    assert orphan["open_id"] == "old-open"

    UserIdentityRepository.link_orphan_identity(
        writer,
        user_id=orphan["id"],
        bot_user_key="bot-1",
        plusfriend_key="pf-1",
        now=datetime(2026, 5, 12, 10, 0, 0),
    )
    assert UserIdentityRepository.find_by_plusfriend_key(reader, "pf-1") is None

    writer.commit()

    linked = UserIdentityRepository.find_by_plusfriend_key(reader, "pf-1")
    assert linked is not None
    assert linked["open_id"] == "old-open"


def test_chat_identity_methods_preserve_router_transactions(user_identity_db_pair):
    writer, reader = user_identity_db_pair
    now = datetime(2026, 5, 12, 12, 0, 0)
    writer.execute(
        """
        INSERT INTO users (
            bot_user_key, plusfriend_user_key, first_message_at,
            last_message_at, message_count, active
        )
        VALUES (?, ?, ?, ?, 1, 1)
        """,
        ("old-bot", "pf-chat", now, now),
    )
    writer.commit()

    rowcount = UserIdentityRepository.touch_chat_plusfriend_user(
        writer,
        plusfriend_key="pf-chat",
        bot_user_key="new-bot",
        now=datetime(2026, 5, 12, 12, 1, 0),
    )

    assert rowcount == 1
    assert UserIdentityRepository.find_by_plusfriend_key(reader, "pf-chat")["bot_user_key"] == "old-bot"

    writer.commit()

    saved = UserIdentityRepository.find_by_plusfriend_key(reader, "pf-chat")
    assert saved is not None
    assert saved["bot_user_key"] == "new-bot"
    assert saved["message_count"] == 2


def test_open_id_identity_methods_support_webhook_flow(user_identity_db_pair):
    writer, reader = user_identity_db_pair
    now = datetime(2026, 5, 12, 13, 0, 0)

    UserIdentityRepository.insert_open_id_user(writer, open_id="open-1", now=now)
    assert UserIdentityRepository.find_by_open_id(reader, "open-1") is None

    writer.commit()

    saved = UserIdentityRepository.find_by_open_id(reader, "open-1")
    assert saved is not None
    assert saved["open_id"] == "open-1"
    assert saved["active"] == 1

    UserIdentityRepository.set_active_by_open_id(writer, open_id="open-1", active=False)
    writer.commit()

    inactive = UserIdentityRepository.find_by_open_id(reader, "open-1")
    assert inactive is not None
    assert inactive["active"] == 0
