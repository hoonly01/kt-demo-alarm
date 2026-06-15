"""SQLite compatibility probe 계약 테스트."""

import json
import logging
import sqlite3
import subprocess
from pathlib import Path

import pytest
from app.database.compatibility_probe import ROW_ACCESS_CONTRACT
from app.database.compatibility_probe import SQLITE_DIALECT_ASSUMPTIONS
from app.database.compatibility_probe import STARTUP_CONTRACT
from app.database.compatibility_probe import _build_contract_snapshot
from app.database.compatibility_probe import generate_compatibility_report
from app.database.compatibility_probe import normalize_schema_snapshot
from app.database.compatibility_probe import open_readonly_probe_connection
from app.database.compatibility_probe import validate_report
from app.database.connection import init_db


def _find_required_columns(report: dict, table_name: str) -> dict:
    return next(
        item
        for item in report["required_columns"]
        if item["table"] == table_name
    )


def _find_required_column_definition(table_report: dict, column_name: str) -> dict:
    return next(
        item
        for item in table_report["column_definitions"]
        if item["name"] == column_name
    )


def _find_required_index(report: dict, index_name: str) -> dict:
    return next(
        item
        for item in report["required_indexes"]
        if item["name"] == index_name
    )


def _assert_evidence_reference_exists(reference: str) -> None:
    path_text, line_range = reference.split(":", 1)
    path = Path(__file__).resolve().parents[1] / path_text
    assert path.exists(), f"Missing evidence path: {path_text}"
    lines = path.read_text().splitlines()
    if "-" in line_range:
        start_text, end_text = line_range.split("-", 1)
        start_line = int(start_text)
        end_line = int(end_text)
    else:
        start_line = end_line = int(line_range)
    assert 1 <= start_line <= len(lines), f"Invalid start line for {reference}"
    assert start_line <= end_line <= len(lines), f"Invalid end line for {reference}"


def _database_snapshot(db_path) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        schema_rows = conn.execute(
            """
            SELECT type, name, sql
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
            ORDER BY type, name
            """
        ).fetchall()
        table_rows = {}
        for table_name in ("users", "events", "alarm_tasks"):
            rows = conn.execute(
                f"SELECT * FROM {table_name} ORDER BY rowid"
            ).fetchall()
            table_rows[table_name] = [dict(row) for row in rows]
        return {
            "schema": [dict(row) for row in schema_rows],
            "rows": table_rows,
        }
    finally:
        conn.close()


def test_probe_reports_current_sqlite_dialect_assumptions(tmp_path, settings_overrides):
    db_path = tmp_path / "compatibility-probe.db"
    settings_overrides(DATABASE_PATH=str(db_path))
    init_db()

    report = generate_compatibility_report(database_path=str(db_path))

    assert {table["name"] for table in report["required_tables"]} == {
        "users",
        "events",
        "alarm_tasks",
    }
    assert all(table["exists"] for table in report["required_tables"])

    assumption_ids = {
        assumption["id"]
        for assumption in report["sqlite_dialect_assumptions"]
    }
    assert {
        "sqlite_row_factory",
        "pragma_table_info",
        "rowid_fallback",
        "partial_unique_index",
        "datetime_now_kst_offset",
        "date_start_date",
    }.issubset(assumption_ids)
    assert report["report_version"] == 2
    assert report["engine_specific_delta"]["current_engine"] == "sqlite"
    assert report["engine_specific_delta"]["current_driver"] == "sqlite3"
    assert report["engine_specific_delta"]["active_assumption_ids"] == [
        assumption["id"]
        for assumption in report["sqlite_dialect_assumptions"]
    ]
    portability_hotspots = {
        hotspot["assumption_id"]: hotspot
        for hotspot in report["engine_specific_delta"]["portability_hotspots"]
    }
    assert portability_hotspots["sqlite_row_factory"]["category"] == "row_access"
    assert portability_hotspots["pragma_table_info"]["category"] == "schema_introspection"
    assert portability_hotspots["rowid_fallback"]["category"] == "legacy_fallback"
    assert report["detected_assumptions_count"] == len(report["sqlite_dialect_assumptions"])
    assert report["failure_reasons"] == []

    events_columns = _find_required_columns(report, "events")
    assert "source_record_hash" in events_columns["columns"]
    assert "source_payload_hash" in events_columns["columns"]
    assert events_columns["missing_columns"] == []
    assert events_columns["mismatched_columns"] == []

    source_column = _find_required_column_definition(events_columns, "source")
    assert source_column["definition_matches"] is True
    assert source_column["expected"] == source_column["actual"]
    assert source_column["expected"]["notnull"] is True

    probe_index = _find_required_index(report, "idx_events_source_record_hash")
    assert probe_index["table"] == "events"
    assert probe_index["columns"] == ["source_record_hash"]
    assert probe_index["unique"] is True
    assert probe_index["partial"] is True
    assert probe_index["where"] == "source_record_hash IS NOT NULL"
    assert probe_index["exists"] is True

    assert report["row_access_contract"]["row_factory"] == "sqlite3.Row"
    assert report["row_access_contract"]["access_pattern"] == "row['column_name']"
    assert report["startup_contract"]["bootstrap_entrypoint"] == "app.database.connection.init_db"
    assert report["startup_contract"]["probe_runs_on_startup"] is False


def test_probe_readonly_connection_rejects_writes_and_preserves_database_state(
    tmp_path,
    settings_overrides,
):
    db_path = tmp_path / "compatibility-probe-readonly.db"
    settings_overrides(DATABASE_PATH=str(db_path))
    init_db()

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO users (bot_user_key, active)
            VALUES ('readonly-user', 1)
            """
        )
        conn.commit()
    finally:
        conn.close()

    before_snapshot = _database_snapshot(db_path)
    report = generate_compatibility_report(database_path=str(db_path))
    assert report["database_path"] == str(db_path.resolve())

    with open_readonly_probe_connection(str(db_path)) as probe_conn:
        query_only = probe_conn.execute("PRAGMA query_only").fetchone()[0]
        assert query_only == 1

        try:
            probe_conn.execute(
                """
                INSERT INTO users (bot_user_key, active)
                VALUES ('should-fail', 1)
                """
            )
        except sqlite3.OperationalError as exc:
            assert "readonly" in str(exc).lower()
        else:
            raise AssertionError("read-only probe connection unexpectedly allowed a write")

        assert probe_conn.total_changes == 0

    after_snapshot = _database_snapshot(db_path)
    assert after_snapshot == before_snapshot


def test_probe_report_returns_structured_failure_for_missing_database_path(tmp_path):
    db_path = tmp_path / "compatibility-probe-missing.db"
    assert not db_path.exists()

    report = generate_compatibility_report(database_path=str(db_path))

    assert report["database_path"] == str(db_path.resolve())
    assert all(not table["exists"] for table in report["required_tables"])
    assert f"missing database file: {db_path.resolve()}" in report["failure_reasons"]
    assert "missing table: users" in report["failure_reasons"]
    assert "missing table: events" in report["failure_reasons"]
    assert "missing index: sqlite_autoindex_alarm_tasks_1" in report["failure_reasons"]
    assert "missing index: sqlite_autoindex_users_1" in report["failure_reasons"]
    assert "missing index: idx_events_source_record_hash" in report["failure_reasons"]
    assert not db_path.exists()


def test_probe_report_returns_structured_failure_for_invalid_database_file(tmp_path):
    db_path = tmp_path / "compatibility-probe-invalid.db"
    db_path.write_text("not sqlite", encoding="utf-8")

    report = generate_compatibility_report(database_path=str(db_path))

    assert report["database_path"] == str(db_path.resolve())
    assert all(not table["exists"] for table in report["required_tables"])
    assert (
        f"unreadable database file: {db_path.resolve()} (file is not a database)"
        in report["failure_reasons"]
    )
    assert "missing table: users" in report["failure_reasons"]
    assert "missing index: idx_events_source_record_hash" in report["failure_reasons"]


def test_probe_contract_snapshot_matches_bootstrap_contract():
    snapshot = _build_contract_snapshot()

    assert snapshot["table_names"] == ["alarm_tasks", "events", "users"]
    assert "image_path" in snapshot["columns_by_table"]["events"]
    event_source_column = next(
        column
        for column in snapshot["column_definitions_by_table"]["events"]
        if column["name"] == "source"
    )
    assert event_source_column["type"] == "TEXT"
    assert event_source_column["notnull"] is True
    assert event_source_column["default"] == "'SMPA'"

    index_names = {index["name"] for index in snapshot["indexes"]}
    assert {
        "idx_events_source_record_hash",
        "sqlite_autoindex_alarm_tasks_1",
        "sqlite_autoindex_users_1",
    }.issubset(index_names)

    parsed_index = next(
        index
        for index in snapshot["indexes"]
        if index["name"] == "idx_events_source_record_hash"
    )
    assert parsed_index["columns"] == ["source_record_hash"]
    assert parsed_index["unique"] is True
    assert parsed_index["partial"] is True
    assert parsed_index["where"] == "source_record_hash IS NOT NULL"


def test_schema_snapshot_normalizer_sorts_tables_columns_and_indexes():
    normalized = normalize_schema_snapshot(
        {
            "table_names": {"users", "events"},
            "columns_by_table": {
                "users": ["plusfriend_user_key", "bot_user_key"],
                "events": ["source", "title"],
            },
            "column_definitions_by_table": {
                "users": [
                    {
                        "name": "plusfriend_user_key",
                        "type": "TEXT",
                        "notnull": False,
                        "default": None,
                        "pk": 0,
                    },
                    {
                        "name": "bot_user_key",
                        "type": "TEXT",
                        "notnull": True,
                        "default": None,
                        "pk": 0,
                    },
                ],
            },
            "indexes": [
                {"table": "users", "name": "idx_users_z", "columns": [], "unique": False, "partial": False, "where": None},
                {"table": "users", "name": "idx_users_a", "columns": [], "unique": False, "partial": False, "where": None},
            ],
        }
    )

    assert normalized["table_names"] == ["events", "users"]
    assert normalized["columns_by_table"]["users"] == [
        "bot_user_key",
        "plusfriend_user_key",
    ]
    assert [
        column["name"]
        for column in normalized["column_definitions_by_table"]["users"]
    ] == [
        "bot_user_key",
        "plusfriend_user_key",
    ]
    assert [index["name"] for index in normalized["indexes"]] == [
        "idx_users_a",
        "idx_users_z",
    ]


def test_probe_report_validator_rejects_missing_required_fields(tmp_path, settings_overrides):
    db_path = tmp_path / "compatibility-probe-validate.db"
    settings_overrides(DATABASE_PATH=str(db_path))
    init_db()

    report = generate_compatibility_report(database_path=str(db_path))
    report.pop("report_version")

    with pytest.raises(ValueError, match="report_version"):
        validate_report(report)


def test_probe_report_validator_rejects_engine_specific_delta_drift(
    tmp_path,
    settings_overrides,
):
    db_path = tmp_path / "compatibility-probe-delta-validate.db"
    settings_overrides(DATABASE_PATH=str(db_path))
    init_db()

    report = generate_compatibility_report(database_path=str(db_path))
    report["engine_specific_delta"]["active_assumption_ids"] = ["sqlite_row_factory"]

    with pytest.raises(ValueError, match="active_assumption_ids"):
        validate_report(report)


def test_probe_report_flags_index_definition_drift(tmp_path, settings_overrides):
    db_path = tmp_path / "compatibility-probe-index-drift.db"
    settings_overrides(DATABASE_PATH=str(db_path))
    init_db()

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP INDEX idx_events_source_record_hash")
        conn.execute(
            """
            CREATE UNIQUE INDEX idx_events_source_record_hash
            ON events(source_payload_hash)
            """
        )
        conn.commit()
    finally:
        conn.close()

    report = generate_compatibility_report(database_path=str(db_path))

    probe_index = _find_required_index(report, "idx_events_source_record_hash")
    assert probe_index["exists"] is True
    assert probe_index["definition_matches"] is False
    assert probe_index["actual"]["columns"] == ["source_payload_hash"]
    assert "mismatched index definition: idx_events_source_record_hash" in report["failure_reasons"]


def test_probe_report_flags_column_definition_drift(tmp_path, settings_overrides):
    db_path = tmp_path / "compatibility-probe-column-drift.db"
    settings_overrides(DATABASE_PATH=str(db_path))
    init_db()

    conn = sqlite3.connect(db_path)
    try:
        users_create_sql = conn.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name = 'users'
            """
        ).fetchone()[0]
        assert "is_alarm_on BOOLEAN DEFAULT TRUE" in users_create_sql
        conn.execute("DROP INDEX IF EXISTS idx_users_open_id")
        conn.execute("DROP INDEX IF EXISTS idx_users_plusfriend_key")
        conn.execute("DROP TABLE users")
        conn.execute(
            users_create_sql.replace(
                "is_alarm_on BOOLEAN DEFAULT TRUE",
                "is_alarm_on BOOLEAN DEFAULT FALSE",
            )
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_open_id ON users(open_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_plusfriend_key ON users(plusfriend_user_key)")
        conn.commit()
    finally:
        conn.close()

    report = generate_compatibility_report(database_path=str(db_path))

    users_columns = _find_required_columns(report, "users")
    assert users_columns["missing_columns"] == []
    assert users_columns["mismatched_columns"] == ["is_alarm_on"]

    is_alarm_on_column = _find_required_column_definition(users_columns, "is_alarm_on")
    assert is_alarm_on_column["definition_matches"] is False
    assert is_alarm_on_column["expected"]["default"] != is_alarm_on_column["actual"]["default"]
    assert "mismatched column definition in users: is_alarm_on" in report["failure_reasons"]


def test_probe_report_tolerates_quoted_extra_index_names(tmp_path, settings_overrides):
    db_path = tmp_path / "compatibility-probe-quoted-index.db"
    settings_overrides(DATABASE_PATH=str(db_path))
    init_db()

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            'CREATE INDEX "idx users weird space" ON users(favorite_zone)'
        )
        conn.commit()
    finally:
        conn.close()

    report = generate_compatibility_report(database_path=str(db_path))

    assert report["failure_reasons"] == []


def test_probe_evidence_references_resolve_to_existing_source_lines():
    references = []
    for assumption in SQLITE_DIALECT_ASSUMPTIONS:
        references.extend(assumption["evidence"])
    references.extend(ROW_ACCESS_CONTRACT["evidence"])
    references.extend(STARTUP_CONTRACT["evidence"])

    for reference in references:
        _assert_evidence_reference_exists(reference)


def test_probe_cli_returns_structured_json_for_missing_database_path(tmp_path):
    db_path = tmp_path / "compatibility-probe-cli-missing.db"
    assert not db_path.exists()

    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-m",
            "app.database.compatibility_probe",
            "--database-path",
            str(db_path),
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=repo_root,
    )

    report = json.loads(result.stdout)
    assert report["database_path"] == str(db_path.resolve())
    assert all(not table["exists"] for table in report["required_tables"])
    assert f"missing database file: {db_path.resolve()}" in report["failure_reasons"]
    assert not db_path.exists()


def test_probe_cli_returns_structured_json_for_invalid_database_file(tmp_path):
    db_path = tmp_path / "compatibility-probe-cli-invalid.db"
    db_path.write_text("not sqlite", encoding="utf-8")

    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-m",
            "app.database.compatibility_probe",
            "--database-path",
            str(db_path),
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=repo_root,
    )

    report = json.loads(result.stdout)
    assert report["database_path"] == str(db_path.resolve())
    assert all(not table["exists"] for table in report["required_tables"])
    assert (
        f"unreadable database file: {db_path.resolve()} (file is not a database)"
        in report["failure_reasons"]
    )


def test_probe_cli_smoke_outputs_json_report(tmp_path, settings_overrides):
    db_path = tmp_path / "compatibility-probe-cli.db"
    settings_overrides(DATABASE_PATH=str(db_path))
    init_db()

    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-m",
            "app.database.compatibility_probe",
            "--database-path",
            str(db_path),
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=repo_root,
    )

    report = json.loads(result.stdout)
    assert report["database_path"] == str(db_path.resolve())
    assert report["report_version"] == 2
    assert report["engine_specific_delta"]["current_engine"] == "sqlite"
    assert report["detected_assumptions_count"] == len(report["sqlite_dialect_assumptions"])
    assert report["failure_reasons"] == []


def test_probe_logs_mode_and_database_path_source(tmp_path, settings_overrides, caplog):
    db_path = tmp_path / "compatibility-probe-log.db"
    settings_overrides(DATABASE_PATH=str(db_path))
    init_db()

    caplog.set_level(logging.INFO)
    caplog.clear()

    report = generate_compatibility_report(database_path=str(db_path))
    assert report["database_path"] == str(db_path.resolve())

    probe_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "app.database.compatibility_probe"
    ]
    assert any(
        "mode=probe" in message
        and "path_source=argument" in message
        and str(db_path.resolve()) in message
        for message in probe_messages
    )
