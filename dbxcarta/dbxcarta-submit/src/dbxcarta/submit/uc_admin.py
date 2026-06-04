"""Local Unity Catalog admin for the bootstrap and teardown commands.

Both commands run on the operator's machine and execute their DDL through a
SQL warehouse, the way the retired per-example scripts did. The create path
and the drop path each live here exactly once, so there is a single source of
the SQL and the safety checks.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from dbxcarta.core.executor import catalog_exists
from dbxcarta.core.identifiers import (
    check_not_protected,
    quote_identifier,
    validate_identifier,
)

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient

_POLL_INTERVAL_SEC = 2.0
# Cap on polling past the initial 50s server-side wait, generous enough to
# cover a cold warehouse starting up before it can run the quick DDL.
_MAX_POLL_SEC = 300.0


def execute_statement(ws: WorkspaceClient, warehouse_id: str, statement: str) -> None:
    """Run one SQL statement on the warehouse and wait for it to finish.

    The DDL the bootstrap and teardown commands issue is quick, so the 50s
    server-side wait usually returns a terminal state. If the warehouse is
    still starting and the statement is not yet terminal, poll until it is. A
    non-``SUCCEEDED`` terminal state is raised rather than silently swallowed,
    so a failed ``CREATE``/``DROP`` can never be reported as success.
    """
    from databricks.sdk.service.sql import (
        ExecuteStatementRequestOnWaitTimeout,
        StatementState,
    )

    resp = ws.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=statement,
        wait_timeout="50s",
        on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CONTINUE,
    )

    terminal = {
        StatementState.SUCCEEDED,
        StatementState.FAILED,
        StatementState.CANCELED,
        StatementState.CLOSED,
    }
    deadline = time.monotonic() + _MAX_POLL_SEC
    while resp.status is None or resp.status.state not in terminal:
        if time.monotonic() >= deadline:
            raise RuntimeError(f"statement did not finish in time:\n{statement}")
        if resp.statement_id is None:
            raise RuntimeError("warehouse did not return a statement id")
        time.sleep(_POLL_INTERVAL_SEC)
        resp = ws.statement_execution.get_statement(resp.statement_id)

    if resp.status.state is not StatementState.SUCCEEDED:
        detail = ""
        if resp.status.error is not None and resp.status.error.message:
            detail = f": {resp.status.error.message}"
        state = resp.status.state.value if resp.status.state else "UNKNOWN"
        raise RuntimeError(f"statement {state}{detail}\n{statement}")


def ensure_uc_catalog(ws: WorkspaceClient, warehouse_id: str, *, catalog: str) -> None:
    """Create the catalog if missing (idempotent).

    Used for both the ops catalog (via :func:`ensure_uc_volume`) and the data
    catalog named by ``DBXCARTA_CATALOG``, so the protected-name guard and the
    Default-Storage skip-if-exists handling live in one place.
    """
    check_not_protected(catalog, label="catalog")
    catalog_q = quote_identifier(catalog)
    # Skip CREATE CATALOG when the catalog already exists: on Default-Storage
    # accounts the statement fails without a MANAGED LOCATION even with IF NOT
    # EXISTS, so a pre-created (e.g. UI-created) catalog must not be re-created.
    if not catalog_exists(ws, warehouse_id, catalog):
        execute_statement(
            ws,
            warehouse_id,
            f"CREATE CATALOG IF NOT EXISTS {catalog_q}"
            " COMMENT 'dbxcarta bootstrap: example catalog'",
        )


def ensure_uc_volume(
    ws: WorkspaceClient,
    warehouse_id: str,
    *,
    catalog: str,
    schema: str,
    volume: str,
) -> None:
    """Create the catalog, schema, and volume if missing (idempotent)."""
    ensure_uc_catalog(ws, warehouse_id, catalog=catalog)
    catalog_q = quote_identifier(catalog)
    schema_q = quote_identifier(schema)
    volume_q = quote_identifier(volume)
    execute_statement(
        ws,
        warehouse_id,
        f"CREATE SCHEMA IF NOT EXISTS {catalog_q}.{schema_q}"
        " COMMENT 'dbxcarta bootstrap: example schema'",
    )
    execute_statement(
        ws,
        warehouse_id,
        f"CREATE VOLUME IF NOT EXISTS {catalog_q}.{schema_q}.{volume_q}"
        " COMMENT 'dbxcarta bootstrap: example volume'",
    )


class TeardownKind(Enum):
    SCHEMA = "schema"
    CATALOG = "catalog"


@dataclass(frozen=True)
class TeardownTarget:
    """A validated `DBXCARTA_TEARDOWN_TARGET`: a schema or a whole catalog."""

    kind: TeardownKind
    catalog: str
    schema: str | None = None

    def describe(self) -> str:
        if self.kind is TeardownKind.CATALOG:
            return f"catalog {self.catalog}"
        return f"schema {self.catalog}.{self.schema}"


def parse_teardown_target(value: str) -> TeardownTarget:
    """Parse ``DBXCARTA_TEARDOWN_TARGET`` into a validated target.

    Accepts ``schema:<catalog>.<schema>`` or ``catalog:<catalog>``. The
    explicit prefix keeps the destructive "drop the whole catalog" case a
    declared choice rather than something a missing schema segment can trigger.
    """
    prefix, sep, rest = value.strip().partition(":")
    if not sep:
        raise ValueError(
            "DBXCARTA_TEARDOWN_TARGET must be 'schema:<catalog>.<schema>' or "
            f"'catalog:<catalog>', got {value!r}"
        )
    rest = rest.strip()
    if prefix == "catalog":
        validate_identifier(rest, label="teardown catalog")
        check_not_protected(rest, label="catalog")
        return TeardownTarget(kind=TeardownKind.CATALOG, catalog=rest)
    if prefix == "schema":
        catalog, dot, schema = rest.partition(".")
        if not dot:
            raise ValueError(
                f"schema teardown target must be 'schema:<catalog>.<schema>', got {value!r}"
            )
        validate_identifier(catalog, label="teardown catalog")
        validate_identifier(schema, label="teardown schema")
        check_not_protected(catalog, label="catalog")
        return TeardownTarget(kind=TeardownKind.SCHEMA, catalog=catalog, schema=schema)
    raise ValueError(
        f"DBXCARTA_TEARDOWN_TARGET prefix must be 'schema' or 'catalog', got {prefix!r}"
    )


def parse_teardown_targets(value: str) -> list[TeardownTarget]:
    """Parse a comma-separated ``DBXCARTA_TEARDOWN_TARGET`` into targets.

    An example that owns more than one thing (e.g. a data catalog plus an ops
    schema in the shared ops catalog) lists each target separated by commas, so
    one teardown removes everything it owns. Each item is validated by
    :func:`parse_teardown_target`, so the protected-name guard and the explicit
    ``catalog:``/``schema:`` prefix apply per target. A value with no parseable
    target is a hard error rather than a silent no-op.
    """
    targets = [parse_teardown_target(item) for item in value.split(",") if item.strip()]
    if not targets:
        raise ValueError(
            "DBXCARTA_TEARDOWN_TARGET must name at least one "
            "'schema:<catalog>.<schema>' or 'catalog:<catalog>' target"
        )
    return targets


def drop_teardown_target(ws: WorkspaceClient, warehouse_id: str, target: TeardownTarget) -> None:
    """Drop exactly the target schema or catalog, cascading."""
    catalog_q = quote_identifier(target.catalog)
    if target.kind is TeardownKind.CATALOG:
        execute_statement(ws, warehouse_id, f"DROP CATALOG IF EXISTS {catalog_q} CASCADE")
        return
    if target.schema is None:  # unreachable: SCHEMA kind always sets schema
        raise ValueError("schema teardown target is missing its schema name")
    schema_q = quote_identifier(target.schema)
    execute_statement(ws, warehouse_id, f"DROP SCHEMA IF EXISTS {catalog_q}.{schema_q} CASCADE")
