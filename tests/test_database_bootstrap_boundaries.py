"""startup/lifespan bootstrap-only 경계 테스트."""

import logging
import sqlite3

from fastapi.testclient import TestClient

from main import app


def _table_names(db_path: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


def test_startup_runs_bootstrap_but_not_probe(tmp_path, settings_overrides, caplog):
    db_path = tmp_path / "lifespan-bootstrap.db"
    settings_overrides(DATABASE_PATH=str(db_path))
    caplog.set_level(logging.INFO)
    caplog.clear()

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert {"users", "events", "alarm_tasks"}.issubset(_table_names(str(db_path)))

    bootstrap_logs = [
        record.getMessage()
        for record in caplog.records
        if record.name == "app.database.bootstrap"
    ]
    probe_logs = [
        record.getMessage()
        for record in caplog.records
        if record.name == "app.database.compatibility_probe"
    ]

    assert any(
        "mode=bootstrap" in message and "path_source=settings" in message
        for message in bootstrap_logs
    )
    assert probe_logs == []
