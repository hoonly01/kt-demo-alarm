import sqlite3

from app.services.user_service import UserService


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
        "SELECT bot_user_key, plusfriend_user_key, message_count, active FROM users WHERE bot_user_key = ?",
        ("bot_user_key_123",),
    )
    row = cursor.fetchone()

    assert row == ("bot_user_key_123", "pf_123", 2, 1)

    cursor.execute("SELECT COUNT(*) FROM users")
    assert cursor.fetchone()[0] == 1
    conn.close()


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


def test_sync_kakao_user_links_oldest_orphan_user(clean_test_db):
    conn = sqlite3.connect(clean_test_db)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO users (open_id, first_message_at, last_message_at, message_count, active)
        VALUES (?, ?, ?, 1, 1)
        """,
        ("old-open", "2026-05-12T08:00:00", "2026-05-12T08:00:00"),
    )
    cursor.execute(
        """
        INSERT INTO users (open_id, first_message_at, last_message_at, message_count, active)
        VALUES (?, ?, ?, 1, 1)
        """,
        ("new-open", "2026-05-12T09:00:00", "2026-05-12T09:00:00"),
    )
    conn.commit()

    UserService.sync_kakao_user("bot_user_key_123", "pf_123", conn)

    cursor.execute(
        """
        SELECT open_id, bot_user_key, plusfriend_user_key, active
        FROM users
        ORDER BY first_message_at ASC, id ASC
        """
    )
    rows = cursor.fetchall()

    assert rows[0] == ("old-open", "bot_user_key_123", "pf_123", 1)
    assert rows[1] == ("new-open", None, None, 1)
    conn.close()
