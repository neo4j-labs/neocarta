"""DBxCarta ingestion orchestrator.

Thin coordinator for the ingest run. Its job is limited to:
  1. Construct Settings (fails loudly at boundary via cross-field validators).
  2. Run preflight (fails before any destructive action).
  3. Call extract → transform (embed, sample) → FK discovery → load.
  4. Emit the RunSummary.

The module intentionally keeps domain work in focused ingest modules under
`fk`, `transform`, and `load`. Pipeline functions here wire those modules
together and update run-level counters so the Databricks task has one clear
entry point.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from dbxcarta.spark.contract import (
    CONTRACT_VERSION,
    NODE_PROPERTIES,
    REFERENCES_PROPERTIES,
    NodeLabel,
    RelType,
)
from dbxcarta.spark.ingest import summary_io
from dbxcarta.spark.ingest.extract import ExtractResult, extract
from dbxcarta.spark.ingest.fk.discovery import (
    FKDiscoveryResult,
    run_fk_discovery,
)
from dbxcarta.spark.ingest.load.neo4j_io import (
    bootstrap_constraints,
    delete_stale_values,
    query_counts,
    write_node,
    write_rel,
)
from dbxcarta.spark.ingest.load.writer import Neo4jConfig
from dbxcarta.spark.ingest.preflight import preflight
from dbxcarta.spark.ingest.summary import EmbeddingCounts, RunSummary
from dbxcarta.spark.ingest.transform.embed_stage import (
    embedded_batch,
    finalize_embedding_summary,
)
from dbxcarta.spark.ingest.transform.staging import (
    resolve_ledger_path,
    resolve_transient_root,
)
from dbxcarta.spark.ingest.transform.value_stage import (
    ValueResult,
    transform_sample_values,
)
from dbxcarta.spark.settings import SparkIngestSettings

if TYPE_CHECKING:
    from neo4j import Driver
    from pyspark.sql import DataFrame, SparkSession

logger = logging.getLogger(__name__)


def run_dbxcarta(
    *,
    settings: SparkIngestSettings | None = None,
    spark: SparkSession | None = None,
) -> RunSummary:
    """Run a complete ingest and return the finished RunSummary.

    When called with no arguments, this is the Databricks wheel entrypoint:
    settings are loaded from environment variables and the active Spark session
    is resolved lazily. Library consumers can pass an explicit SparkIngestSettings.
    """
    resolved_settings = settings if settings is not None else SparkIngestSettings()

    if spark is None:
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.getOrCreate()
    run_id = os.environ.get("DATABRICKS_JOB_RUN_ID", "local")
    schema_list = [s.strip() for s in resolved_settings.dbxcarta_schemas.split(",") if s.strip()]

    summary = _build_summary(run_id, resolved_settings, schema_list)
    primary_error: BaseException | None = None

    try:
        _run(spark, resolved_settings, schema_list, summary)
        summary.finish(status="success")
    except Exception as exc:
        primary_error = exc
        # Top-level catch-all is deliberate: the purpose here is to record
        # _any_ failure into RunSummary.error (stdout + JSON + Delta) before
        # re-raising. Narrowing would silently lose novel failure modes. The
        # exception propagates via `raise` so the Databricks job still fails.
        summary.finish(status="failure", error=str(exc))
        raise
    finally:
        _emit_summary(
            summary,
            spark,
            resolved_settings.dbxcarta_summary_volume,
            resolved_settings.dbxcarta_summary_table,
            primary_error=primary_error,
        )
    return summary


def _build_summary(
    run_id: str, settings: SparkIngestSettings, schema_list: list[str]
) -> RunSummary:
    """Create the run summary shell before any Spark or Neo4j work begins.

    Embedding flags are copied from Settings at startup so the emitted summary
    records the requested configuration even if no rows are eligible for a
    particular label.
    """
    flags: dict[NodeLabel, bool] = {
        NodeLabel.TABLE: settings.dbxcarta_include_embeddings_tables,
        NodeLabel.COLUMN: settings.dbxcarta_include_embeddings_columns,
        NodeLabel.VALUE: settings.dbxcarta_include_embeddings_values,
        NodeLabel.SCHEMA: settings.dbxcarta_include_embeddings_schemas,
        NodeLabel.DATABASE: settings.dbxcarta_include_embeddings_databases,
    }
    return RunSummary(
        run_id=run_id,
        job_name="dbxcarta",
        contract_version=CONTRACT_VERSION,
        catalog=settings.dbxcarta_catalog,
        schemas=schema_list,
        embeddings=EmbeddingCounts(
            model=settings.dbxcarta_embedding_endpoint,
            failure_threshold=settings.dbxcarta_embedding_failure_max,
            flags=flags,
        ),
    )


def _emit_summary(
    summary: RunSummary,
    spark: SparkSession,
    volume_path: str,
    table_name: str,
    *,
    primary_error: BaseException | None,
) -> None:
    """Emit the summary without masking an existing run failure."""
    try:
        summary_io.emit(summary, spark, volume_path, table_name)
    except Exception:
        if primary_error is not None:
            logger.exception("[dbxcarta] failed to emit run summary after run failure")
            return
        raise


def _run(
    spark: SparkSession,
    settings: SparkIngestSettings,
    schema_list: list[str],
    summary: RunSummary,
) -> None:
    """Execute the ingest workflow after settings and summary are initialized.

    This method owns resource ordering: preflight and transient/ledger path
    resolution happen before the Neo4j driver opens, graph constraints are
    bootstrapped before writes, node embedding + node writes are batched by
    table range (each batch's transient materialization deleted as soon as it
    is written), and cached extraction DataFrames are unpersisted after
    verification.
    """
    from databricks.sdk.runtime import dbutils
    from neo4j import GraphDatabase

    extract_result: ExtractResult | None = None
    values: ValueResult | None = None
    fk_result: FKDiscoveryResult | None = None
    scope = settings.databricks_secret_scope
    neo4j = Neo4jConfig(
        uri=dbutils.secrets.get(scope=scope, key="NEO4J_URI"),
        username=dbutils.secrets.get(scope=scope, key="NEO4J_USERNAME"),
        password=dbutils.secrets.get(scope=scope, key="NEO4J_PASSWORD"),
        batch_size=settings.dbxcarta_neo4j_batch_size,
    )

    preflight(spark, settings)
    transient_root = resolve_transient_root(settings)
    ledger_path = resolve_ledger_path(settings)

    run_error: BaseException | None = None
    try:
        with GraphDatabase.driver(neo4j.uri, auth=(neo4j.username, neo4j.password)) as driver:
            bootstrap_constraints(driver, settings)

            extract_result = extract(spark, settings, schema_list, summary)

            # Sample distinct values BEFORE the chunk loop so each Value
            # slice can embed+write alongside its Column slice in the same
            # batched pass. Sampling-only now: no Neo4j write or stale purge
            # happens here.
            values = transform_sample_values(
                spark,
                settings,
                schema_list,
                extract_result,
                summary,
            )

            # Node embedding + node writes are batched by table range here;
            # the per-chunk Value slice rides along when the value path is
            # active. Relationship writes stay in _load and run after FK
            # discovery, MERGE-matching the nodes this loop already wrote.
            _embed_and_write_node_chunks(
                spark,
                neo4j,
                settings,
                extract_result,
                ledger_path,
                transient_root,
                summary,
                values.value_node_df if values else None,
            )
            # Schema/Database are per-schema / per-catalog scale, not
            # table-scale: embed (if enabled) and write once, outside the loop.
            _write_label_nodes(
                extract_result.database_df,
                NodeLabel.DATABASE,
                neo4j,
                settings,
                ledger_path,
                transient_root,
                "all",
                summary,
                settings.dbxcarta_include_embeddings_databases,
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
                settings.dbxcarta_include_embeddings_schemas,
            )

            # Scoped stale-Value cleanup: one server-side delete after every
            # Value slice for this run has been written. Runs on every
            # value-path run (not only when this run sampled something) so a
            # run whose columns vanished still drops their Values. Replaces
            # the old driver-collected `IN $col_ids` purge (best-practices
            # §5).
            if values is not None:
                _stale_value_cleanup(
                    driver,
                    settings,
                    schema_list,
                    values,
                    summary,
                )

            # Per-batch counts accumulated across every chunk and the
            # value stage; fill the derived reporting rates once here (the
            # slot the removed check_thresholds gate used to occupy).
            finalize_embedding_summary(summary)

            fk_result = run_fk_discovery(
                spark,
                settings,
                schema_list,
                extract_result,
                summary,
            )

            _load(neo4j, settings, extract_result, fk_result, values, summary)
            summary.neo4j_counts = query_counts(driver)
            _verify(driver, settings, summary)
    except Exception as exc:
        run_error = exc
        raise
    finally:
        # Release cached snapshots after run_fk_discovery and _load have
        # finished reading them. Each release is guarded independently so a
        # failure in one still attempts the others; on the success path a
        # release failure is re-raised, on the failure path it is logged so it
        # does not mask the original error.
        if fk_result is not None:
            try:
                fk_result.unpersist_cached()
            except Exception:
                if run_error is not None:
                    logger.exception("[dbxcarta] failed to unpersist cached FK edge DataFrames")
                else:
                    raise
        if values is not None:
            try:
                values.unpersist_cached()
            except Exception:
                if run_error is not None:
                    logger.exception(
                        "[dbxcarta] failed to unpersist cached sampled-value DataFrame"
                    )
                else:
                    raise
        if extract_result is not None:
            try:
                extract_result.unpersist_cached()
            except Exception:
                if run_error is not None:
                    logger.exception("[dbxcarta] failed to unpersist cached extraction DataFrames")
                else:
                    raise
    logger.info("[dbxcarta] neo4j counts: %s", summary.neo4j_counts)


def _stale_value_cleanup(
    driver: Driver,
    settings: SparkIngestSettings,
    schema_list: list[str],
    values: ValueResult,
    summary: RunSummary,
) -> None:
    """Drop prior-run Values, unless a suspicious empty sample makes the
    delete unsafe.

    The scoped server-side delete keys on the contract-1.3 Value run-stamp:
    any Value within this run's catalogs/schemas whose `last_run` predates
    the run start was not refreshed by the per-chunk writes and is stale.

    Safety gate (review #6): when the value path ran and found candidate
    columns but produced zero Value nodes, that is far more likely a silent
    sampling failure (unreadable schemas, cardinality wipeout) than a
    catalog with genuinely no sampleable values. Deleting here would wipe
    every prior-run Value because *this* run wrote none — so the delete is
    skipped entirely and the failure recorded loudly instead. No run
    failure and no new setting: a healthy next run heals the staleness.
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
        logger.warning("[dbxcarta] %s", msg)
        return

    delete_stale_values(
        driver,
        summary.started_at.isoformat(),
        settings.resolved_catalogs(),
        schema_list,
    )


def _verify(driver: Driver, settings: SparkIngestSettings, summary: RunSummary) -> None:
    """Final pipeline step: re-run dbxcarta.spark.verify against the run summary just
    built. Records the outcome on summary.verify (durable in JSON + Delta).
    Warn-only by default; raises when settings.dbxcarta_verify_gate is True.

    The summary dict is materialised here with status forced to 'success' — the
    enclosing run_dbxcarta() has not yet called summary.finish(), but verify's
    summary-shape check expects a successful run. If we raise, the outer
    catch-all in run_dbxcarta() records the failure via summary.finish(failure).
    """
    from databricks.sdk import WorkspaceClient
    from dbxcarta.spark.ingest.summary import VerifyResult
    from dbxcarta.spark.verify import verify_run

    summary_dict = summary.to_dict()
    summary_dict["status"] = "success"
    ws = WorkspaceClient()
    report = verify_run(
        summary=summary_dict,
        neo4j_driver=driver,
        ws=ws,
        warehouse_id=settings.databricks_warehouse_id,
        # The count invariants (graph node counts, REFERENCES, Value) scope to
        # every resolved catalog so a multi-catalog run is checked against its
        # aggregate summary totals. `catalog` remains the single primary for
        # the deferred information_schema sampling in verify.catalog (tracked
        # in SparkIngestSettings.dbxcarta_catalogs as part-2).
        catalog=settings.dbxcarta_catalog,
        catalogs=settings.resolved_catalogs(),
        sample_limit=settings.dbxcarta_sample_limit,
    )
    summary.verify = VerifyResult(
        ok=report.ok,
        violations=[{"code": v.code, "message": v.message} for v in report.violations],
    )
    if report.ok:
        logger.info("[dbxcarta] verify: OK (0 violations)")
        return
    if settings.dbxcarta_verify_gate:
        raise RuntimeError(
            f"[dbxcarta] verify gate failed: {len(report.violations)} violation(s)\n"
            + report.format()
        )
    logger.warning(
        "[dbxcarta] verify reported %d violation(s) (warn-only; set"
        " DBXCARTA_VERIFY_GATE=true to gate):\n%s",
        len(report.violations),
        report.format(),
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
    failure-count gate and this MERGE write both read that single ai_query
    pass, and the transient is deleted as soon as the batch is written. When
    embedding is off, the built frame is projected and written directly.
    `_project` is the fail-closed boundary in both arms.
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


def _embed_and_write_node_chunks(
    spark: SparkSession,
    neo4j: Neo4jConfig,
    settings: SparkIngestSettings,
    extract_result: ExtractResult,
    ledger_path: str,
    transient_root: str,
    summary: RunSummary,
    value_node_df: DataFrame | None = None,
) -> None:
    """Embed + write Table, Column, and Value nodes batched by table range.

    The bounded list of distinct `(table_catalog, table_schema, table_name)`
    triples is collected to the driver (O(tables) tiny identifiers, not the
    catalog-scale columns/values §5 forbids) and chunked by
    `dbxcarta_embedding_batch_tables`. Each chunk filters the already-built
    Table/Column/Value node frames on their now-declared
    `catalog`/`schema`/(table) properties via a broadcast left-semi join,
    embeds once into a transient per-(chunk, label) materialization, gates on
    the per-batch failure count, and writes straight to Neo4j (MERGE on id; a
    re-run heals a partial run).

    `value_node_df` (the un-embedded sampled Value frame, or None when the
    value path is off) is sliced to the same table range and written here so
    each Value slice embeds alongside its Column slice rather than in a
    separate global pass. Every Value row is stamped with `last_run` =
    `summary.started_at` so the post-loop scoped delete can drop any Value a
    prior run left behind. The slice goes through `_write_label_nodes`
    unconditionally: an empty per-chunk slice is a harmless no-op write, and
    the post-loop delete is what reconciles vanished columns.
    """
    from pyspark.sql.functions import broadcast, lit

    table_flag = settings.dbxcarta_include_embeddings_tables
    column_flag = settings.dbxcarta_include_embeddings_columns
    batch_size = settings.dbxcarta_embedding_batch_tables

    rows = (
        extract_result.tables_df.select("table_catalog", "table_schema", "table_name")
        .distinct()
        .collect()
    )
    triples = [(r["table_catalog"], r["table_schema"], r["table_name"]) for r in rows]

    def _filter_to_chunk(
        df: DataFrame,
        keys: DataFrame,
        table_col: str,
    ) -> DataFrame:
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
        logger.info(
            "[dbxcarta] embedding batch %s: %d table(s)",
            tag,
            len(chunk),
        )
        # Build the broadcast key frame once per chunk and reuse it for the
        # Table/Column/Value semi-joins. createDataFrame is a driver action;
        # building it once per chunk (not once per label) avoids three
        # identical tiny frames per batch.
        keys = broadcast(
            spark.createDataFrame(chunk, ["_k_cat", "_k_sch", "_k_tab"]),
        )
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
        if value_node_df is not None:
            value_slice = _filter_to_chunk(
                value_node_df,
                keys,
                "table",
            ).withColumn("last_run", lit(summary.started_at))
            _write_label_nodes(
                value_slice,
                NodeLabel.VALUE,
                neo4j,
                settings,
                ledger_path,
                transient_root,
                tag,
                summary,
                settings.dbxcarta_include_embeddings_values,
            )


def _load(
    neo4j: Neo4jConfig,
    settings: SparkIngestSettings,
    extract_result: ExtractResult,
    fk_result: FKDiscoveryResult,
    values: ValueResult | None,
    summary: RunSummary,
) -> None:
    """Write inferred and sampled *relationships* to Neo4j.

    Node writes (Database/Schema/Table/Column batched, Value in the value
    stage) already ran before FK discovery; this step only writes
    relationships. Relationship writes are partitioned by `_rel_partition`
    per `dbxcarta_rel_write_partitions`: the default of 1 coalesces to a
    single partition (byte-for-byte identical to the historical write, the
    safe default for Neo4j lock contention); a higher value repartitions
    for tuned parallel relationship writes. Every relationship MERGE-matches
    nodes the earlier node writes already created.
    """
    if values is not None and values.sample_stats.value_nodes > 0:
        logger.info(
            "[dbxcarta] writing relationships: HAS_VALUE (%d)", values.sample_stats.has_value_edges
        )
        write_rel(
            _rel_partition(values.has_value_df, settings.dbxcarta_rel_write_partitions),
            neo4j,
            RelType.HAS_VALUE,
            NodeLabel.COLUMN,
            NodeLabel.VALUE,
        )

    logger.info("[dbxcarta] writing relationships: HAS_SCHEMA")
    write_rel(
        _rel_partition(extract_result.has_schema_df, settings.dbxcarta_rel_write_partitions),
        neo4j,
        RelType.HAS_SCHEMA,
        NodeLabel.DATABASE,
        NodeLabel.SCHEMA,
    )

    logger.info("[dbxcarta] writing relationships: HAS_TABLE")
    write_rel(
        _rel_partition(extract_result.has_table_df, settings.dbxcarta_rel_write_partitions),
        neo4j,
        RelType.HAS_TABLE,
        NodeLabel.SCHEMA,
        NodeLabel.TABLE,
    )

    logger.info("[dbxcarta] writing relationships: HAS_COLUMN")
    write_rel(
        _rel_partition(extract_result.has_column_df, settings.dbxcarta_rel_write_partitions),
        neo4j,
        RelType.HAS_COLUMN,
        NodeLabel.TABLE,
        NodeLabel.COLUMN,
    )

    if fk_result.declared_edge_count > 0 and fk_result.declared_edges_df is not None:
        logger.info(
            "[dbxcarta] writing relationships: REFERENCES declared (%d)",
            fk_result.declared_edge_count,
        )
        write_rel(
            _rel_partition(fk_result.declared_edges_df, settings.dbxcarta_rel_write_partitions),
            neo4j,
            RelType.REFERENCES,
            NodeLabel.COLUMN,
            NodeLabel.COLUMN,
            properties=REFERENCES_PROPERTIES,
        )

    if fk_result.metadata_edge_count > 0 and fk_result.metadata_edges_df is not None:
        logger.info(
            "[dbxcarta] writing relationships: REFERENCES inferred_metadata (%d)",
            fk_result.metadata_edge_count,
        )
        write_rel(
            _rel_partition(fk_result.metadata_edges_df, settings.dbxcarta_rel_write_partitions),
            neo4j,
            RelType.REFERENCES,
            NodeLabel.COLUMN,
            NodeLabel.COLUMN,
            properties=REFERENCES_PROPERTIES,
        )


def _project(df: DataFrame, label: NodeLabel) -> DataFrame:
    """Project a node DataFrame to its declared per-label property set.

    This is the fail-closed write boundary: a column reaches Neo4j if and
    only if it is listed in `contract.NODE_PROPERTIES[label]`. Helper
    columns and embedding bookkeeping (`embedding_text`,
    `embedding_text_hash`, `embedding_model`, `embedded_at`,
    `embedding_error`) are dropped by construction because they are not
    declared — no hand-maintained denylist.

    `embedding` is the only declared column that may be legitimately absent
    (present only when the label was embedded this run); the projection
    selects the intersection. Any other missing declared column is a real
    contract violation and fails loudly rather than being silently skipped.
    """
    declared = NODE_PROPERTIES[label]
    present = set(df.columns)
    missing = [c for c in declared if c != "embedding" and c not in present]
    if missing:
        raise RuntimeError(
            f"[dbxcarta] {label.value} node DataFrame is missing declared"
            f" properties {missing}; columns present: {sorted(present)}"
        )
    return df.select(*[c for c in declared if c in present])


def _rel_partition(df: DataFrame, n: int) -> DataFrame:
    """Set relationship-write partitioning per `dbxcarta_rel_write_partitions`.

    `repartition(1)` is deliberately not the `n <= 1` branch: it forces a
    shuffle and is not equivalent to `coalesce(1)`.
    """
    return df.coalesce(1) if n <= 1 else df.repartition(n)
