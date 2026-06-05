"""Schema graph transforms: pure DataFrame builders for Unity Catalog metadata.

Each function accepts DataFrames shaped like Unity Catalog information_schema
queries and returns connector-ready node or relationship DataFrames. Identifier
columns are generated through the shared contract helpers so Python and Spark
produce the same ids.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from neocarta.connectors.databricks.contract import CONTRACT_VERSION, DATABASE_SERVICE
from neocarta.connectors.databricks.ingest.contract_expr import id_expr
from neocarta.connectors.utils.generate_id import compose_id

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession
    from pyspark.sql.types import StructType

    from neocarta.connectors.databricks.ingest.fk.common import FKEdge


def build_database_nodes(
    spark: SparkSession,
    catalogs: list[str],
    platform: str | None = None,
) -> DataFrame:
    """Build one Database node per ingested catalog.

    A single-catalog run passes a one-element list, so the historical
    one-Database-node behavior is preserved.

    `service` is the constant ``DATABASE_SERVICE`` ("DATABRICKS") — every
    catalog this connector ingests is a Unity Catalog catalog. `platform` is the
    optional cloud tag (AWS/AZURE/GCP) from config; ``None`` yields a null
    property. `description` is null today (the extract reads no catalog
    comment). An explicit schema is used so the nullable `platform` and
    `description` columns type as STRING rather than inferring NullType from
    all-None values.
    """
    from pyspark.sql.types import StringType, StructField, StructType

    schema = StructType(
        [
            StructField("id", StringType(), False),
            StructField("name", StringType(), False),
            StructField("platform", StringType(), True),
            StructField("service", StringType(), False),
            StructField("description", StringType(), True),
            StructField("contract_version", StringType(), False),
        ]
    )
    rows = [
        (compose_id(c), c, platform, DATABASE_SERVICE, None, CONTRACT_VERSION) for c in catalogs
    ]
    return spark.createDataFrame(rows, schema)


def build_schema_nodes(schemata_df: DataFrame) -> DataFrame:
    """Build Schema nodes from information_schema.schemata rows.

    Selects only the declared Schema properties; transform inputs
    (`catalog_name`) do not leave the builder.
    """
    from pyspark.sql.functions import col, lit

    return (
        schemata_df.withColumn("id", id_expr("catalog_name", "schema_name"))
        .withColumn("name", col("schema_name"))
        .withColumn("contract_version", lit(CONTRACT_VERSION))
        .select(
            "id",
            "name",
            col("comment").alias("description"),
            "contract_version",
        )
    )


def build_table_nodes(
    tables_df: DataFrame,
    layer_map: dict[str, str] | None = None,
) -> DataFrame:
    """Build Table nodes from information_schema.tables rows.

    Selects only the declared Table properties; transform inputs
    (`table_catalog` / `table_schema`) do not leave the builder. The `layer`
    property is derived from `table_catalog` through the configured
    catalog->layer map; catalogs absent from the map (or an empty map) yield a
    null `layer` (contract v1.1, additive). `layer` is a real, declared
    property.
    """
    from pyspark.sql.functions import col, lit, when
    from pyspark.sql.types import StringType

    layer_expr = lit(None).cast(StringType())
    for catalog, layer in (layer_map or {}).items():
        layer_expr = when(col("table_catalog") == catalog, lit(layer)).otherwise(layer_expr)

    return (
        tables_df.withColumn("id", id_expr("table_catalog", "table_schema", "table_name"))
        .withColumn("name", col("table_name"))
        .withColumn("catalog", col("table_catalog"))
        .withColumn("schema", col("table_schema"))
        .withColumn("layer", layer_expr)
        .withColumn("contract_version", lit(CONTRACT_VERSION))
        .select(
            "id",
            "name",
            "catalog",
            "schema",
            "layer",
            col("comment").alias("description"),
            "table_type",
            "created",
            "last_altered",
            "contract_version",
        )
    )


def build_column_nodes(
    columns_df: DataFrame,
    constraints_df: DataFrame | None = None,
) -> DataFrame:
    """Build Column nodes from information_schema.columns rows.

    Converts Databricks YES/NO nullability strings into booleans while
    preserving ordinal position, data type, and comments for retrieval
    context. Selects only the declared Column properties; the qualifying
    columns (`table_catalog` / `table_schema` / `table_name`) are transform
    inputs and do not leave the builder.

    `is_primary_key` / `is_foreign_key` come from `constraints_df` (one
    boolean row per column, from the catalog's DECLARED PRIMARY KEY / FOREIGN
    KEY constraints), left-joined on the four-part column identity and
    coalesced to false for columns with no declared constraint. ``None`` means
    "no declared constraints known" and yields all-false, matching the
    neocarta core declared-only semantics. Inferred FK edges are a separate
    enrichment and never set these flags.
    """
    from pyspark.sql.functions import coalesce, col, lit, when

    keys = ["table_catalog", "table_schema", "table_name", "column_name"]
    if constraints_df is None:
        joined = columns_df.withColumn("is_primary_key", lit(False)).withColumn(
            "is_foreign_key", lit(False)
        )
    else:
        joined = (
            columns_df.join(constraints_df, on=keys, how="left")
            .withColumn("is_primary_key", coalesce(col("is_primary_key"), lit(False)))
            .withColumn("is_foreign_key", coalesce(col("is_foreign_key"), lit(False)))
        )

    return (
        joined.withColumn("id", id_expr(*keys))
        .withColumn("name", col("column_name"))
        .withColumn("catalog", col("table_catalog"))
        .withColumn("schema", col("table_schema"))
        .withColumn("table", col("table_name"))
        .withColumn(
            "nullable",
            when(col("is_nullable") == "YES", True).when(col("is_nullable") == "NO", False),
        )
        .withColumn("contract_version", lit(CONTRACT_VERSION))
        .select(
            "id",
            "name",
            "catalog",
            "schema",
            "table",
            col("data_type").alias("type"),
            "nullable",
            "is_primary_key",
            "is_foreign_key",
            "ordinal_position",
            col("comment").alias("description"),
            "contract_version",
        )
    )


def build_has_schema_rel(schemata_df: DataFrame) -> DataFrame:
    """Build Database -> Schema edges for every schema in scope.

    The Database source id is derived from each row's `catalog_name`, so a
    multi-catalog snapshot links every schema to its own Database node. This
    matches `build_database_nodes`, whose id is `compose_id(catalog)` and
    `id_expr("catalog_name")` applies the same normalization.
    """
    return (
        schemata_df.withColumn("source_id", id_expr("catalog_name"))
        .withColumn("target_id", id_expr("catalog_name", "schema_name"))
        .select("source_id", "target_id")
    )


def build_has_table_rel(tables_df: DataFrame) -> DataFrame:
    """Build Schema -> Table edges for every table in scope."""
    return (
        tables_df.withColumn("source_id", id_expr("table_catalog", "table_schema"))
        .withColumn("target_id", id_expr("table_catalog", "table_schema", "table_name"))
        .select("source_id", "target_id")
    )


def build_has_column_rel(columns_df: DataFrame) -> DataFrame:
    """Build Table -> Column edges for every column in scope."""
    return (
        columns_df.withColumn("source_id", id_expr("table_catalog", "table_schema", "table_name"))
        .withColumn(
            "target_id", id_expr("table_catalog", "table_schema", "table_name", "column_name")
        )
        .select("source_id", "target_id")
    )


def references_schema() -> StructType:
    """The canonical REFERENCES 5-col schema — single source of truth.

    Both the bounded declared path (`build_references_rel`, list[FKEdge] ->
    DataFrame) and the catalog-scale Spark-native inference path
    (`to_references_rel`, DataFrame -> DataFrame) conform to exactly this.
    """
    from pyspark.sql.types import DoubleType, StringType, StructField, StructType

    return StructType(
        [
            StructField("source_column_id", StringType(), False),
            StructField("target_column_id", StringType(), False),
            StructField("confidence", DoubleType(), False),
            StructField("source", StringType(), False),
            StructField("criteria", StringType(), True),
        ]
    )


def to_references_rel(df: DataFrame) -> DataFrame:
    """Project a Spark-native inference frame onto `references_schema`.

    DataFrame -> DataFrame, no driver collect. Casts each column to the
    canonical type so byte-compatibility with the declared path is enforced
    by the schema, not by coincidental conformance of the upstream
    expressions. The input must already carry the five named columns.
    """
    from pyspark.sql.functions import col

    fields = references_schema().fields
    return df.select(*[col(f.name).cast(f.dataType).alias(f.name) for f in fields])


def build_references_rel(
    spark: SparkSession,
    edges: list[FKEdge],
) -> DataFrame:
    """Wrap FKEdge dataclasses in the canonical REFERENCES 5-col schema.

    Source-agnostic: accepts edges with any EdgeSource tag (DECLARED,
    INFERRED_METADATA). The enum `.value` is serialized at this
    tuple boundary — no magic strings downstream.
    """
    tuples = [
        (e.source_column_id, e.target_column_id, e.confidence, e.source.value, e.criteria)
        for e in edges
    ]
    return spark.createDataFrame(tuples, schema=references_schema())
