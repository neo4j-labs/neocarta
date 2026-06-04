"""Spark-side graph-contract expression tests."""

from __future__ import annotations

from dbxcarta.spark.contract import generate_id
from dbxcarta.spark.ingest.contract_expr import id_expr, id_expr_from_columns


def test_id_expr_matches_core_generate_id(local_spark) -> None:
    rows = [("Main Catalog", "Sales-Data", "Orders Table", "Customer-ID")]
    df = local_spark.createDataFrame(rows, ["catalog", "schema", "table", "column"])

    got = df.select(id_expr("catalog", "schema", "table", "column").alias("id")).collect()[0]["id"]

    assert got == generate_id("Main Catalog", "Sales-Data", "Orders Table", "Customer-ID")


def test_id_expr_from_columns_supports_literals_and_row_values(local_spark) -> None:
    from pyspark.sql.functions import col, lit

    df = local_spark.createDataFrame([("Customer-ID",)], ["col_name"])

    got = df.select(
        id_expr_from_columns(
            lit("Main Catalog"),
            lit("Sales-Data"),
            lit("Orders Table"),
            col("col_name"),
        ).alias("id")
    ).collect()[0]["id"]

    assert got == generate_id("Main Catalog", "Sales-Data", "Orders Table", "Customer-ID")
