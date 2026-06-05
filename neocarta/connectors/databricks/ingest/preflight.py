"""Pre-run checks: catalog accessibility and presence of tables to ingest.

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

    Two checks:
      1. Each resolved catalog's information_schema is readable.
      2. At least one user table exists in scope (an empty catalog would
         otherwise produce a silently empty graph instead of a clear error).
    """
    catalogs = settings.resolved_catalogs()
    for catalog in catalogs:
        spark.sql(
            f"SELECT 1 FROM {quote_identifier(catalog)}.information_schema.schemata LIMIT 1"
        ).collect()

    _assert_tables_exist(spark, settings, catalogs)

    logger.info(
        "[databricks] preflight passed: %s information_schema accessible, tables present",
        ", ".join(catalogs),
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
