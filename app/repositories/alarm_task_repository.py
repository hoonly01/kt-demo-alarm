"""alarm_tasks 테이블 저장소."""
import sqlite3
from typing import Any, Dict, List, Optional


class AlarmTaskRepository:
    """호출자가 제공한 SQLite 연결로 alarm_tasks SQL을 실행한다."""

    @staticmethod
    def create_task(
        db: sqlite3.Connection,
        *,
        task_id: str,
        alarm_type: str,
        total_recipients: int,
        event_id: Optional[int],
        request_data: Optional[str],
        created_at: str,
    ) -> int:
        cursor = db.cursor()
        cursor.execute(
            """
            INSERT INTO alarm_tasks
            (task_id, alarm_type, status, total_recipients, event_id, request_data, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                alarm_type,
                "pending",
                total_recipients,
                event_id,
                request_data,
                created_at,
            ),
        )
        return cursor.rowcount

    @staticmethod
    def update_status(
        db: sqlite3.Connection,
        *,
        task_id: str,
        status: str,
        updated_at: str,
        successful_sends: Optional[int] = None,
        failed_sends: Optional[int] = None,
        error_messages: Optional[str] = None,
        total_recipients: Optional[int] = None,
        completed_at: Optional[str] = None,
    ) -> int:
        update_fields = ["status = ?", "updated_at = ?"]
        update_values: List[Any] = [status, updated_at]

        if successful_sends is not None:
            update_fields.append("successful_sends = ?")
            update_values.append(successful_sends)

        if failed_sends is not None:
            update_fields.append("failed_sends = ?")
            update_values.append(failed_sends)

        if error_messages is not None:
            update_fields.append("error_messages = ?")
            update_values.append(error_messages)

        if total_recipients is not None:
            update_fields.append("total_recipients = ?")
            update_values.append(total_recipients)

        if completed_at is not None:
            update_fields.append("completed_at = ?")
            update_values.append(completed_at)

        update_values.append(task_id)
        cursor = db.cursor()
        cursor.execute(
            f"UPDATE alarm_tasks SET {', '.join(update_fields)} WHERE task_id = ?",
            update_values,
        )
        return cursor.rowcount

    @staticmethod
    def get_status(
        db: sqlite3.Connection,
        task_id: str,
    ) -> Optional[Dict[str, Any]]:
        cursor = db.cursor()
        cursor.execute(
            """
            SELECT
                task_id, alarm_type, status, total_recipients,
                successful_sends, failed_sends, event_id,
                request_data, error_messages,
                created_at, updated_at, completed_at
            FROM alarm_tasks
            WHERE task_id = ?
            """,
            (task_id,),
        )

        row = cursor.fetchone()
        if not row:
            return None

        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))

    @staticmethod
    def list_recent(
        db: sqlite3.Connection,
        limit: int,
    ) -> List[Dict[str, Any]]:
        cursor = db.cursor()
        cursor.execute(
            """
            SELECT
                task_id, alarm_type, status, total_recipients,
                successful_sends, failed_sends, event_id,
                created_at, updated_at, completed_at
            FROM alarm_tasks
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )

        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in rows]

    @staticmethod
    def delete_older_than(
        db: sqlite3.Connection,
        *,
        cutoff_date: str,
    ) -> int:
        cursor = db.cursor()
        cursor.execute(
            """
            DELETE FROM alarm_tasks
            WHERE created_at < ?
            """,
            (cutoff_date,),
        )
        return cursor.rowcount
