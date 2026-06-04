"""Warehouse SQL executor: run statements and report results or success."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from databricks.sdk.service.sql import (
    Disposition,
    ExecuteStatementRequestOnWaitTimeout,
    Format,
    StatementState,
    StatementStatus,
)

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient


def _statement_error(status: StatementStatus | None, state: StatementState | None) -> str:
    if status and status.error and status.error.message:
        return status.error.message
    return str(state)


def execute_sql(
    ws: WorkspaceClient,
    warehouse_id: str,
    sql: str,
    timeout_sec: int = 30,
) -> tuple[bool, bool, str | None]:
    """Execute *sql* against *warehouse_id*.

    Returns (executed, non_empty, error_message).
    - executed: True when the statement completed without a warehouse error.
    - non_empty: True when at least one row was returned.
    - error_message: set when executed is False.
    """
    response = ws.statement_execution.execute_statement(
        statement=sql,
        warehouse_id=warehouse_id,
        wait_timeout=f"{timeout_sec}s",
        disposition=Disposition.INLINE,
        format=Format.JSON_ARRAY,
    )

    status = response.status
    state = status.state if status else None

    if state == StatementState.SUCCEEDED:
        data = (response.result and response.result.data_array) or []
        return True, len(data) > 0, None

    if state in (StatementState.FAILED, StatementState.CANCELED):
        return False, False, _statement_error(status, state)

    # PENDING or RUNNING means the timeout elapsed before completion.
    return False, False, f"statement did not complete within {timeout_sec}s (state={state})"


def fetch_rows(
    ws: WorkspaceClient,
    warehouse_id: str,
    sql: str,
    timeout_sec: int = 30,
) -> tuple[list[str] | None, list[list[Any]] | None, str | None]:
    """Execute SQL and return (column_names, rows, error).

    Returns (None, None, error_message) on failure.
    Column names come from the statement manifest; rows are returned as-is from
    the JSON_ARRAY disposition.
    """
    response = ws.statement_execution.execute_statement(
        statement=sql,
        warehouse_id=warehouse_id,
        wait_timeout=f"{timeout_sec}s",
        disposition=Disposition.INLINE,
        format=Format.JSON_ARRAY,
    )

    status = response.status
    state = status.state if status else None

    if state == StatementState.SUCCEEDED:
        columns: list[str] = []
        if response.manifest and response.manifest.schema and response.manifest.schema.columns:
            columns = [
                col.name or f"col_{index + 1}"
                for index, col in enumerate(response.manifest.schema.columns)
            ]
        chunk = response.result
        data: list[list[Any]] = list(chunk.data_array or []) if chunk else []
        statement_id = response.statement_id
        while chunk and chunk.next_chunk_index is not None:
            if statement_id is None:
                return None, None, "statement id missing for paginated result"
            chunk = ws.statement_execution.get_statement_result_chunk_n(
                statement_id, chunk.next_chunk_index
            )
            if chunk:
                data.extend(chunk.data_array or [])
        return columns, data, None

    if state in (StatementState.FAILED, StatementState.CANCELED):
        return None, None, _statement_error(status, state)

    return None, None, f"statement did not complete within {timeout_sec}s (state={state})"


def catalog_exists(ws: WorkspaceClient, warehouse_id: str, catalog: str) -> bool:
    """Return True if *catalog* already exists in the metastore.

    Guards ``CREATE CATALOG``: on accounts with Default Storage enabled but no
    metastore storage root URL, ``CREATE CATALOG`` fails unless given a
    ``MANAGED LOCATION``, even with ``IF NOT EXISTS`` on a catalog that already
    exists. Callers check this first and skip the create when the catalog is
    already present (for example, pre-created in the workspace UI).
    """
    _, rows, error = fetch_rows(ws, warehouse_id, "SHOW CATALOGS")
    if error is not None or rows is None:
        raise RuntimeError(f"could not list catalogs to check for {catalog!r}: {error}")
    return any(row and row[0] == catalog for row in rows)


def execute_ddl(
    ws: WorkspaceClient,
    warehouse_id: str,
    sql: str,
    timeout_sec: int = 50,
    catalog: str | None = None,
) -> tuple[bool, str | None]:
    """Execute a DDL statement (CREATE, ALTER, DROP, USE) and return success.

    Returns (succeeded, error_message). DDL produces no result set so
    Disposition and Format are omitted.
    """
    response = ws.statement_execution.execute_statement(
        statement=sql,
        warehouse_id=warehouse_id,
        wait_timeout=f"{timeout_sec}s",
        catalog=catalog,
    )
    status = response.status
    state = status.state if status else None
    if state == StatementState.SUCCEEDED:
        return True, None
    if state in (StatementState.FAILED, StatementState.CANCELED):
        return False, _statement_error(status, state)
    return False, f"statement did not complete within {timeout_sec}s (state={state})"


def execute_ddl_blocking(
    ws: WorkspaceClient,
    warehouse_id: str,
    statement: str,
    *,
    label: str = "",
    total_timeout_sec: float = 600.0,
    poll_interval_sec: float = 3.0,
) -> None:
    """Execute one statement and block until it reaches a terminal state.

    Unlike :func:`execute_ddl`, this polls ``get_statement`` past the API's 50s
    synchronous ``wait_timeout`` cap, so a slow ``CREATE TABLE`` or ``INSERT``
    on a large catalog runs to completion instead of being reported as a
    spurious timeout. Raises ``RuntimeError`` on a failed statement and
    ``TimeoutError`` when it does not finish within ``total_timeout_sec``. The
    ``label`` appears only in error messages.
    """
    start = time.monotonic()
    response = ws.statement_execution.execute_statement(
        statement=statement,
        warehouse_id=warehouse_id,
        wait_timeout="50s",
        on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CONTINUE,
    )
    statement_id = response.statement_id
    if statement_id is None:
        raise RuntimeError(f"no statement id returned for: {label or statement[:80]}")

    status = response.status
    state = status.state if status else StatementState.SUCCEEDED
    deadline = start + total_timeout_sec
    while state in (StatementState.PENDING, StatementState.RUNNING):
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"statement did not complete within {total_timeout_sec:.0f}s:"
                f" {label or statement[:80]}"
            )
        time.sleep(poll_interval_sec)
        response = ws.statement_execution.get_statement(statement_id)
        status = response.status
        state = status.state if status else StatementState.SUCCEEDED

    if state != StatementState.SUCCEEDED:
        raise RuntimeError(
            f"statement failed (state={state}): {label or statement[:80]}"
            f" — {_statement_error(status, state)}"
        )


def split_sql_statements(sql: str) -> list[str]:
    """Split a SQL script on semicolons, discarding comment-only and empty segments.

    Tracks -- line-comment state and single-quoted string literals so semicolons
    inside comments or strings are not treated as statement boundaries. Does not
    handle block comments (/* */); this is sufficient for DDL scripts.
    """
    result = []
    current: list[str] = []
    in_line_comment = False
    in_string = False

    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if in_string:
            current.append(ch)
            if ch == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    # SQL escaped quote: '' — consume both chars
                    i += 1
                    current.append(sql[i])
                else:
                    in_string = False
        elif in_line_comment:
            current.append(ch)
            if ch == "\n":
                in_line_comment = False
        elif ch == "'":
            in_string = True
            current.append(ch)
        elif ch == "-" and i + 1 < n and sql[i + 1] == "-":
            in_line_comment = True
            current.append(ch)
        elif ch == ";":
            segment = "".join(current).strip()
            has_sql = any(
                line and not line.startswith("--")
                for line in (raw.strip() for raw in segment.splitlines())
            )
            if has_sql:
                result.append(segment)
            current = []
        else:
            current.append(ch)
        i += 1

    # trailing segment with no final semicolon
    segment = "".join(current).strip()
    has_sql = any(
        line and not line.startswith("--") for line in (raw.strip() for raw in segment.splitlines())
    )
    if has_sql:
        result.append(segment)

    return result


def preflight_warehouse(ws: WorkspaceClient, warehouse_id: str) -> None:
    """Raise RuntimeError if the warehouse is unreachable or returns an error."""
    executed, _, error = execute_sql(ws, warehouse_id, "SELECT 1", timeout_sec=30)
    if not executed:
        raise RuntimeError(f"Warehouse preflight failed: {error}")
