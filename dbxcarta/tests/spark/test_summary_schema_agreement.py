"""Guard that the run-summary writer schema and the preflight CREATE TABLE
agree on column types.

The writer (``summary_io.summary_table_schema``) appends with ``mergeSchema``,
so a type that drifts from the preflight CREATE TABLE
(``preflight._SUMMARY_TABLE_COLUMNS_SQL``) stays hidden until the table is
recreated from scratch, at which point the run fails on a Delta merge error.
This pins the two surfaces to the same types.
"""

from __future__ import annotations

import re

from dbxcarta.spark.ingest.preflight import _SUMMARY_TABLE_COLUMNS_SQL
from dbxcarta.spark.ingest.summary_io import summary_table_schema
from pyspark.sql.types import ArrayType, DataType, MapType

_SCALAR_SQL = {
    "StringType": "STRING",
    "LongType": "BIGINT",
    "DoubleType": "DOUBLE",
    "BooleanType": "BOOLEAN",
    "TimestampType": "TIMESTAMP",
}


def _spark_type_to_sql(dtype: DataType) -> str:
    """Render a Spark DataType as the canonical SQL type used in the DDL."""
    if isinstance(dtype, ArrayType):
        return f"ARRAY<{_spark_type_to_sql(dtype.elementType)}>"
    if isinstance(dtype, MapType):
        return f"MAP<{_spark_type_to_sql(dtype.keyType)},{_spark_type_to_sql(dtype.valueType)}>"
    return _SCALAR_SQL[type(dtype).__name__]


def _normalize(sql_type: str) -> str:
    """Strip nullability and whitespace so two SQL types compare structurally."""
    return re.sub(r"\s+", "", sql_type.upper().replace("NOT NULL", ""))


def _ddl_columns() -> dict[str, str]:
    columns: dict[str, str] = {}
    for line in _SUMMARY_TABLE_COLUMNS_SQL.splitlines():
        stripped = line.strip().rstrip(",")
        if not stripped:
            continue
        name, _, sql_type = stripped.partition(" ")
        columns[name] = _normalize(sql_type)
    return columns


def _writer_columns() -> dict[str, str]:
    return {
        field.name: _normalize(_spark_type_to_sql(field.dataType))
        for field in summary_table_schema().fields
    }


def test_preflight_ddl_and_writer_schema_agree_on_shared_columns() -> None:
    ddl = _ddl_columns()
    writer = _writer_columns()

    shared = ddl.keys() & writer.keys()
    assert shared, "expected overlapping columns between DDL and writer schema"

    mismatches = {
        name: (ddl[name], writer[name]) for name in sorted(shared) if ddl[name] != writer[name]
    }
    assert not mismatches, (
        "preflight CREATE TABLE and summary_table_schema() disagree on column "
        f"types (col: ddl vs writer): {mismatches}"
    )


def test_preflight_declares_no_column_the_writer_never_writes() -> None:
    # The writer may carry columns the append adds via mergeSchema, but every
    # column the preflight DDL declares must exist in the writer schema, or the
    # CREATE TABLE would seed a column the writer never populates.
    orphan = _ddl_columns().keys() - _writer_columns().keys()
    assert not orphan, f"preflight declares columns the writer never writes: {orphan}"


def test_embedding_failure_threshold_is_integer_typed() -> None:
    # Regression: failure_threshold is an int count (dbxcarta_embedding_failure_max
    # is `int`), so both sides must be BIGINT. A DOUBLE here failed the run on a
    # Delta merge error once the summary table was recreated.
    assert _ddl_columns()["embedding_failure_threshold"] == "BIGINT"
    assert _writer_columns()["embedding_failure_threshold"] == "BIGINT"
