"""Prior-edge suppression threaded as DataFrames across the strategies.

Metadata anti-joins the declared-only edge frame. The prior is a
`(source_id, target_id)` DataFrame, never collected.
"""

from __future__ import annotations

from dbxcarta.spark.contract import EdgeSource
from dbxcarta.spark.ingest.fk.discovery import FKDiscoveryResult
from dbxcarta.spark.ingest.fk.inference import (
    build_columns_frame,
    build_pk_gate,
    infer_metadata_edges,
)

_CAT = "main"
_SCHEMA = "shop"

_COL_FIELDS = (
    "table_catalog",
    "table_schema",
    "table_name",
    "column_name",
    "data_type",
    "comment",
)
_CON_FIELDS = (
    "table_catalog",
    "table_schema",
    "table_name",
    "column_name",
    "constraint_type",
    "ordinal_position",
    "constraint_name",
)
_EDGE = (
    f"{_CAT}.{_SCHEMA}.orders.customer_id",
    f"{_CAT}.{_SCHEMA}.customers.id",
)


def _columns_schema():
    from pyspark.sql.types import StringType, StructField, StructType

    return StructType([StructField(n, StringType(), True) for n in _COL_FIELDS])


def _constraints_schema():
    from pyspark.sql.types import (
        IntegerType,
        StringType,
        StructField,
        StructType,
    )

    return StructType(
        [
            StructField("table_catalog", StringType(), True),
            StructField("table_schema", StringType(), True),
            StructField("table_name", StringType(), True),
            StructField("column_name", StringType(), True),
            StructField("constraint_type", StringType(), True),
            StructField("ordinal_position", IntegerType(), True),
            StructField("constraint_name", StringType(), True),
        ]
    )


def _columns(spark):
    rows = [
        (_CAT, _SCHEMA, "customers", "id", "BIGINT", None),
        (_CAT, _SCHEMA, "orders", "customer_id", "BIGINT", None),
    ]
    return spark.createDataFrame(rows, schema=_columns_schema())


def _constraints(spark):
    rows = [(_CAT, _SCHEMA, "customers", "id", "PRIMARY KEY", 1, "customers_pk")]
    return spark.createDataFrame(rows, schema=_constraints_schema())


def test_metadata_skips_declared_prior_pair(local_spark) -> None:
    """Metadata would infer orders.customer_id → customers.id; the
    declared-only prior frame suppresses exactly that edge."""
    cf = build_columns_frame(_columns(local_spark))
    pk_gate, composite = build_pk_gate(cf, _constraints(local_spark))
    prior = local_spark.createDataFrame([_EDGE], schema=["source_id", "target_id"])
    edges_df, _counts, _c = infer_metadata_edges(
        local_spark,
        cf,
        pk_gate,
        prior,
        composite_pk_count=composite,
    )
    emitted = {(r["source_id"], r["target_id"]) for r in edges_df.collect()}
    assert _EDGE not in emitted


def test_fk_result_releases_cached_inferred_edges(local_spark) -> None:
    from pyspark.sql.types import DoubleType, StringType, StructField, StructType

    edge_schema = StructType(
        [
            StructField("source_id", StringType(), False),
            StructField("target_id", StringType(), False),
            StructField("confidence", DoubleType(), False),
            StructField("source", StringType(), False),
            StructField("criteria", StringType(), True),
        ]
    )
    metadata_df = local_spark.createDataFrame(
        [("s", "t", 0.9, EdgeSource.INFERRED_METADATA.value, None)],
        schema=edge_schema,
    ).cache()
    metadata_df.count()

    result = FKDiscoveryResult(
        declared_edges_df=None,
        declared_edge_count=0,
        metadata_edges_df=metadata_df,
        metadata_edge_count=1,
    )
    result.unpersist_cached()

    assert not metadata_df.storageLevel.useMemory
