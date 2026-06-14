"""Pre-run checks: catalog accessibility, presence of tables to ingest, and
embedding-endpoint reachability.

Runs before any catalog extraction or Neo4j write. A preflight failure means
the rest of the run cannot succeed, so the caller lets these exceptions fail the
job after the run summary records the error.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from neocarta.connectors.databricks._platform.identifiers import quote_identifier

if TYPE_CHECKING:
    from pyspark.sql import SparkSession

    from neocarta.connectors.databricks.settings import SparkIngestSettings

logger = logging.getLogger(__name__)


def preflight(spark: SparkSession, settings: SparkIngestSettings) -> None:
    """Fail fast on a mis-provisioned or empty catalog.

    Three checks:
      1. Each resolved catalog's information_schema is readable.
      2. At least one user table exists in scope (an empty catalog would
         otherwise produce a silently empty graph instead of a clear error).
      3. When inline embeddings are enabled, the configured serving endpoint
         answers a trivial ai_query and returns a vector of the expected
         dimension.
    """
    catalogs = settings.resolved_catalogs()
    for catalog in catalogs:
        spark.sql(
            f"SELECT 1 FROM {quote_identifier(catalog)}.information_schema.schemata LIMIT 1"
        ).collect()

    _assert_tables_exist(spark, settings, catalogs)

    if settings.any_embeddings_enabled():
        _assert_embedding_endpoint(spark, settings)

    logger.info(
        "[databricks] preflight passed: %s information_schema accessible, tables present",
        ", ".join(catalogs),
    )


def _assert_embedding_endpoint(spark: SparkSession, settings: SparkIngestSettings) -> None:
    """Confirm the inline embedding endpoint is reachable and dimension-correct.

    Runs only when at least one embedding flag is on. Sends a trivial
    ``ai_query`` and checks the returned vector length equals the configured
    ``embedding_dimension``, so a missing endpoint, a permission gap, or a
    model/dimension mismatch fails the run before any node write rather than
    midway through embedding.
    """
    from py4j.protocol import Py4JJavaError  # type: ignore[import-untyped]
    from pyspark.errors import AnalysisException

    endpoint = settings.embedding_endpoint
    # ai_query surfaces failures through the Spark execution layer, so narrow to
    # the two types Spark actually raises: AnalysisException for SQL/plan errors,
    # Py4JJavaError for runtime JVM exceptions. Anything else propagates.
    try:
        rows = spark.sql(
            f"SELECT ai_query('{endpoint}', 'preflight', failOnError => false) AS response"
        ).collect()
    except (AnalysisException, Py4JJavaError) as exc:
        raise RuntimeError(
            f"[databricks] preflight: embedding endpoint '{endpoint}' unreachable"
            f" or missing invoke permission: {exc}"
        ) from exc

    resp = rows[0]["response"]
    if resp["errorMessage"] is not None:
        raise RuntimeError(
            f"[databricks] preflight: embedding endpoint '{endpoint}' returned an error:"
            f" {resp['errorMessage']}"
        )
    vec = resp["result"]
    if vec is None or len(vec) != settings.embedding_dimension:
        actual = len(vec) if vec is not None else 0
        raise RuntimeError(
            f"[databricks] preflight: embedding endpoint '{endpoint}' returned a vector of"
            f" length {actual}, expected {settings.embedding_dimension}."
            " Set NEOCARTA_DATABRICKS_EMBEDDING_DIMENSION to match the endpoint."
        )


def _assert_tables_exist(
    spark: SparkSession,
    settings: SparkIngestSettings,
    catalogs: list[str],
) -> None:
    """Confirm at least one user table exists in scope.

    Counts user tables in ``information_schema.tables`` across the resolved
    catalogs, scoped to the configured schemas when set and to all non-system
    schemas otherwise. Finding one table anywhere in scope is enough; a single
    ``LIMIT 1`` probe per catalog keeps this O(1), not catalog-scale.
    """
    schema_list = [s.strip() for s in settings.schemas.split(",") if s.strip()]
    schema_filter = ""
    if schema_list:
        in_list = ", ".join(f"'{s}'" for s in schema_list)
        schema_filter = f" AND table_schema IN ({in_list})"

    for catalog in catalogs:
        rows = spark.sql(
            f"SELECT 1 FROM {quote_identifier(catalog)}.information_schema.tables"
            f" WHERE table_schema <> 'information_schema'{schema_filter} LIMIT 1"
        ).take(1)
        if rows:
            return

    scope = f"schemas {schema_list}" if schema_list else "any non-system schema"
    raise RuntimeError(
        f"[databricks] preflight: no tables found in {', '.join(catalogs)} ({scope})."
        " The connector ingests existing Unity Catalog tables; point it at a"
        " catalog/schema that holds tables."
    )
