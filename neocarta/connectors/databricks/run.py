"""Databricks ingestion orchestrator (schema facts).

Thin coordinator for the schema-ingest run. Its job is limited to:
  1. Construct Settings (fails loudly at boundary via cross-field validators).
  2. Run preflight (fails before any destructive action).
  3. Call extract -> sample values -> write nodes -> declared-FK discovery ->
     write relationships.
  4. Return the in-memory RunSummary.

Embeddings are intentionally not produced here: vectors are added afterward by
neocarta's enrichment layer. Inferred (heuristic) foreign keys live in
`neocarta.enrichment.foreign_keys`. This module ingests catalog facts only.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from neocarta.connectors.databricks.contract import (
    CONTRACT_VERSION,
    NODE_PROPERTIES,
    REFERENCES_PROPERTIES,
    NodeLabel,
    RelType,
)
from neocarta.connectors.databricks.ingest.extract import ExtractResult, extract
from neocarta.connectors.databricks.ingest.fk.discovery import (
    FKDiscoveryResult,
    run_fk_discovery,
)
from neocarta.connectors.databricks.ingest.load.neo4j_io import (
    Neo4jConfig,
    bootstrap_constraints,
    delete_stale_values,
    query_counts,
    write_node,
    write_rel,
)
from neocarta.connectors.databricks.ingest.preflight import preflight
from neocarta.connectors.databricks.ingest.summary import RunSummary
from neocarta.connectors.databricks.ingest.transform.value_stage import (
    ValueResult,
    transform_sample_values,
)
from neocarta.connectors.databricks.settings import SparkIngestSettings

if TYPE_CHECKING:
    from neo4j import Driver
    from pyspark.sql import DataFrame, SparkSession

logger = logging.getLogger(__name__)


def run_ingest(
    *,
    settings: SparkIngestSettings | None = None,
    spark: SparkSession | None = None,
    neo4j: Neo4jConfig | None = None,
) -> RunSummary:
    """Run a complete schema ingest and return the finished RunSummary.

    When called with no arguments, this is the Databricks wheel entrypoint:
    settings load from environment variables, the active Spark session resolves
    lazily, and Neo4j credentials come from the Databricks secret scope. Library
    consumers can pass an explicit ``SparkIngestSettings`` and/or a
    ``Neo4jConfig`` (e.g. running against a local or Spark Connect session).
    """
    resolved_settings = settings if settings is not None else SparkIngestSettings()

    if spark is None:
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.getOrCreate()
    run_id = os.environ.get("DATABRICKS_JOB_RUN_ID", "local")
    schema_list = [s.strip() for s in resolved_settings.schemas.split(",") if s.strip()]

    summary = _build_summary(run_id, resolved_settings, schema_list)
    try:
        _run(spark, resolved_settings, schema_list, summary, neo4j)
        summary.finish(status="success")
    except Exception as exc:
        # Top-level catch-all is deliberate: record _any_ failure into
        # RunSummary.error before re-raising so a Databricks job still fails.
        summary.finish(status="failure", error=str(exc))
        raise
    return summary


def _build_summary(
    run_id: str, settings: SparkIngestSettings, schema_list: list[str]
) -> RunSummary:
    """Create the run summary shell before any Spark or Neo4j work begins."""
    return RunSummary(
        run_id=run_id,
        job_name="databricks",
        contract_version=CONTRACT_VERSION,
        catalog=settings.catalog,
        schemas=schema_list,
    )


def _resolve_neo4j(settings: SparkIngestSettings, neo4j: Neo4jConfig | None) -> Neo4jConfig:
    """Resolve Neo4j connection details.

    Precedence: an explicitly passed ``Neo4jConfig`` (library/local use) >
    ``NEO4J_*`` process env > the Databricks secret scope (on-cluster jobs).
    """
    if neo4j is not None:
        return neo4j
    uri = os.environ.get("NEO4J_URI")
    username = os.environ.get("NEO4J_USERNAME")
    password = os.environ.get("NEO4J_PASSWORD")
    if uri and username and password:
        return Neo4jConfig(
            uri=uri,
            username=username,
            password=password,
            batch_size=settings.neo4j_batch_size,
        )
    from databricks.sdk.runtime import dbutils

    scope = settings.secret_scope
    return Neo4jConfig(
        uri=dbutils.secrets.get(scope=scope, key="NEO4J_URI"),
        username=dbutils.secrets.get(scope=scope, key="NEO4J_USERNAME"),
        password=dbutils.secrets.get(scope=scope, key="NEO4J_PASSWORD"),
        batch_size=settings.neo4j_batch_size,
    )


def _run(
    spark: SparkSession,
    settings: SparkIngestSettings,
    schema_list: list[str],
    summary: RunSummary,
    neo4j_override: Neo4jConfig | None,
) -> None:
    """Execute the ingest workflow after settings and summary are initialized.

    Resource ordering: preflight runs before the Neo4j driver opens, graph
    constraints are bootstrapped before writes, nodes are written, sampled
    Values reconciled, declared FKs discovered, relationships written, and the
    cached extraction DataFrames released afterward.
    """
    from neo4j import GraphDatabase

    extract_result: ExtractResult | None = None
    values: ValueResult | None = None
    neo4j = _resolve_neo4j(settings, neo4j_override)

    preflight(spark, settings)

    run_error: BaseException | None = None
    try:
        with GraphDatabase.driver(neo4j.uri, auth=(neo4j.username, neo4j.password)) as driver:
            bootstrap_constraints(driver)

            extract_result = extract(spark, settings, schema_list, summary)

            # Sample distinct values before writing nodes so the Value frame is
            # ready to write alongside the Column nodes.
            values = transform_sample_values(spark, settings, schema_list, extract_result, summary)

            _write_nodes(neo4j, extract_result, values, summary)

            # Scoped stale-Value cleanup after this run's Values are written.
            if values is not None:
                _stale_value_cleanup(driver, settings, schema_list, values, summary)

            fk_result = run_fk_discovery(spark, settings, schema_list, summary)

            _load(neo4j, settings, extract_result, fk_result, values, summary)
            summary.neo4j_counts = query_counts(driver)
    except Exception as exc:
        run_error = exc
        raise
    finally:
        # Release cached snapshots after _load has finished reading them. Each
        # release is guarded independently; on the success path a release
        # failure is re-raised, on the failure path it is logged so it does not
        # mask the original error.
        if values is not None:
            try:
                values.unpersist_cached()
            except Exception:
                if run_error is not None:
                    logger.exception(
                        "[neocarta] failed to unpersist cached sampled-value DataFrame"
                    )
                else:
                    raise
        if extract_result is not None:
            try:
                extract_result.unpersist_cached()
            except Exception:
                if run_error is not None:
                    logger.exception("[neocarta] failed to unpersist cached extraction DataFrames")
                else:
                    raise
    logger.info("[neocarta] neo4j counts: %s", summary.neo4j_counts)


def _write_nodes(
    neo4j: Neo4jConfig,
    extract_result: ExtractResult,
    values: ValueResult | None,
    summary: RunSummary,
) -> None:
    """Write Database/Schema/Table/Column (and sampled Value) nodes to Neo4j.

    Each frame is projected to its declared per-label property set (the
    fail-closed write boundary) and MERGE-written on id. Embeddings are not
    produced here; the `embedding` property is simply absent and added later by
    neocarta enrichment.
    """
    from pyspark.sql.functions import lit

    write_node(_project(extract_result.database_df, NodeLabel.DATABASE), neo4j, NodeLabel.DATABASE)
    write_node(_project(extract_result.schema_node_df, NodeLabel.SCHEMA), neo4j, NodeLabel.SCHEMA)
    write_node(_project(extract_result.table_node_df, NodeLabel.TABLE), neo4j, NodeLabel.TABLE)
    write_node(_project(extract_result.column_node_df, NodeLabel.COLUMN), neo4j, NodeLabel.COLUMN)

    if values is not None and values.value_node_df is not None:
        # Stamp every Value with this run's start so the post-run scoped delete
        # can drop any Value a prior run left behind.
        value_df = values.value_node_df.withColumn("last_run", lit(summary.started_at))
        write_node(_project(value_df, NodeLabel.VALUE), neo4j, NodeLabel.VALUE)


def _stale_value_cleanup(
    driver: Driver,
    settings: SparkIngestSettings,
    schema_list: list[str],
    values: ValueResult,
    summary: RunSummary,
) -> None:
    """Drop prior-run Values, unless a suspicious empty sample makes it unsafe.

    The scoped server-side delete keys on the Value run-stamp: any Value within
    this run's catalogs/schemas whose `last_run` predates the run start was not
    refreshed by the node writes and is stale.

    Safety gate: when the value path found candidate columns but produced zero
    Value nodes, that is more likely a silent sampling failure than a catalog
    with no sampleable values; deleting here would wipe every prior-run Value,
    so the delete is skipped and the failure recorded loudly instead.
    """
    stats = values.sample_stats
    if stats.value_nodes == 0 and stats.candidate_columns > 0:
        msg = (
            f"value path produced 0 Value nodes from"
            f" {stats.candidate_columns} candidate column(s):"
            f" sampling likely failed silently (unreadable schemas or"
            f" cardinality wipeout) rather than no sampleable values;"
            f" stale-Value delete SKIPPED to avoid wiping prior-run Values"
        )
        summary.value_sampling_warning = msg
        logger.warning("[neocarta] %s", msg)
        return

    delete_stale_values(
        driver,
        summary.started_at.isoformat(),
        settings.resolved_catalogs(),
        schema_list,
    )


def _load(
    neo4j: Neo4jConfig,
    settings: SparkIngestSettings,
    extract_result: ExtractResult,
    fk_result: FKDiscoveryResult,
    values: ValueResult | None,
    summary: RunSummary,
) -> None:
    """Write relationships to Neo4j.

    Node writes already ran; this step writes HAS_VALUE (when the value path is
    active), the structural HAS_* edges, and declared REFERENCES. Every
    relationship MERGE-matches nodes the earlier node writes created.
    """
    if values is not None and values.sample_stats.value_nodes > 0:
        logger.info(
            "[neocarta] writing relationships: HAS_VALUE (%d)", values.sample_stats.has_value_edges
        )
        write_rel(
            _rel_partition(values.has_value_df, settings.rel_write_partitions),
            neo4j,
            RelType.HAS_VALUE,
            NodeLabel.COLUMN,
            NodeLabel.VALUE,
        )

    logger.info("[neocarta] writing relationships: HAS_SCHEMA")
    write_rel(
        _rel_partition(extract_result.has_schema_df, settings.rel_write_partitions),
        neo4j,
        RelType.HAS_SCHEMA,
        NodeLabel.DATABASE,
        NodeLabel.SCHEMA,
    )

    logger.info("[neocarta] writing relationships: HAS_TABLE")
    write_rel(
        _rel_partition(extract_result.has_table_df, settings.rel_write_partitions),
        neo4j,
        RelType.HAS_TABLE,
        NodeLabel.SCHEMA,
        NodeLabel.TABLE,
    )

    logger.info("[neocarta] writing relationships: HAS_COLUMN")
    write_rel(
        _rel_partition(extract_result.has_column_df, settings.rel_write_partitions),
        neo4j,
        RelType.HAS_COLUMN,
        NodeLabel.TABLE,
        NodeLabel.COLUMN,
    )

    if fk_result.declared_edge_count > 0 and fk_result.declared_edges_df is not None:
        logger.info(
            "[neocarta] writing relationships: REFERENCES declared (%d)",
            fk_result.declared_edge_count,
        )
        write_rel(
            _rel_partition(fk_result.declared_edges_df, settings.rel_write_partitions),
            neo4j,
            RelType.REFERENCES,
            NodeLabel.COLUMN,
            NodeLabel.COLUMN,
            source_col="source_column_id",
            target_col="target_column_id",
            properties=REFERENCES_PROPERTIES,
        )


def _project(df: DataFrame, label: NodeLabel) -> DataFrame:
    """Project a node DataFrame to its declared per-label property set.

    This is the fail-closed write boundary: a column reaches Neo4j if and only
    if it is listed in `contract.NODE_PROPERTIES[label]`. `embedding` is the
    only declared column that may be legitimately absent (it is populated later
    by enrichment); the projection selects the intersection. Any other missing
    declared column is a real contract violation and fails loudly.
    """
    declared = NODE_PROPERTIES[label]
    present = set(df.columns)
    missing = [c for c in declared if c != "embedding" and c not in present]
    if missing:
        raise RuntimeError(
            f"[neocarta] {label.value} node DataFrame is missing declared"
            f" properties {missing}; columns present: {sorted(present)}"
        )
    return df.select(*[c for c in declared if c in present])


def _rel_partition(df: DataFrame, n: int) -> DataFrame:
    """Set relationship-write partitioning per `rel_write_partitions`.

    `repartition(1)` is deliberately not the `n <= 1` branch: it forces a
    shuffle and is not equivalent to `coalesce(1)`.
    """
    return df.coalesce(1) if n <= 1 else df.repartition(n)
