"""Unity Catalog extraction — pure information_schema reads + node/rel DataFrame build.

This module does *only* UC extraction and DataFrame assembly for schemas,
tables, and columns. FK discovery (declared, metadata) lives in
`neocarta.connectors.databricks.ingest.fk.discovery` and runs against the extracted material.
Embedding enrichment happens later in the ingestion pipeline, before the Neo4j load.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import neocarta.connectors.databricks.ingest.schema_graph as sg
from neocarta.connectors.databricks.ingest.summary import ExtractCounts, RunSummary

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

    from neocarta.connectors.databricks.settings import SparkIngestSettings

logger = logging.getLogger(__name__)


@dataclass
class ExtractResult:
    """Raw UC extraction + node/rel DataFrames. No FK edges, no counters.

    Fields are mutable only because embedding enrichment replaces the node
    DataFrames in place after staging. The cached information_schema
    DataFrames stay attached so later FK discovery and sample-value transforms
    can reuse the same catalog snapshot.
    """

    database_df: DataFrame
    schema_node_df: DataFrame
    table_node_df: DataFrame
    column_node_df: DataFrame
    has_schema_df: DataFrame
    has_table_df: DataFrame
    has_column_df: DataFrame
    schemata_df: DataFrame
    tables_df: DataFrame
    columns_df: DataFrame

    def unpersist_cached(self) -> None:
        """Release cached information_schema DataFrames after the ingest run.

        Extraction caches the three source DataFrames because several
        downstream steps read them. The pipeline calls this once the graph load
        and verification steps no longer need the snapshot.
        """
        self.schemata_df.unpersist()
        self.tables_df.unpersist()
        self.columns_df.unpersist()


def _extract_constraints(
    spark: SparkSession,
    catalogs: list[str],
    schema_list: list[str],
) -> DataFrame:
    """Per-column DECLARED key-constraint flags from information_schema.

    Joins `key_column_usage` to `table_constraints` per catalog and aggregates
    to one row per column with `is_primary_key` / `is_foreign_key` booleans
    (declared PRIMARY KEY / FOREIGN KEY participation). Columns with no
    declared constraint simply do not appear; `build_column_nodes` left-joins
    and coalesces their flags to false. Matches neocarta core's declared-only
    semantics — inferred FK edges (discovered later) never set these flags.

    Native Spark join + aggregate, no driver collect: the constraint tables are
    catalog-scale, so the flags ride a broadcastable left join into the column
    build rather than being resolved on the driver.
    """
    from functools import reduce

    from pyspark.sql.functions import col
    from pyspark.sql.functions import max as col_max

    def _union(frames: list[DataFrame]) -> DataFrame:
        return reduce(lambda a, b: a.unionByName(b), frames)

    raw = _union(
        [
            spark.sql(
                f"SELECT kcu.table_catalog, kcu.table_schema, kcu.table_name,"
                f"       kcu.column_name, tc.constraint_type"
                f" FROM `{catalog}`.information_schema.key_column_usage kcu"
                f" JOIN `{catalog}`.information_schema.table_constraints tc"
                f"   ON tc.constraint_catalog = kcu.constraint_catalog"
                f"  AND tc.constraint_schema  = kcu.constraint_schema"
                f"  AND tc.constraint_name    = kcu.constraint_name"
            )
            for catalog in catalogs
        ]
    ).filter(col("table_schema") != "information_schema")
    if schema_list:
        raw = raw.filter(col("table_schema").isin(schema_list))

    keys = ["table_catalog", "table_schema", "table_name", "column_name"]
    return raw.groupBy(*keys).agg(
        col_max(col("constraint_type") == "PRIMARY KEY").alias("is_primary_key"),
        col_max(col("constraint_type") == "FOREIGN KEY").alias("is_foreign_key"),
    )


def extract(
    spark: SparkSession,
    settings: SparkIngestSettings,
    schema_list: list[str],
    summary: RunSummary,
) -> ExtractResult:
    """Pull information_schema metadata for the configured catalog/schemas.

    Populates `summary.extract` in the process — this is the one place the
    extract counts are recorded. The returned DataFrames are already filtered
    to the requested schema scope and cached for reuse by later transforms.
    """
    from functools import reduce

    from pyspark.sql.functions import col

    catalogs = settings.resolved_catalogs()

    def _union(frames: list[DataFrame]) -> DataFrame:
        return reduce(lambda a, b: a.unionByName(b), frames)

    schemata_df = _union(
        [
            spark.sql(
                f"SELECT catalog_name, schema_name, comment"
                f" FROM `{catalog}`.information_schema.schemata"
            )
            for catalog in catalogs
        ]
    ).filter(col("schema_name") != "information_schema")
    if schema_list:
        schemata_df = schemata_df.filter(col("schema_name").isin(schema_list))
    schemata_df = schemata_df.cache()

    tables_df = _union(
        [
            spark.sql(
                f"SELECT table_catalog, table_schema, table_name, table_type,"
                f"       comment, created, last_altered"
                f" FROM `{catalog}`.information_schema.tables"
            )
            for catalog in catalogs
        ]
    ).filter(col("table_schema") != "information_schema")
    if schema_list:
        tables_df = tables_df.filter(col("table_schema").isin(schema_list))
    tables_df = tables_df.cache()

    columns_df = _union(
        [
            spark.sql(
                f"SELECT table_catalog, table_schema, table_name, column_name,"
                f"       data_type, is_nullable, ordinal_position, comment"
                f" FROM `{catalog}`.information_schema.columns"
            )
            for catalog in catalogs
        ]
    ).filter(col("table_schema") != "information_schema")
    if schema_list:
        columns_df = columns_df.filter(col("table_schema").isin(schema_list))
    columns_df = columns_df.cache()

    summary.extract = ExtractCounts(
        schemas=schemata_df.count(),
        tables=tables_df.count(),
        columns=columns_df.count(),
    )

    logger.info(
        "[databricks] read: schemas=%d tables=%d columns=%d",
        summary.extract.schemas,
        summary.extract.tables,
        summary.extract.columns,
    )

    database_df = sg.build_database_nodes(spark, catalogs, settings.platform or None)
    schema_node_df = sg.build_schema_nodes(schemata_df)
    table_node_df = sg.build_table_nodes(tables_df, settings.layer_map())
    constraints_df = _extract_constraints(spark, catalogs, schema_list)
    column_node_df = sg.build_column_nodes(columns_df, constraints_df)
    has_schema_df = sg.build_has_schema_rel(schemata_df)
    has_table_df = sg.build_has_table_rel(tables_df)
    has_column_df = sg.build_has_column_rel(columns_df)

    return ExtractResult(
        database_df=database_df,
        schema_node_df=schema_node_df,
        table_node_df=table_node_df,
        column_node_df=column_node_df,
        has_schema_df=has_schema_df,
        has_table_df=has_table_df,
        has_column_df=has_column_df,
        schemata_df=schemata_df,
        tables_df=tables_df,
        columns_df=columns_df,
    )
