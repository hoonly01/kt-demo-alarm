import sqlite3
from datetime import datetime, timedelta

from app.models.user import UserPreferences
from app.services.user_service import UserService


def assert_utc_storage(value: str) -> None:
    parsed = datetime.fromisoformat(value)
    assert "T" in value
    assert value.endswith("+00:00")
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


def test_save_or_update_user_writes_utc_aware_storage(clean_test_db):
    conn = sqlite3.connect(clean_test_db)

    UserService.save_or_update_user("bot-new", conn)
    UserService.save_or_update_user("bot-new", conn)

    row = conn.execute(
        "SELECT first_message_at, last_message_at, message_count FROM users WHERE bot_user_key = ?",
        ("bot-new",),
    ).fetchone()
    conn.close()

    assert row[2] == 2
    assert_utc_storage(row[0])
    assert_utc_storage(row[1])


def test_sync_kakao_user_links_existing_bot_user(clean_test_db):
    conn = sqlite3.connect(clean_test_db)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO users (bot_user_key, first_message_at, last_message_at, message_count, active)
        VALUES (?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, 1)
        """,
        ("bot_user_key_123",),
    )
    conn.commit()

    UserService.sync_kakao_user("bot_user_key_123", "pf_123", conn)

    cursor.execute(
        "SELECT bot_user_key, plusfriend_user_key, message_count, active, last_message_at FROM users WHERE bot_user_key = ?",
        ("bot_user_key_123",),
    )
    row = cursor.fetchone()

    assert row[:4] == ("bot_user_key_123", "pf_123", 2, 1)
    assert_utc_storage(row[4])

    cursor.execute("SELECT COUNT(*) FROM users")
    assert cursor.fetchone()[0] == 1
    conn.close()


def test_delete_user_route_writes_utc_route_timestamp(clean_test_db):
    conn = sqlite3.connect(clean_test_db)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO users (
            bot_user_key, plusfriend_user_key, first_message_at, last_message_at,
            departure_name, departure_x, departure_y, arrival_name, arrival_x, arrival_y,
            route_updated_at
        )
        VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        ("bot-route", "pf-route", "영통역", 127.071, 37.251, "광화문역", 126.9769, 37.5709),
    )
    conn.commit()

    result = UserService.delete_user_route("pf-route", conn)
    row = conn.execute(
        "SELECT departure_name, arrival_name, route_updated_at FROM users WHERE plusfriend_user_key = ?",
        ("pf-route",),
    ).fetchone()
    conn.close()

    assert result == {"success": True}
    assert row[0] is None
    assert row[1] is None
    assert_utc_storage(row[2])


def test_update_user_preferences_accepts_marked_bus_and_language(clean_test_db):
    conn = sqlite3.connect(clean_test_db)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO users (bot_user_key, first_message_at, last_message_at, message_count, active)
        VALUES (?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, 1)
        """,
        ("bot-preferences",),
    )
    conn.commit()

    result = UserService.update_user_preferences(
        "bot-preferences",
        UserPreferences(marked_bus="470", language="ko"),
        conn,
    )
    row = conn.execute(
        "SELECT marked_bus, language FROM users WHERE bot_user_key = ?",
        ("bot-preferences",),
    ).fetchone()
    conn.close()

    assert result == {"success": True}
    assert row == ("470", "ko")


def test_sync_kakao_user_updates_existing_plusfriend_user(clean_test_db):
    conn = sqlite3.connect(clean_test_db)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO users (bot_user_key, plusfriend_user_key, first_message_at, last_message_at, message_count, active)
        VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, 0)
        """,
        ("bot_user_key_123", "pf_123"),
    )
    conn.commit()

    UserService.sync_kakao_user("bot_user_key_123", "pf_123", conn)

    cursor.execute(
        "SELECT bot_user_key, plusfriend_user_key, message_count, active FROM users WHERE plusfriend_user_key = ?",
        ("pf_123",),
    )
    row = cursor.fetchone()

    assert row == ("bot_user_key_123", "pf_123", 2, 1)
    conn.close()


def test_sync_kakao_user_does_not_merge_conflicting_rows(clean_test_db):
    conn = sqlite3.connect(clean_test_db)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO users (bot_user_key, first_message_at, last_message_at, message_count, active)
        VALUES (?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, 1)
        """,
        ("bot_a",),
    )
    cursor.execute(
        """
        INSERT INTO users (bot_user_key, plusfriend_user_key, first_message_at, last_message_at, message_count, active)
        VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, 0)
        """,
        ("bot_b", "pf_x"),
    )
    conn.commit()

    UserService.sync_kakao_user("bot_a", "pf_x", conn)

    cursor.execute(
        "SELECT bot_user_key, plusfriend_user_key, message_count, active FROM users WHERE bot_user_key = ?",
        ("bot_a",),
    )
    bot_a_row = cursor.fetchone()
    cursor.execute(
        "SELECT bot_user_key, plusfriend_user_key, message_count, active FROM users WHERE plusfriend_user_key = ?",
        ("pf_x",),
    )
    pf_x_row = cursor.fetchone()

    assert bot_a_row == ("bot_a", None, 1, 1)
    assert pf_x_row == ("bot_b", "pf_x", 2, 1)

    cursor.execute("SELECT COUNT(*) FROM users")
    assert cursor.fetchone()[0] == 2
    conn.close()
