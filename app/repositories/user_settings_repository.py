"""사용자 설정 저장소."""
import sqlite3
from datetime import datetime
from typing import Optional


class UserSettingsRepository:
    """plusfriend 우선, bot fallback 규칙을 유지하는 사용자 설정 SQL."""

    @staticmethod
    def update_alarm_setting(
        db: sqlite3.Connection,
        *,
        user_id: str,
        is_alarm_on: bool,
    ) -> int:
        rowcount = UserSettingsRepository._update_single_value(
            db,
            column="is_alarm_on",
            value=is_alarm_on,
            identifier_column="plusfriend_user_key",
            user_id=user_id,
        )
        if rowcount == 0:
            rowcount = UserSettingsRepository._update_single_value(
                db,
                column="is_alarm_on",
                value=is_alarm_on,
                identifier_column="bot_user_key",
                user_id=user_id,
            )
        return rowcount

    @staticmethod
    def update_favorite_zone(
        db: sqlite3.Connection,
        *,
        user_id: str,
        zone: Optional[int],
    ) -> int:
        rowcount = UserSettingsRepository._update_single_value(
            db,
            column="favorite_zone",
            value=zone,
            identifier_column="plusfriend_user_key",
            user_id=user_id,
        )
        if rowcount == 0:
            rowcount = UserSettingsRepository._update_single_value(
                db,
                column="favorite_zone",
                value=zone,
                identifier_column="bot_user_key",
                user_id=user_id,
            )
        return rowcount

    @staticmethod
    def update_marked_bus(
        db: sqlite3.Connection,
        *,
        user_id: str,
        marked_bus: str,
        now: datetime,
    ) -> int:
        rowcount = UserSettingsRepository._update_marked_bus_by_identifier(
            db,
            identifier_column="plusfriend_user_key",
            user_id=user_id,
            marked_bus=marked_bus,
            now=now,
        )
        if rowcount == 0:
            rowcount = UserSettingsRepository._update_marked_bus_by_identifier(
                db,
                identifier_column="bot_user_key",
                user_id=user_id,
                marked_bus=marked_bus,
                now=now,
            )
        return rowcount

    @staticmethod
    def _update_single_value(
        db: sqlite3.Connection,
        *,
        column: str,
        value: object,
        identifier_column: str,
        user_id: str,
    ) -> int:
        cursor = db.cursor()
        cursor.execute(
            f"""
            UPDATE users
            SET {column} = ?
            WHERE {identifier_column} = ?
            """,
            (value, user_id),
        )
        return cursor.rowcount

    @staticmethod
    def _update_marked_bus_by_identifier(
        db: sqlite3.Connection,
        *,
        identifier_column: str,
        user_id: str,
        marked_bus: str,
        now: datetime,
    ) -> int:
        cursor = db.cursor()
        cursor.execute(
            f"""
            UPDATE users
            SET marked_bus = ?,
                last_message_at = ?
            WHERE {identifier_column} = ?
            """,
            (marked_bus, now, user_id),
        )
        return cursor.rowcount
