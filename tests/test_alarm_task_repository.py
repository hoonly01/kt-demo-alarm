"""Alarm task repository integration tests."""
import json
import os
import sqlite3
import tempfile
from typing import Iterator

import pytest

from app.database.models import ALARM_TASKS_TABLE_SCHEMA, EVENTS_TABLE_SCHEMA
from app.repositories.alarm_task_repository import AlarmTaskRepository


@pytest.fixture
def alarm_task_db_pair() -> Iterator[tuple[sqlite3.Connection, sqlite3.Connection]]:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    writer = sqlite3.connect(db_path)
    reader = sqlite3.connect(db_path)
    writer.execute("PRAGMA foreign_keys = ON")
    reader.execute("PRAGMA foreign_keys = ON")
    writer.execute(EVENTS_TABLE_SCHEMA)
    writer.execute(ALARM_TASKS_TABLE_SCHEMA)
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


def _task_count(db: sqlite3.Connection) -> int:
    cursor = db.execute("SELECT COUNT(*) FROM alarm_tasks")
    return int(cursor.fetchone()[0])


def test_create_task_uses_caller_transaction(alarm_task_db_pair):
    writer, reader = alarm_task_db_pair
    request_data = {"user_id": "test-user", "nested": {"route": "A"}}
    event_id = writer.execute(
        """
        INSERT INTO events (title, location_name, latitude, longitude, start_date)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("test-event", "test-location", 37.5, 127.0, "2026-05-12T09:00:00"),
    ).lastrowid
    writer.commit()

    rowcount = AlarmTaskRepository.create_task(
        writer,
        task_id="task-create",
        alarm_type="individual",
        total_recipients=2,
        event_id=event_id,
        request_data=json.dumps(request_data),
        created_at="2026-05-12T09:00:00",
    )

    assert rowcount == 1
    assert _task_count(writer) == 1
    assert _task_count(reader) == 0

    writer.commit()

    saved = AlarmTaskRepository.get_status(reader, "task-create")
    assert saved is not None
    assert saved["status"] == "pending"
    assert saved["request_data"] == json.dumps(request_data)


def test_update_status_returns_rowcount_without_committing(alarm_task_db_pair):
    writer, reader = alarm_task_db_pair
    AlarmTaskRepository.create_task(
        writer,
        task_id="task-update",
        alarm_type="bulk",
        total_recipients=5,
        event_id=None,
        request_data=None,
        created_at="2026-05-12T09:00:00",
    )
    writer.commit()

    rowcount = AlarmTaskRepository.update_status(
        writer,
        task_id="task-update",
        status="completed",
        updated_at="2026-05-12T09:01:00",
        successful_sends=4,
        failed_sends=1,
        error_messages=json.dumps(["timeout"]),
        total_recipients=5,
        completed_at="2026-05-12T09:02:00",
    )

    assert rowcount == 1
    before_commit = AlarmTaskRepository.get_status(reader, "task-update")
    assert before_commit is not None
    assert before_commit["status"] == "pending"

    writer.commit()

    after_commit = AlarmTaskRepository.get_status(reader, "task-update")
    assert after_commit is not None
    assert after_commit["status"] == "completed"
    assert after_commit["successful_sends"] == 4
    assert after_commit["failed_sends"] == 1
    assert after_commit["error_messages"] == json.dumps(["timeout"])
    assert after_commit["completed_at"] == "2026-05-12T09:02:00"

    assert (
        AlarmTaskRepository.update_status(
            writer,
            task_id="missing-task",
            status="completed",
            updated_at="2026-05-12T09:03:00",
        )
        == 0
    )


def test_list_recent_and_delete_older_than(alarm_task_db_pair):
    writer, reader = alarm_task_db_pair
    for task_id, created_at in [
        ("old-task", "2026-04-01T00:00:00"),
        ("middle-task", "2026-05-01T00:00:00"),
        ("new-task", "2026-05-12T00:00:00"),
    ]:
        AlarmTaskRepository.create_task(
            writer,
            task_id=task_id,
            alarm_type="bulk",
            total_recipients=1,
            event_id=None,
            request_data=None,
            created_at=created_at,
        )
    writer.commit()

    recent = AlarmTaskRepository.list_recent(reader, limit=2)
    assert [task["task_id"] for task in recent] == ["new-task", "middle-task"]

    deleted_count = AlarmTaskRepository.delete_older_than(
        writer,
        cutoff_date="2026-05-01T00:00:00",
    )

    assert deleted_count == 1
    assert _task_count(reader) == 3

    writer.commit()

    remaining = AlarmTaskRepository.list_recent(reader, limit=10)
    assert [task["task_id"] for task in remaining] == ["new-task", "middle-task"]
