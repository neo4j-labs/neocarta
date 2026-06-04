"""Pre-run checks: catalog accessibility, volume/table provisioning,
embedding-endpoint reachability.

Runs before any catalog extraction or Neo4j write. A preflight failure means
the rest of the run cannot succeed, so the caller should let these exceptions
fail the job after the run summary records the error.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from dbxcarta.core.identifiers import quote_identifier, quote_qualified_name
from dbxcarta.spark.ingest.transform.staging import split_volume_subpath

if TYPE_CHECKING:
    from dbxcarta.spark.settings import SparkIngestSettings
    from pyspark.sql import SparkSession

logger = logging.getLogger(__name__)

# Column definitions for the run-summary history table, kept as a module
# constant (not inlined in the CREATE below) so a test can assert these types
# agree with the writer schema in ``summary_io.summary_table_schema()``. A type
# that drifts between the two surfaces only when the table is recreated from
# scratch, because the writer's append uses ``mergeSchema``. The writer schema
# additionally carries ``value_sampling_warning`` / ``verify_ok`` /
# ``verify_violation_count``; the append adds those via ``mergeSchema``, so
# preflight need not pre-declare them.
_SUMMARY_TABLE_COLUMNS_SQL = """\
            run_id STRING NOT NULL,
            job_name STRING,
            contract_version STRING,
            catalog STRING,
            schemas ARRAY<STRING>,
            started_at TIMESTAMP,
            ended_at TIMESTAMP,
            status STRING,
            row_counts MAP<STRING, BIGINT>,
            neo4j_counts MAP<STRING, BIGINT>,
            error STRING,
            embedding_model STRING,
            embedding_flags MAP<STRING, BOOLEAN>,
            embedding_attempts MAP<STRING, BIGINT>,
            embedding_successes MAP<STRING, BIGINT>,
            embedding_failure_rate_per_label MAP<STRING, DOUBLE>,
            embedding_failure_rate DOUBLE,
            embedding_failure_threshold BIGINT,
            embedding_ledger_hits MAP<STRING, BIGINT>"""


def preflight(spark: SparkSession, settings: SparkIngestSettings) -> None:
    """Fail fast on any mis-provisioned dependency.

    Four checks:
      1. Catalog + information_schema readable.
      2. The Materialize stage produced tables (stage precondition: Ingest
         reads the materialized tables, so an empty catalog means Materialize
         did not run or wrote nowhere this run can see).
      3. Summary volume + summary table exist (create if not).
      4. When any embedding flag is on, the endpoint answers a trivial ai_query
         and returns a vector of the expected dimension.
    """
    from py4j.protocol import Py4JJavaError  # type: ignore[import-untyped]
    from pyspark.errors import AnalysisException

    catalogs = settings.resolved_catalogs()
    for catalog in catalogs:
        spark.sql(
            f"SELECT 1 FROM {quote_identifier(catalog)}.information_schema.schemata LIMIT 1"
        ).collect()

    _assert_materialized_tables_exist(spark, settings, catalogs)

    parts = split_volume_subpath(settings.dbxcarta_summary_volume)
    vol_catalog, vol_schema, vol_name = parts[1], parts[2], parts[3]
    spark.sql(f"CREATE VOLUME IF NOT EXISTS `{vol_catalog}`.`{vol_schema}`.`{vol_name}`")

    quoted_table = quote_qualified_name(
        settings.dbxcarta_summary_table,
        expected_parts=3,
    )
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS {quoted_table} (
{_SUMMARY_TABLE_COLUMNS_SQL}
        ) USING DELTA
    """)

    any_embeddings = any(
        [
            settings.dbxcarta_include_embeddings_tables,
            settings.dbxcarta_include_embeddings_columns,
            settings.dbxcarta_include_embeddings_values,
            settings.dbxcarta_include_embeddings_schemas,
            settings.dbxcarta_include_embeddings_databases,
        ]
    )
    if any_embeddings:
        endpoint = settings.dbxcarta_embedding_endpoint
        # ai_query surfaces failures through the Spark execution layer, so
        # narrow to the two types Spark actually raises: AnalysisException
        # for SQL/plan errors, Py4JJavaError for runtime JVM exceptions.
        # Anything else (e.g. KeyboardInterrupt) propagates unchanged.
        try:
            rows = spark.sql(
                f"SELECT ai_query('{endpoint}', 'preflight', failOnError => false) AS response"
            ).collect()
        except (AnalysisException, Py4JJavaError) as exc:
            raise RuntimeError(
                f"[dbxcarta] preflight: embedding endpoint '{endpoint}' unreachable"
                f" or missing invoke permission: {exc}"
            ) from exc

        resp = rows[0]["response"]
        if resp["errorMessage"] is not None:
            raise RuntimeError(
                f"[dbxcarta] preflight: embedding endpoint '{endpoint}' returned an error:"
                f" {resp['errorMessage']}"
            )
        vec = resp["result"]
        if vec is None or len(vec) != settings.dbxcarta_embedding_dimension:
            actual = len(vec) if vec is not None else 0
            raise RuntimeError(
                f"[dbxcarta] preflight: embedding endpoint '{endpoint}' returned a vector of"
                f" length {actual}, expected {settings.dbxcarta_embedding_dimension}."
                f" Set DBXCARTA_EMBEDDING_DIMENSION to match the endpoint."
            )

    logger.info(
        "[dbxcarta] preflight passed: %s information_schema accessible, volume and table ready",
        ", ".join(catalogs),
    )


def _assert_materialized_tables_exist(
    spark: SparkSession,
    settings: SparkIngestSettings,
    catalogs: list[str],
) -> None:
    """Confirm the Materialize stage left at least one table for Ingest to read.

    Ingest's primary input is the materialized tables; running it before
    Materialize (or against a catalog that materialized nothing this run can
    see) otherwise produces a silently empty graph instead of a clear error.
    The check counts user tables in ``information_schema.tables`` across the
    resolved catalogs, scoped to the configured schemas when
    ``DBXCARTA_SCHEMAS`` is set and to all non-system schemas when it is blank
    (how schemapile runs). Finding one table anywhere in scope is enough; a
    single ``LIMIT 1`` probe per catalog keeps this O(1), not catalog-scale.
    """
    schema_list = [s.strip() for s in settings.dbxcarta_schemas.split(",") if s.strip()]
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
        f"[dbxcarta] preflight: no tables found in {', '.join(catalogs)}"
        f" ({scope}). The Materialize stage must run before Ingest: run the"
        " example's materialize step first so the catalog holds tables to"
        " ingest."
    )
