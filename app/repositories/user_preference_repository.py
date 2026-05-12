"""사용자 개인화 설정 저장소."""
import sqlite3
from typing import Any, Optional


class UserPreferenceRepository:
    """bot_user_key 기준 사용자 선호 설정 SQL을 실행한다."""

    @staticmethod
    def exists_by_bot_user_key(db: sqlite3.Connection, user_id: str) -> bool:
        cursor = db.cursor()
        cursor.execute("SELECT id FROM users WHERE bot_user_key = ?", (user_id,))
        return cursor.fetchone() is not None

    @staticmethod
    def update_preferences(
        db: sqlite3.Connection,
        *,
        user_id: str,
        marked_bus: Optional[str],
        language: Optional[str],
    ) -> int:
        update_fields = []
        update_values: list[Any] = []

        if marked_bus:
            update_fields.append("marked_bus = ?")
            update_values.append(marked_bus)

        if language:
            update_fields.append("language = ?")
            update_values.append(language)

        if not update_fields:
            return 0

        update_values.append(user_id)
        cursor = db.cursor()
        cursor.execute(
            f"UPDATE users SET {', '.join(update_fields)} WHERE bot_user_key = ?",
            update_values,
        )
        return cursor.rowcount
