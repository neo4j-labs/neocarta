"""Catalog-vs-graph contract checks: id normalization + complex-type round-trip.

Uses the Databricks SQL warehouse to sample from `information_schema.columns`,
then verifies the corresponding Neo4j nodes have the expected id and `type`
(the graph property; sourced from the UC `data_type` column).
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

from dbxcarta.spark.contract import generate_id
from dbxcarta.spark.verify import Violation

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementParameterListItem
    from neo4j import Driver


_COMPLEX_TYPE_FAMILIES = ("STRUCT", "ARRAY", "MAP", "VARIANT", "INTERVAL")


def check(
    driver: Driver,
    summary: dict[str, Any],
    *,
    ws: WorkspaceClient,
    warehouse_id: str,
    catalog: str,
) -> list[Violation]:
    if not warehouse_id:
        return [
            Violation(
                code="catalog.no_warehouse",
                message="DATABRICKS_WAREHOUSE_ID not set; catalog-vs-graph checks skipped.",
            )
        ]
    out: list[Violation] = []
    out.extend(
        _check_id_normalization(driver, summary, ws=ws, warehouse_id=warehouse_id, catalog=catalog)
    )
    out.extend(
        _check_complex_type_round_trip(
            driver, summary, ws=ws, warehouse_id=warehouse_id, catalog=catalog
        )
    )
    return out


def _str_param(name: str, value: str) -> StatementParameterListItem:
    """Build a STRING-typed bound parameter for the Statement Execution API."""
    from databricks.sdk.service.sql import StatementParameterListItem

    return StatementParameterListItem(name=name, value=value, type="STRING")


def _columns_table(catalog: str) -> str:
    """Back-quoted columns-table name bound via IDENTIFIER(:tbl).

    Each part is back-quoted so a catalog whose name is not a simple
    identifier still resolves, matching both the prior interpolated form
    (which back-quoted the catalog) and the documented IDENTIFIER canonical
    example. The value still travels as a bound parameter, never
    interpolated, so this only affects name resolution, not injection.
    """
    return f"`{catalog}`.`information_schema`.`columns`"


def _schema_filter(
    schemas: list[str],
) -> tuple[str, list[StatementParameterListItem]]:
    """Build a bound `table_schema IN (...)` fragment, one marker per schema.

    Returns an empty fragment and no parameters when the list is empty, which
    preserves the prior unfiltered behavior.
    """
    if not schemas:
        return "", []
    markers = ", ".join(f":s{i}" for i in range(len(schemas)))
    params = [_str_param(f"s{i}", s) for i, s in enumerate(schemas)]
    return f" AND table_schema IN ({markers})", params


def _exec(
    ws: WorkspaceClient,
    warehouse_id: str,
    statement: str,
    parameters: list[StatementParameterListItem] | None = None,
) -> list[list[Any]]:
    """Execute a SQL statement; return data_array rows or [] if no result.

    When `parameters` is supplied, values travel to the warehouse as bound
    parameter markers rather than interpolated text, so no value can alter
    the statement structure.
    """
    result = ws.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=statement,
        wait_timeout="30s",
        parameters=parameters,
    )
    if result.result is None:
        return []
    return list(result.result.data_array or [])


def _check_id_normalization(
    driver: Driver,
    summary: dict[str, Any],
    *,
    ws: WorkspaceClient,
    warehouse_id: str,
    catalog: str,
) -> list[Violation]:
    """Sampled column IDs must exist in Neo4j; Python generate_id must equal the
    Spark SQL id_expr equivalent byte-for-byte.
    """
    out: list[Violation] = []
    schemas = summary.get("schemas") or []
    schema_filter, schema_params = _schema_filter(schemas)

    rows = _exec(
        ws,
        warehouse_id,
        (
            "SELECT table_catalog, table_schema, table_name, column_name"
            " FROM IDENTIFIER(:tbl)"
            f" WHERE table_schema != 'information_schema'{schema_filter}"
            " LIMIT 500"
        ),
        [_str_param("tbl", _columns_table(catalog)), *schema_params],
    )
    if rows:
        sample = random.sample(rows, min(50, len(rows)))
        missing: list[str] = []
        with driver.session() as s:
            for row in sample:
                table_catalog, table_schema, table_name, column_name = row
                expected_id = generate_id(table_catalog, table_schema, table_name, column_name)
                found = s.run("MATCH (n:Column {id: $id}) RETURN n.id", id=expected_id).single()
                if not found:
                    missing.append(expected_id)
        if missing:
            out.append(
                Violation(
                    code="catalog.column_id_missing_in_neo4j",
                    message=f"{len(missing)} column id(s) sampled from {catalog} not found in Neo4j.",
                    details={"missing_count": len(missing), "examples": missing[:5]},
                )
            )

    sql_rows = _exec(
        ws,
        warehouse_id,
        (
            "SELECT table_catalog, table_schema, table_name, column_name,"
            " lower(translate(concat_ws('.', table_catalog, table_schema, table_name, column_name), ' -', '__')) AS sql_id"
            " FROM IDENTIFIER(:tbl)"
            " LIMIT 100"
        ),
        [_str_param("tbl", _columns_table(catalog))],
    )
    mismatches: list[tuple[str, str]] = []
    for row in sql_rows:
        table_catalog, table_schema, table_name, column_name, sql_id = row
        py_id = generate_id(table_catalog, table_schema, table_name, column_name)
        if py_id != sql_id:
            mismatches.append((py_id, sql_id))
    if mismatches:
        out.append(
            Violation(
                code="catalog.python_spark_id_drift",
                message=f"Python generate_id() differs from Spark SQL id_expr() for {len(mismatches)} row(s).",
                details={"count": len(mismatches), "examples": mismatches[:3]},
            )
        )
    return out


def _check_complex_type_round_trip(
    driver: Driver,
    summary: dict[str, Any],
    *,
    ws: WorkspaceClient,
    warehouse_id: str,
    catalog: str,
) -> list[Violation]:
    """For each complex data type family present in the run's scope, the
    corresponding Column node in Neo4j must store that type string verbatim
    on its `type` property (sourced from the UC `data_type` column). Families
    absent from the in-scope schemas skip. Sampling is constrained to
    `summary["schemas"]` so columns belonging to objects the run did not load
    (e.g. the run-summary Delta table itself, which lives outside the test
    fixture schemas) cannot surface as false-positive "missing node" violations.
    """
    out: list[Violation] = []
    schemas = summary.get("schemas") or []
    schema_filter, schema_params = _schema_filter(schemas)
    with driver.session() as s:
        for prefix in _COMPLEX_TYPE_FAMILIES:
            rows = _exec(
                ws,
                warehouse_id,
                (
                    "SELECT table_catalog, table_schema, table_name, column_name, data_type"
                    " FROM IDENTIFIER(:tbl)"
                    f" WHERE upper(data_type) LIKE :prefix{schema_filter}"
                    " LIMIT 1"
                ),
                [
                    _str_param("tbl", _columns_table(catalog)),
                    _str_param("prefix", f"{prefix}%"),
                    *schema_params,
                ],
            )
            if not rows:
                continue
            table_catalog, table_schema, table_name, column_name, data_type = rows[0]
            expected_id = generate_id(table_catalog, table_schema, table_name, column_name)
            node = s.run("MATCH (n:Column {id: $id}) RETURN n.type AS dt", id=expected_id).single()
            if node is None:
                out.append(
                    Violation(
                        code=f"catalog.complex_type_column_missing.{prefix}",
                        message=f"Column node not found for {prefix} sample id={expected_id}.",
                        details={"id": expected_id, "family": prefix},
                    )
                )
            elif node["dt"] != data_type:
                out.append(
                    Violation(
                        code=f"catalog.complex_type_data_type_drift.{prefix}",
                        message=f"data_type mismatch for {prefix} sample id={expected_id}.",
                        details={"id": expected_id, "stored": node["dt"], "expected": data_type},
                    )
                )
    return out
