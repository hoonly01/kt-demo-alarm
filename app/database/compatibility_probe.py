"""현재 앱의 SQLite 호환성 계약을 보고하는 read-only probe."""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.database.bootstrap import apply_bootstrap_contract
from app.database.connection import get_database_path
from app.database.models import BOOTSTRAP_TABLE_SCHEMAS

logger = logging.getLogger(__name__)

PROBE_TABLE_ORDER = tuple(BOOTSTRAP_TABLE_SCHEMAS)
REPORT_VERSION = 2
REQUIRED_REPORT_FIELDS = (
    "report_version",
    "database_path",
    "required_tables",
    "required_columns",
    "required_indexes",
    "sqlite_dialect_assumptions",
    "engine_specific_delta",
    "detected_assumptions_count",
    "failure_reasons",
    "row_access_contract",
    "startup_contract",
)

SQLITE_DIALECT_ASSUMPTIONS = (
    {
        "id": "sqlite_row_factory",
        "detail": "런타임 조회 결과는 sqlite3.Row 기반 매핑 접근을 전제로 한다.",
        "evidence": [
            "app/database/connection.py:16-17",
            "app/database/connection.py:27-28",
        ],
    },
    {
        "id": "pragma_table_info",
        "detail": "admin legacy schema 호환은 PRAGMA table_info(...) 응답 형식에 의존한다.",
        "evidence": [
            "app/routers/admin.py:395-405",
        ],
    },
    {
        "id": "rowid_fallback",
        "detail": "recent alarm/event 조회는 rowid fallback 정렬을 사용한다.",
        "evidence": [
            "app/routers/admin.py:319-325",
            "app/routers/admin.py:364-369",
            "app/services/alarm_status_service.py:216-245",
        ],
    },
    {
        "id": "partial_unique_index",
        "detail": "events.source_record_hash partial unique index 가 현재 bootstrap 계약에 포함된다.",
        "evidence": [
            "app/database/bootstrap.py:65-67",
            "app/database/models.py:133-136",
        ],
    },
    {
        "id": "datetime_now_kst_offset",
        "detail": "경로 집회 조회는 datetime('now', '+9 hours') 를 사용한다.",
        "evidence": [
            "app/services/event_service.py:214-219",
        ],
    },
    {
        "id": "date_start_date",
        "detail": "오늘 집회 조회는 date(start_date) 비교를 사용한다.",
        "evidence": [
            "app/services/event_service.py:453-464",
        ],
    },
)

ROW_ACCESS_CONTRACT = {
    "row_factory": "sqlite3.Row",
    "access_pattern": "row['column_name']",
    "evidence": [
        "app/database/connection.py:16-17",
        "app/database/connection.py:27-28",
    ],
}

STARTUP_CONTRACT = {
    "bootstrap_entrypoint": "app.database.connection.init_db",
    "probe_runs_on_startup": False,
    "evidence": [
        "main.py:36-54",
    ],
}


def _build_contract_snapshot() -> dict[str, Any]:
    """현재 bootstrap 선언이 요구하는 테이블/컬럼/인덱스 계약을 계산한다."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        apply_bootstrap_contract(conn.cursor())
        return _collect_schema_snapshot(conn)
    finally:
        conn.close()


def _build_engine_specific_delta() -> dict[str, Any]:
    """현재 SQLite 런타임 전용 delta 를 action-oriented 형태로 정리한다."""
    category_by_assumption_id = {
        "sqlite_row_factory": "row_access",
        "pragma_table_info": "schema_introspection",
        "rowid_fallback": "legacy_fallback",
        "partial_unique_index": "index_dialect",
        "datetime_now_kst_offset": "datetime_expression",
        "date_start_date": "date_expression",
    }
    portability_hotspots = [
        {
            "assumption_id": assumption["id"],
            "category": category_by_assumption_id[assumption["id"]],
            "detail": assumption["detail"],
            "evidence": assumption["evidence"],
        }
        for assumption in SQLITE_DIALECT_ASSUMPTIONS
    ]
    return {
        "current_engine": "sqlite",
        "current_driver": "sqlite3",
        "active_assumption_ids": [
            assumption["id"]
            for assumption in SQLITE_DIALECT_ASSUMPTIONS
        ],
        "portability_hotspots": portability_hotspots,
    }


def _collect_schema_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    table_names = _get_existing_tables(conn)
    column_definitions_by_table = {}
    columns_by_table = {}
    for table_name in PROBE_TABLE_ORDER:
        if table_name not in table_names:
            continue
        column_definitions = _get_table_column_definitions(conn, table_name)
        column_definitions_by_table[table_name] = column_definitions
        columns_by_table[table_name] = [
            column["name"]
            for column in column_definitions
        ]
    indexes = []
    for table_name in PROBE_TABLE_ORDER:
        if table_name in table_names:
            indexes.extend(_get_table_indexes(conn, table_name))

    return normalize_schema_snapshot(
        {
            "table_names": table_names,
            "columns_by_table": columns_by_table,
            "column_definitions_by_table": column_definitions_by_table,
            "indexes": indexes,
        }
    )


def normalize_schema_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """schema snapshot 을 deterministic ordering 으로 정규화한다."""
    normalized_columns = {
        table_name: sorted(columns)
        for table_name, columns in sorted(snapshot["columns_by_table"].items())
    }
    normalized_column_definitions = {
        table_name: sorted(
            [
                _normalize_column_definition(column)
                for column in columns
            ],
            key=lambda item: item["name"],
        )
        for table_name, columns in sorted(
            snapshot.get("column_definitions_by_table", {}).items()
        )
    }
    normalized_indexes = sorted(
        snapshot["indexes"],
        key=lambda item: (item["table"], item["name"]),
    )
    return {
        "table_names": sorted(snapshot["table_names"]),
        "columns_by_table": normalized_columns,
        "column_definitions_by_table": normalized_column_definitions,
        "indexes": normalized_indexes,
    }


def _get_existing_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        """
    ).fetchall()
    return {row["name"] for row in rows}


def _normalize_column_definition(column: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": column["name"],
        "type": column["type"],
        "notnull": bool(column["notnull"]),
        "default": column["default"],
        "pk": int(column["pk"]),
    }


def _quote_identifier(identifier: str) -> str:
    return f'"{identifier.replace("\"", "\"\"")}"'


def _get_table_column_definitions(
    conn: sqlite3.Connection,
    table_name: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"PRAGMA table_info({_quote_identifier(table_name)})"
    ).fetchall()
    return [
        _normalize_column_definition(
            {
                "name": row["name"],
                "type": row["type"],
                "notnull": row["notnull"],
                "default": row["dflt_value"],
                "pk": row["pk"],
            }
        )
        for row in rows
    ]


def _get_table_indexes(conn: sqlite3.Connection, table_name: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"PRAGMA index_list({_quote_identifier(table_name)})"
    ).fetchall()
    indexes = []
    for row in rows:
        index_name = row["name"]
        sql_row = conn.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'index' AND name = ?
            """,
            (index_name,),
        ).fetchone()
        indexes.append(
            {
                "table": table_name,
                "name": index_name,
                "columns": _get_index_columns(conn, index_name),
                "unique": bool(row["unique"]),
                "partial": bool(row["partial"]),
                "where": _extract_where_clause(sql_row["sql"] if sql_row else None),
            }
        )
    return indexes


def _get_index_columns(conn: sqlite3.Connection, index_name: str) -> list[str]:
    rows = conn.execute(
        f"PRAGMA index_info({_quote_identifier(index_name)})"
    ).fetchall()
    return [row["name"] for row in rows]


def _extract_where_clause(index_sql: str | None) -> str | None:
    if not index_sql:
        return None

    match = re.search(r"\bWHERE\b\s+(.*)$", index_sql, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip()


def _normalize_sql_fragment(sql_fragment: str | None) -> str | None:
    if sql_fragment is None:
        return None
    return " ".join(sql_fragment.split()).lower()


def _normalize_column_type(column_type: str | None) -> str:
    if column_type is None:
        return ""
    return " ".join(column_type.split()).upper()


def _column_definition_matches(
    expected_column: dict[str, Any],
    actual_column: dict[str, Any],
) -> bool:
    return (
        _normalize_column_type(expected_column["type"])
        == _normalize_column_type(actual_column["type"])
        and bool(expected_column["notnull"]) == bool(actual_column["notnull"])
        and _normalize_sql_fragment(expected_column["default"])
        == _normalize_sql_fragment(actual_column["default"])
        and int(expected_column["pk"]) == int(actual_column["pk"])
    )


def _index_definition_matches(
    expected_index: dict[str, Any],
    actual_index: dict[str, Any],
) -> bool:
    return (
        expected_index["columns"] == actual_index["columns"]
        and expected_index["unique"] == actual_index["unique"]
        and expected_index["partial"] == actual_index["partial"]
        and _normalize_sql_fragment(expected_index["where"])
        == _normalize_sql_fragment(actual_index["where"])
    )


def open_readonly_probe_connection(database_path: str) -> sqlite3.Connection:
    connection_uri = f"{Path(database_path).resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(connection_uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    query_only_row = conn.execute("PRAGMA query_only").fetchone()
    if query_only_row[0] != 1:
        conn.close()
        raise RuntimeError("Probe connection did not enable query_only mode.")
    return conn


def _build_failure_reasons(
    required_tables: list[dict[str, Any]],
    required_columns: list[dict[str, Any]],
    required_indexes: list[dict[str, Any]],
) -> list[str]:
    failure_reasons = [
        f"missing table: {table['name']}"
        for table in required_tables
        if not table["exists"]
    ]
    for table in required_columns:
        if table["missing_columns"]:
            missing = ", ".join(table["missing_columns"])
            failure_reasons.append(f"missing columns in {table['table']}: {missing}")
        if table["mismatched_columns"]:
            mismatched = ", ".join(table["mismatched_columns"])
            failure_reasons.append(
                f"mismatched column definition in {table['table']}: {mismatched}"
            )
    for index in required_indexes:
        if not index["exists"]:
            failure_reasons.append(f"missing index: {index['name']}")
            continue
        if not index["definition_matches"]:
            failure_reasons.append(f"mismatched index definition: {index['name']}")
    return failure_reasons


def _empty_schema_snapshot() -> dict[str, Any]:
    return normalize_schema_snapshot(
        {
            "table_names": [],
            "columns_by_table": {},
            "column_definitions_by_table": {},
            "indexes": [],
        }
    )


def _build_unreadable_database_reason(
    database_path: Path,
    exc: Exception,
) -> str:
    return f"unreadable database file: {database_path.resolve()} ({exc})"


def _load_actual_snapshot(target_database: Path) -> tuple[dict[str, Any], list[str]]:
    if not target_database.is_file():
        return (
            _empty_schema_snapshot(),
            [f"missing database file: {target_database.resolve()}"],
        )

    try:
        conn = open_readonly_probe_connection(str(target_database))
        try:
            return _collect_schema_snapshot(conn), []
        finally:
            conn.close()
    except (sqlite3.DatabaseError, RuntimeError) as exc:
        return (
            _empty_schema_snapshot(),
            [_build_unreadable_database_reason(target_database, exc)],
        )


def validate_report(report: dict[str, Any]) -> dict[str, Any]:
    missing_fields = [
        field_name
        for field_name in REQUIRED_REPORT_FIELDS
        if field_name not in report
    ]
    if missing_fields:
        missing = ", ".join(missing_fields)
        raise ValueError(f"Compatibility probe report is missing required fields: {missing}")

    assumption_count = len(report["sqlite_dialect_assumptions"])
    if report["detected_assumptions_count"] != assumption_count:
        raise ValueError(
            "Compatibility probe report has mismatched detected_assumptions_count."
        )

    engine_specific_delta = report["engine_specific_delta"]
    if not isinstance(engine_specific_delta, dict):
        raise ValueError("Compatibility probe report engine_specific_delta must be a dict.")

    active_assumption_ids = engine_specific_delta.get("active_assumption_ids")
    expected_assumption_ids = [
        assumption["id"]
        for assumption in report["sqlite_dialect_assumptions"]
    ]
    if active_assumption_ids != expected_assumption_ids:
        raise ValueError(
            "Compatibility probe report engine_specific_delta has mismatched active_assumption_ids."
        )

    portability_hotspots = engine_specific_delta.get("portability_hotspots")
    if not isinstance(portability_hotspots, list) or len(portability_hotspots) != assumption_count:
        raise ValueError(
            "Compatibility probe report engine_specific_delta must list portability_hotspots for every assumption."
        )

    if not isinstance(report["failure_reasons"], list):
        raise ValueError("Compatibility probe report failure_reasons must be a list.")

    return report


def serialize_report(report: dict[str, Any], *, output_format: str = "json") -> str:
    validated_report = validate_report(report)
    if output_format != "json":
        raise ValueError(f"Unsupported probe output format: {output_format}")
    return json.dumps(validated_report, ensure_ascii=False, indent=2, sort_keys=True)


def generate_compatibility_report(database_path: str | None = None) -> dict[str, Any]:
    """현재 앱 계약과 대상 DB 상태를 함께 요약한 probe 보고서를 만든다."""
    target_database_path = database_path or get_database_path()
    path_source = "argument" if database_path else "settings"
    target_database = Path(target_database_path)
    resolved_database_path = str(target_database.resolve())
    contract_snapshot = _build_contract_snapshot()
    actual_snapshot, database_failure_reasons = _load_actual_snapshot(target_database)

    actual_indexes_by_name = {
        index["name"]: index
        for index in actual_snapshot["indexes"]
    }

    required_tables = [
        {
            "name": table_name,
            "exists": table_name in actual_snapshot["table_names"],
        }
        for table_name in PROBE_TABLE_ORDER
    ]

    required_columns = []
    for table_name in PROBE_TABLE_ORDER:
        expected_columns = contract_snapshot["columns_by_table"].get(table_name, [])
        actual_columns = actual_snapshot["columns_by_table"].get(table_name, [])
        expected_column_definitions = {
            column["name"]: column
            for column in contract_snapshot["column_definitions_by_table"].get(
                table_name,
                [],
            )
        }
        actual_column_definitions = {
            column["name"]: column
            for column in actual_snapshot["column_definitions_by_table"].get(
                table_name,
                [],
            )
        }
        column_definitions = []
        for column_name in expected_columns:
            actual_column = actual_column_definitions.get(column_name)
            expected_column = expected_column_definitions[column_name]
            column_definitions.append(
                {
                    "name": column_name,
                    "exists": actual_column is not None,
                    "definition_matches": actual_column is not None
                    and _column_definition_matches(expected_column, actual_column),
                    "expected": expected_column,
                    "actual": actual_column,
                }
            )
        required_columns.append(
            {
                "table": table_name,
                "columns": expected_columns,
                "missing_columns": [
                    column_name
                    for column_name in expected_columns
                    if column_name not in actual_columns
                ],
                "mismatched_columns": [
                    column["name"]
                    for column in column_definitions
                    if column["exists"] and not column["definition_matches"]
                ],
                "column_definitions": column_definitions,
            }
        )

    required_indexes = []
    for expected_index in contract_snapshot["indexes"]:
        actual_index = actual_indexes_by_name.get(expected_index["name"])
        required_indexes.append(
            {
                **expected_index,
                "exists": actual_index is not None,
                "definition_matches": actual_index is not None
                and _index_definition_matches(expected_index, actual_index),
                "actual": actual_index,
            }
        )

    failure_reasons = [
        *database_failure_reasons,
        *_build_failure_reasons(
            required_tables,
            required_columns,
            required_indexes,
        ),
    ]

    report = {
        "report_version": REPORT_VERSION,
        "database_path": resolved_database_path,
        "required_tables": required_tables,
        "required_columns": required_columns,
        "required_indexes": required_indexes,
        "sqlite_dialect_assumptions": list(SQLITE_DIALECT_ASSUMPTIONS),
        "engine_specific_delta": _build_engine_specific_delta(),
        "detected_assumptions_count": len(SQLITE_DIALECT_ASSUMPTIONS),
        "failure_reasons": failure_reasons,
        "row_access_contract": dict(ROW_ACCESS_CONTRACT),
        "startup_contract": dict(STARTUP_CONTRACT),
    }
    logger.info(
        "database lifecycle mode=probe db_path=%s path_source=%s",
        resolved_database_path,
        path_source,
    )
    return validate_report(report)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="현재 앱의 SQLite 호환성 계약을 JSON 으로 출력한다."
    )
    parser.add_argument(
        "--database-path",
        dest="database_path",
        default=None,
        help="probe 대상 SQLite 파일 경로 (생략 시 settings.DATABASE_PATH 사용)",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=("json",),
        default="json",
        help="출력 형식",
    )
    args = parser.parse_args(argv)
    report = generate_compatibility_report(database_path=args.database_path)
    print(serialize_report(report, output_format=args.output_format))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
