"""사용자 식별 정보 저장소."""
import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional


IDENTITY_COLUMNS = """
    id, bot_user_key, plusfriend_user_key, open_id, message_count, active
"""


class UserIdentityRepository:
    """호출자가 제공한 SQLite 연결로 사용자 식별 SQL을 실행한다."""

    @staticmethod
    def find_by_bot_user_key(
        db: sqlite3.Connection,
        bot_user_key: str,
    ) -> Optional[Dict[str, Any]]:
        cursor = db.cursor()
        cursor.execute(
            f"""
            SELECT {IDENTITY_COLUMNS}
            FROM users
            WHERE bot_user_key = ?
            """,
            (bot_user_key,),
        )
        return UserIdentityRepository._fetch_one_dict(cursor)

    @staticmethod
    def find_by_plusfriend_key(
        db: sqlite3.Connection,
        plusfriend_key: str,
    ) -> Optional[Dict[str, Any]]:
        cursor = db.cursor()
        cursor.execute(
            f"""
            SELECT {IDENTITY_COLUMNS}
            FROM users
            WHERE plusfriend_user_key = ?
            """,
            (plusfriend_key,),
        )
        return UserIdentityRepository._fetch_one_dict(cursor)

    @staticmethod
    def find_by_open_id(
        db: sqlite3.Connection,
        open_id: str,
    ) -> Optional[Dict[str, Any]]:
        cursor = db.cursor()
        cursor.execute(
            f"""
            SELECT {IDENTITY_COLUMNS}
            FROM users
            WHERE open_id = ?
            """,
            (open_id,),
        )
        return UserIdentityRepository._fetch_one_dict(cursor)

    @staticmethod
    def find_oldest_unlinked_user(db: sqlite3.Connection) -> Optional[Dict[str, Any]]:
        cursor = db.cursor()
        cursor.execute(
            """
            SELECT id, open_id
            FROM users
            WHERE bot_user_key IS NULL AND plusfriend_user_key IS NULL
            ORDER BY first_message_at ASC, id ASC
            LIMIT 1
            """
        )
        return UserIdentityRepository._fetch_one_dict(cursor)

    @staticmethod
    def find_first_unlinked_user(db: sqlite3.Connection) -> Optional[Dict[str, Any]]:
        cursor = db.cursor()
        cursor.execute(
            """
            SELECT id, open_id
            FROM users
            WHERE bot_user_key IS NULL AND plusfriend_user_key IS NULL
            LIMIT 1
            """
        )
        return UserIdentityRepository._fetch_one_dict(cursor)

    @staticmethod
    def insert_bot_user(
        db: sqlite3.Connection,
        *,
        bot_user_key: str,
        now: datetime,
    ) -> int:
        cursor = db.cursor()
        cursor.execute(
            """
            INSERT INTO users (bot_user_key, first_message_at, last_message_at, message_count)
            VALUES (?, ?, ?, 1)
            """,
            (bot_user_key, now, now),
        )
        return cursor.rowcount

    @staticmethod
    def insert_open_id_user(
        db: sqlite3.Connection,
        *,
        open_id: str,
        now: datetime,
    ) -> int:
        cursor = db.cursor()
        cursor.execute(
            """
            INSERT INTO users (open_id, first_message_at, last_message_at, message_count, active)
            VALUES (?, ?, ?, 1, 1)
            """,
            (open_id, now, now),
        )
        return cursor.rowcount

    @staticmethod
    def increment_bot_user_message(
        db: sqlite3.Connection,
        *,
        bot_user_key: str,
        now: datetime,
    ) -> int:
        cursor = db.cursor()
        cursor.execute(
            """
            UPDATE users
            SET last_message_at = ?, message_count = message_count + 1
            WHERE bot_user_key = ?
            """,
            (now, bot_user_key),
        )
        return cursor.rowcount

    @staticmethod
    def touch_chat_plusfriend_user(
        db: sqlite3.Connection,
        *,
        plusfriend_key: str,
        bot_user_key: str,
        now: datetime,
    ) -> int:
        cursor = db.cursor()
        cursor.execute(
            """
            UPDATE users
            SET bot_user_key = ?,
                last_message_at = ?,
                message_count = message_count + 1
            WHERE plusfriend_user_key = ?
            """,
            (bot_user_key, now, plusfriend_key),
        )
        return cursor.rowcount

    @staticmethod
    def touch_plusfriend_user(
        db: sqlite3.Connection,
        *,
        plusfriend_key: str,
        now: datetime,
    ) -> int:
        cursor = db.cursor()
        cursor.execute(
            """
            UPDATE users
            SET last_message_at = ?, message_count = message_count + 1, active = 1
            WHERE plusfriend_user_key = ?
            """,
            (now, plusfriend_key),
        )
        return cursor.rowcount

    @staticmethod
    def set_active_by_plusfriend_key(
        db: sqlite3.Connection,
        *,
        plusfriend_key: str,
        active: bool,
    ) -> int:
        cursor = db.cursor()
        cursor.execute(
            """
            UPDATE users
            SET active = ?
            WHERE plusfriend_user_key = ?
            """,
            (active, plusfriend_key),
        )
        return cursor.rowcount

    @staticmethod
    def set_active_by_open_id(
        db: sqlite3.Connection,
        *,
        open_id: str,
        active: bool,
    ) -> int:
        cursor = db.cursor()
        cursor.execute(
            """
            UPDATE users
            SET active = ?
            WHERE open_id = ?
            """,
            (active, open_id),
        )
        return cursor.rowcount

    @staticmethod
    def set_bot_user_key_for_plusfriend(
        db: sqlite3.Connection,
        *,
        plusfriend_key: str,
        bot_user_key: str,
    ) -> int:
        cursor = db.cursor()
        cursor.execute(
            """
            UPDATE users
            SET bot_user_key = ?
            WHERE plusfriend_user_key = ?
            """,
            (bot_user_key, plusfriend_key),
        )
        return cursor.rowcount

    @staticmethod
    def link_plusfriend_to_bot(
        db: sqlite3.Connection,
        *,
        bot_user_key: str,
        plusfriend_key: str,
        now: datetime,
    ) -> int:
        cursor = db.cursor()
        cursor.execute(
            """
            UPDATE users
            SET plusfriend_user_key = ?, last_message_at = ?, message_count = message_count + 1, active = 1
            WHERE bot_user_key = ?
            """,
            (plusfriend_key, now, bot_user_key),
        )
        return cursor.rowcount

    @staticmethod
    def link_unlinked_user_from_chat(
        db: sqlite3.Connection,
        *,
        user_id: int,
        bot_user_key: str,
        plusfriend_key: str,
        now: datetime,
    ) -> int:
        cursor = db.cursor()
        cursor.execute(
            """
            UPDATE users
            SET bot_user_key = ?,
                plusfriend_user_key = ?,
                last_message_at = ?
            WHERE id = ?
            """,
            (bot_user_key, plusfriend_key, now, user_id),
        )
        return cursor.rowcount

    @staticmethod
    def link_orphan_identity(
        db: sqlite3.Connection,
        *,
        user_id: int,
        bot_user_key: str,
        plusfriend_key: str,
        now: datetime,
    ) -> int:
        cursor = db.cursor()
        cursor.execute(
            """
            UPDATE users
            SET bot_user_key = ?, plusfriend_user_key = ?, last_message_at = ?, active = 1
            WHERE id = ?
            """,
            (bot_user_key, plusfriend_key, now, user_id),
        )
        return cursor.rowcount

    @staticmethod
    def insert_kakao_identity(
        db: sqlite3.Connection,
        *,
        bot_user_key: str,
        plusfriend_key: str,
        now: datetime,
    ) -> int:
        cursor = db.cursor()
        cursor.execute(
            """
            INSERT INTO users (bot_user_key, plusfriend_user_key, first_message_at, last_message_at, message_count, active)
            VALUES (?, ?, ?, ?, 1, 1)
            """,
            (bot_user_key, plusfriend_key, now, now),
        )
        return cursor.rowcount

    @staticmethod
    def _fetch_one_dict(cursor: sqlite3.Cursor) -> Optional[Dict[str, Any]]:
        row = cursor.fetchone()
        if not row:
            return None

        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))
