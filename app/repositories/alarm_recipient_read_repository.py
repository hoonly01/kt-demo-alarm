"""알림 수신자 읽기 저장소."""
import sqlite3
from typing import Any, Dict, List, Optional


RecipientGroups = Dict[str, List[str]]


class AlarmRecipientReadRepository:
    """알림 발송 대상 사용자 읽기 SQL을 담당한다."""

    @staticmethod
    def list_active_recipients(db: sqlite3.Connection) -> RecipientGroups:
        cursor = db.cursor()
        cursor.execute(
            """
            SELECT plusfriend_user_key
            FROM users
            WHERE active = 1
              AND is_alarm_on = 1
              AND plusfriend_user_key IS NOT NULL
            """
        )
        plusfriend_users = AlarmRecipientReadRepository._dedupe(
            [row["plusfriend_user_key"] for row in cursor.fetchall()]
        )

        cursor.execute(
            """
            SELECT bot_user_key
            FROM users
            WHERE active = 1
              AND is_alarm_on = 1
              AND plusfriend_user_key IS NULL
              AND bot_user_key IS NOT NULL
            """
        )
        bot_users = AlarmRecipientReadRepository._dedupe(
            [row["bot_user_key"] for row in cursor.fetchall()]
        )

        return {
            "plusfriend_user_keys": plusfriend_users,
            "bot_user_keys": bot_users,
        }

    @staticmethod
    def list_filtered_recipients(
        db: sqlite3.Connection,
        *,
        filter_location: Optional[str],
        filter_marked_bus: Optional[str],
        filter_has_route: Optional[bool],
    ) -> RecipientGroups:
        query = """
            SELECT plusfriend_user_key, bot_user_key
            FROM users
            WHERE active = 1 AND is_alarm_on = 1
              AND (plusfriend_user_key IS NOT NULL OR bot_user_key IS NOT NULL)
        """
        params: List[Any] = []

        if filter_location:
            query += " AND location LIKE ?"
            params.append(f"%{filter_location}%")

        if filter_marked_bus:
            query += " AND marked_bus = ?"
            params.append(filter_marked_bus)

        if filter_has_route is not None:
            if filter_has_route:
                query += " AND departure_x IS NOT NULL AND arrival_x IS NOT NULL"
            else:
                query += " AND (departure_x IS NULL OR arrival_x IS NULL)"

        cursor = db.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()

        plusfriend_users_raw = [row["plusfriend_user_key"] for row in rows if row["plusfriend_user_key"] is not None]
        bot_users_raw = [
            row["bot_user_key"]
            for row in rows
            if row["plusfriend_user_key"] is None and row["bot_user_key"] is not None
        ]

        return {
            "plusfriend_user_keys": AlarmRecipientReadRepository._dedupe(plusfriend_users_raw),
            "bot_user_keys": AlarmRecipientReadRepository._dedupe(bot_users_raw),
        }

    @staticmethod
    def _dedupe(values: List[str]) -> List[str]:
        return list(dict.fromkeys(values))
