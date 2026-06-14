"""Spark-logic tests for the node builders' transient ``embedding_text`` column.

These exercise the real DataFrame builders against a local SparkSession, so they
run under the ``databricks`` dependency group (``make test-databricks``). The
top-level ``pyspark`` import is guarded with ``importorskip`` so collection in
the default ``test-unit`` group skips, rather than errors, this module.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pyspark")

from neocarta.connectors.databricks.ingest.schema_graph import (
    build_column_nodes,
    build_database_nodes,
    build_schema_nodes,
    build_table_nodes,
)


def _one(df, column):
    """Return the single-row value of ``column`` from a one-row DataFrame."""
    rows = df.collect()
    assert len(rows) == 1
    return rows[0][column]


def _tables_schema():
    """information_schema.tables shape, with explicit nullable timestamp types so
    the all-None ``created`` / ``last_altered`` columns do not break inference."""
    from pyspark.sql.types import StringType, StructField, StructType, TimestampType

    return StructType(
        [
            StructField("table_catalog", StringType()),
            StructField("table_schema", StringType()),
            StructField("table_name", StringType()),
            StructField("comment", StringType()),
            StructField("table_type", StringType()),
            StructField("created", TimestampType()),
            StructField("last_altered", TimestampType()),
        ]
    )


def test_database_nodes_embedding_text_equals_name(local_spark):
    """The Database embedding text is the catalog name (EXPR[DATABASE] == 'name')."""
    df = build_database_nodes(local_spark, ["sales"], platform="AWS")
    assert "embedding_text" in df.columns
    assert _one(df, "embedding_text") == "sales"
    assert _one(df, "embedding_text") == _one(df, "name")


def test_schema_nodes_embedding_text_is_catalog_qualified(local_spark):
    """Schema embedding text qualifies the name with its catalog plus comment."""
    schemata = local_spark.createDataFrame(
        [("sales", "public", "customer facing")],
        ["catalog_name", "schema_name", "comment"],
    )
    df = build_schema_nodes(schemata)
    assert "embedding_text" in df.columns
    assert _one(df, "embedding_text") == "sales.public | customer facing"


def test_schema_nodes_embedding_text_drops_blank_comment(local_spark):
    """A blank/whitespace comment is dropped, leaving just the qualified name."""
    schemata = local_spark.createDataFrame(
        [("sales", "public", "   ")],
        ["catalog_name", "schema_name", "comment"],
    )
    assert _one(build_schema_nodes(schemata), "embedding_text") == "sales.public"


def test_table_nodes_embedding_text_is_catalog_qualified(local_spark):
    """Table embedding text leads with catalog.schema.table plus the comment."""
    tables = local_spark.createDataFrame(
        [("sales", "public", "orders", "order facts", "MANAGED", None, None)],
        _tables_schema(),
    )
    df = build_table_nodes(tables)
    assert "embedding_text" in df.columns
    assert _one(df, "embedding_text") == "sales.public.orders | order facts"


def test_column_nodes_embedding_text_includes_type_and_comment(local_spark):
    """Column embedding text is the 4-part name, then the data type, then comment."""
    columns = local_spark.createDataFrame(
        [("sales", "public", "orders", "total", "DECIMAL", "YES", "line total", 3)],
        [
            "table_catalog",
            "table_schema",
            "table_name",
            "column_name",
            "data_type",
            "is_nullable",
            "comment",
            "ordinal_position",
        ],
    )
    df = build_column_nodes(columns)
    assert "embedding_text" in df.columns
    assert _one(df, "embedding_text") == "sales.public.orders.total | DECIMAL | line total"


def test_builders_do_not_leak_information_schema_helpers(local_spark):
    """Only declared properties plus the transient embedding_text survive; raw
    information_schema helper columns never leave the builder."""
    tables = local_spark.createDataFrame(
        [("sales", "public", "orders", "c", "MANAGED", None, None)],
        _tables_schema(),
    )
    cols = set(build_table_nodes(tables).columns)
    assert "embedding_text" in cols
    assert "table_catalog" not in cols
    assert "comment" not in cols  # surfaces as `description`, not the raw name
