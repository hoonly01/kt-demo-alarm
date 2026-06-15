"""데이터베이스 bootstrap 선언과 additive migration 적용."""

from __future__ import annotations

import logging
import sqlite3

from app.database.models import (
    BOOTSTRAP_TABLE_SCHEMAS,
    TABLE_INDEX_STATEMENTS,
    TABLE_MIGRATION_COLUMNS,
)

logger = logging.getLogger(__name__)


def _existing_columns(cursor: sqlite3.Cursor, table_name: str) -> set[str]:
    return {
        row[1]
        for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def _add_column_with_duplicate_tolerance(
    cursor: sqlite3.Cursor,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    try:
        cursor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
        )
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise


def ensure_table_columns(
    cursor: sqlite3.Cursor,
    table_name: str,
    columns: list[tuple[str, str]],
) -> None:
    existing_columns = _existing_columns(cursor, table_name)
    for column_name, column_definition in columns:
        if column_name in existing_columns:
            continue
        _add_column_with_duplicate_tolerance(
            cursor,
            table_name,
            column_name,
            column_definition,
        )
        existing_columns.add(column_name)


def ensure_table_indexes(
    cursor: sqlite3.Cursor,
    statements: tuple[str, ...],
) -> None:
    for statement in statements:
        cursor.execute(statement)


def ensure_events_contract(cursor: sqlite3.Cursor) -> None:
    ensure_table_columns(cursor, "events", TABLE_MIGRATION_COLUMNS["events"])
    ensure_table_indexes(cursor, TABLE_INDEX_STATEMENTS["events"])


def apply_bootstrap_contract(cursor: sqlite3.Cursor) -> None:
    for statement in BOOTSTRAP_TABLE_SCHEMAS.values():
        cursor.execute(statement)

    for table_name, columns in TABLE_MIGRATION_COLUMNS.items():
        ensure_table_columns(cursor, table_name, columns)

    for statements in TABLE_INDEX_STATEMENTS.values():
        ensure_table_indexes(cursor, statements)


def bootstrap_database(database_path: str, *, path_source: str = "settings") -> None:
    conn = sqlite3.connect(database_path, check_same_thread=False)
    try:
        cursor = conn.cursor()
        apply_bootstrap_contract(cursor)
        conn.commit()
        logger.info(
            "database lifecycle mode=bootstrap db_path=%s path_source=%s",
            database_path,
            path_source,
        )
    finally:
        conn.close()
