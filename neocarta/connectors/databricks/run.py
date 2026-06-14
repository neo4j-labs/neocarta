"""Databricks ingestion orchestrator (schema facts).

Thin coordinator for the schema-ingest run. Its job is limited to:
  1. Construct Settings (fails loudly at boundary via cross-field validators).
  2. Run preflight (fails before any destructive action).
  3. Call extract -> sample values -> write nodes -> declared-FK discovery ->
     write relationships.
  4. Return the in-memory RunSummary.

Embeddings have two modes. External (default): no vectors are produced here and
neocarta's enrichment layer adds them afterward. Inline (when any
`include_embeddings_*` flag is on): the node-write path embeds each batch
in-cluster via ai_query and creates the per-label vector indexes. Inferred
(heuristic) foreign keys live in `neocarta.enrichment.foreign_keys`. This module
ingests catalog facts only.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
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
    create_vector_indexes,
    delete_stale_values,
    query_counts,
    write_node,
    write_rel,
)
from neocarta.connectors.databricks.ingest.preflight import preflight
from neocarta.connectors.databricks.ingest.summary import EmbeddingCounts, RunSummary
from neocarta.connectors.databricks.ingest.transform.embed_stage import (
    embedded_batch,
    finalize_embedding_summary,
)
from neocarta.connectors.databricks.ingest.transform.staging import (
    resolve_ledger_path,
    resolve_transient_root,
)
from neocarta.connectors.databricks.ingest.transform.value_stage import (
    ValueResult,
    transform_sample_values,
)
from neocarta.connectors.databricks.settings import SparkIngestSettings

if TYPE_CHECKING:
    from neo4j import Driver
    from pyspark.sql import DataFrame, SparkSession

logger = logging.getLogger(__name__)


def _inject_cli_params() -> None:
    """Fold ``KEY=VALUE`` argv tokens into ``os.environ`` for the wheel-job path.

    Wheel-job launchers (e.g. a Databricks ``SparkPythonTask``) deliver
    configuration as positional ``KEY=VALUE`` command-line arguments rather than
    environment variables, while ``SparkIngestSettings`` reads only the
    environment. This copies each such token into ``os.environ`` so the
    env-driven settings see it. ``setdefault`` keeps any real environment
    variable ahead of the command line (12-factor precedence); a token that is
    not ``KEY=VALUE``, or that looks like a flag, is left untouched. Off-cluster
    library and notebook runs carry no such tokens, so this is a no-op there.
    """
    for arg in sys.argv[1:]:
        if arg.startswith("-"):
            continue
        key, sep, value = arg.partition("=")
        if sep:
            os.environ.setdefault(key, value)


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

    On the no-argument wheel-job path, ``KEY=VALUE`` command-line tokens are
    folded into ``os.environ`` before settings load, so launchers that deliver
    config as positional args (rather than env vars) are read transparently.
    """
    if settings is not None:
        resolved_settings = settings
    else:
        _inject_cli_params()
        resolved_settings = SparkIngestSettings()

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
    finally:
        # Persist the finished summary (success or failure) so a failed run still
        # leaves an artifact. Best-effort: a write failure is logged, never
        # raised, so it cannot flip a green run red or mask the original error.
        _persist_summary(resolved_settings, summary)
    return summary


def _persist_summary(settings: SparkIngestSettings, summary: RunSummary) -> None:
    """Write the flattened summary to the configured UC Volume, if any.

    No-op when ``summary_volume`` is blank (the default): the summary is still
    returned in memory and the Neo4j counts are still logged. When set, writes
    ``summary_<run_id>.json`` beneath the (durable, never-deleted) Volume path.
    On a Databricks cluster ``/Volumes/...`` is a FUSE-mounted local path, so a
    plain file write reaches the Volume. A write failure is logged, not raised.
    """
    root = settings.summary_volume.strip()
    if not root:
        return
    path = f"{root.rstrip('/')}/summary_{summary.run_id}.json"
    try:
        Path(path).write_text(json.dumps(summary.to_dict(), indent=2), encoding="utf-8")
        logger.info("[neocarta] wrote run summary to %s", path)
    except OSError as exc:
        logger.warning("[neocarta] failed to write run summary to %s: %s", path, exc)


def _build_summary(
    run_id: str, settings: SparkIngestSettings, schema_list: list[str]
) -> RunSummary:
    """Create the run summary shell before any Spark or Neo4j work begins.

    In inline mode the embedding configuration (model, per-batch failure-count
    gate, and per-label flags) is recorded up front so the emitted summary reflects the
    requested config even if no rows are eligible for a label. External mode
    leaves the default empty `EmbeddingCounts` (all-null embedding view).
    """
    embeddings = EmbeddingCounts()
    if settings.any_embeddings_enabled():
        embeddings = EmbeddingCounts(
            model=settings.embedding_endpoint,
            failure_max=settings.embedding_failure_max,
            flags={
                NodeLabel.TABLE: settings.include_embeddings_tables,
                NodeLabel.COLUMN: settings.include_embeddings_columns,
                NodeLabel.SCHEMA: settings.include_embeddings_schemas,
                NodeLabel.DATABASE: settings.include_embeddings_databases,
            },
        )
    return RunSummary(
        run_id=run_id,
        job_name="databricks",
        contract_version=CONTRACT_VERSION,
        catalog=settings.catalog,
        schemas=schema_list,
        embeddings=embeddings,
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
            inline = settings.any_embeddings_enabled()
            if inline:
                _log_embedding_consistency_warning(settings)
                create_vector_indexes(driver, settings)

            extract_result = extract(spark, settings, schema_list, summary)

            # Sample distinct values before writing nodes so the Value frame is
            # ready to write alongside the Column nodes.
            values = transform_sample_values(spark, settings, schema_list, extract_result, summary)

            # Inline mode embeds each batch once and writes through the failure
            # gate; external mode writes the built frames directly (the
            # `embedding` property is simply absent and added later by enrichment).
            if inline:
                _embed_and_write_nodes(spark, neo4j, settings, extract_result, values, summary)
                finalize_embedding_summary(summary)
            else:
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
    write_node(_project(extract_result.database_df, NodeLabel.DATABASE), neo4j, NodeLabel.DATABASE)
    write_node(_project(extract_result.schema_node_df, NodeLabel.SCHEMA), neo4j, NodeLabel.SCHEMA)
    write_node(_project(extract_result.table_node_df, NodeLabel.TABLE), neo4j, NodeLabel.TABLE)
    write_node(_project(extract_result.column_node_df, NodeLabel.COLUMN), neo4j, NodeLabel.COLUMN)
    _write_value_nodes(neo4j, values, summary)


def _write_value_nodes(
    neo4j: Neo4jConfig,
    values: ValueResult | None,
    summary: RunSummary,
) -> None:
    """Write sampled Value nodes (never embedded) with this run's stamp.

    Value nodes are never embedded — no neocarta path embeds them and they are
    reached by HAS_VALUE traversal, not vector search — so both modes write them
    identically here. Every Value is stamped with this run's start so the
    post-run scoped delete can drop any Value a prior run left behind.
    """
    if values is None or values.value_node_df is None:
        return
    from pyspark.sql.functions import lit

    value_df = values.value_node_df.withColumn("last_run", lit(summary.started_at))
    write_node(_project(value_df, NodeLabel.VALUE), neo4j, NodeLabel.VALUE)


def _log_embedding_consistency_warning(settings: SparkIngestSettings) -> None:
    """Warn, on every inline run, about the model/dimension consistency rules.

    The vector index is created at one fixed dimension, so modes cannot be mixed
    on one graph without rebuilding it, and a graph spanning multiple neocarta
    datasources must embed with the same model/dimension as the rest of neocarta
    or cross-source vector search is inconsistent.
    """
    logger.warning(
        "[neocarta] inline embeddings ENABLED: endpoint=%s dimension=%d."
        " The vector index is fixed at this dimension, so external and inline"
        " modes cannot be mixed on one graph without rebuilding it; if this graph"
        " spans multiple neocarta datasources the model and dimension must match"
        " the rest of neocarta or cross-source vector search will be inconsistent.",
        settings.embedding_endpoint,
        settings.embedding_dimension,
    )


def _embed_and_write_nodes(
    spark: SparkSession,
    neo4j: Neo4jConfig,
    settings: SparkIngestSettings,
    extract_result: ExtractResult,
    values: ValueResult | None,
    summary: RunSummary,
) -> None:
    """Inline-mode node writes: embed each batch once, gate, then write.

    Table/Column nodes are batched by table range so no whole-catalog staging
    table is materialized; Database/Schema are catalog/schema-scale and
    embed-and-write once. Each batch freezes its single ai_query pass to a
    transient Delta path (deleted as soon as it is written). A label whose flag
    is off still goes through here but writes directly without embedding; the
    builder-attached `embedding_text` column is projected off in both arms.
    Value nodes are never embedded, so they write through the same un-embedded
    path as external mode.
    """
    transient_root = resolve_transient_root(settings)
    ledger_path = resolve_ledger_path(settings)

    _embed_and_write_node_chunks(
        spark,
        neo4j,
        settings,
        extract_result,
        ledger_path,
        transient_root,
        summary,
    )
    _write_label_nodes(
        extract_result.database_df,
        NodeLabel.DATABASE,
        neo4j,
        settings,
        ledger_path,
        transient_root,
        "all",
        summary,
        settings.include_embeddings_databases,
    )
    _write_label_nodes(
        extract_result.schema_node_df,
        NodeLabel.SCHEMA,
        neo4j,
        settings,
        ledger_path,
        transient_root,
        "all",
        summary,
        settings.include_embeddings_schemas,
    )
    _write_value_nodes(neo4j, values, summary)


def _embed_and_write_node_chunks(
    spark: SparkSession,
    neo4j: Neo4jConfig,
    settings: SparkIngestSettings,
    extract_result: ExtractResult,
    ledger_path: str,
    transient_root: str,
    summary: RunSummary,
) -> None:
    """Embed + write Table and Column nodes batched by table range.

    The bounded list of distinct `(table_catalog, table_schema, table_name)`
    triples is collected to the driver (O(tables) tiny identifiers, not the
    catalog-scale columns) and chunked by `embedding_batch_tables`. Each chunk
    filters the already-built Table/Column node frames on their declared
    `catalog`/`schema`/(table) properties via a broadcast left-semi join, embeds
    once into a transient per-(chunk, label) materialization, gates on the
    per-batch failure count, and writes straight to Neo4j (MERGE on id; a re-run
    heals a partial run). Value nodes are never embedded and are written
    separately by `_write_value_nodes`.
    """
    from pyspark.sql.functions import broadcast

    table_flag = settings.include_embeddings_tables
    column_flag = settings.include_embeddings_columns
    batch_size = settings.embedding_batch_tables

    rows = (
        extract_result.tables_df.select("table_catalog", "table_schema", "table_name")
        .distinct()
        .collect()
    )
    triples = [(r["table_catalog"], r["table_schema"], r["table_name"]) for r in rows]

    def _filter_to_chunk(df: DataFrame, keys: DataFrame, table_col: str) -> DataFrame:
        cond = (
            (df["catalog"] == keys["_k_cat"])
            & (df["schema"] == keys["_k_sch"])
            & (df[table_col] == keys["_k_tab"])
        )
        return df.join(keys, cond, "left_semi")

    for start in range(0, len(triples), batch_size):
        idx = start // batch_size
        chunk = triples[start : start + batch_size]
        tag = f"b{idx}"
        logger.info("[neocarta] embedding batch %s: %d table(s)", tag, len(chunk))
        # Build the broadcast key frame once per chunk and reuse it for the
        # Table/Column/Value semi-joins (createDataFrame is a driver action).
        keys = broadcast(spark.createDataFrame(chunk, ["_k_cat", "_k_sch", "_k_tab"]))
        _write_label_nodes(
            _filter_to_chunk(extract_result.table_node_df, keys, "name"),
            NodeLabel.TABLE,
            neo4j,
            settings,
            ledger_path,
            transient_root,
            tag,
            summary,
            table_flag,
        )
        _write_label_nodes(
            _filter_to_chunk(extract_result.column_node_df, keys, "table"),
            NodeLabel.COLUMN,
            neo4j,
            settings,
            ledger_path,
            transient_root,
            tag,
            summary,
            column_flag,
        )


def _write_label_nodes(
    df: DataFrame,
    label: NodeLabel,
    neo4j: Neo4jConfig,
    settings: SparkIngestSettings,
    ledger_path: str,
    transient_root: str,
    batch_tag: str,
    summary: RunSummary,
    embed_enabled: bool,
) -> None:
    """Write one label's node frame to Neo4j, embedding-once when enabled.

    When `embed_enabled`, the frame is embedded and frozen to a transient
    per-(batch, label) Delta path inside `embedded_batch`: the per-batch
    failure-count gate and this MERGE write both read that single ai_query pass,
    and the transient is deleted as soon as the batch is written. When embedding
    is off the built frame is projected and written directly. `_project` is the
    fail-closed boundary in both arms.
    """
    if embed_enabled:
        with embedded_batch(
            df,
            label,
            settings,
            ledger_path,
            transient_root,
            batch_tag,
            summary,
        ) as staged:
            write_node(_project(staged, label), neo4j, label)
    else:
        write_node(_project(df, label), neo4j, label)


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
