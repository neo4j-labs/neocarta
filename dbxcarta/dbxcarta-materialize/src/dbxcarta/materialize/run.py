"""Materialize orchestrator: run the blueprint as a serverless Spark job.

Thin coordinator. Its job is limited to:
  1. Construct Settings (fails loudly at the env-var boundary).
  2. Read the staged blueprint from the ops Volume.
  3. Ask core for the statements, run them with ``spark.sql``, overlapping the
     independent table creates in a bounded pool and running the foreign-key
     pass serially after.
  4. Emit the MaterializeRunSummary, recording progress per schema so a
     mid-run failure still reports what actually landed.

Core (:mod:`dbxcarta.core.materialize`) builds every statement and stays pure;
this module owns the ``SparkSession``, the thread pool, and the skip-on-error
tally. The only pool runs over ``SparkSession``, a thread-safe type, so there is
no thread-safety contract on an opaque callable.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dbxcarta.core.env import read_materialize_workers
from dbxcarta.core.identifiers import quote_identifier
from dbxcarta.core.materialize import (
    MaterializedTable,
    MaterializeStats,
    TableBuild,
    build_create_schema_statement,
    build_foreign_key_statements,
    build_table,
    read_schema_entry,
)
from dbxcarta.core.volume_io import load_json_file
from dbxcarta.materialize.settings import MaterializeSettings
from dbxcarta.materialize.summary import JOB_NAME, MaterializeRunSummary
from py4j.protocol import Py4JJavaError  # type: ignore[import-untyped]
from pyspark.errors import PySparkException

if TYPE_CHECKING:
    from pyspark.sql import SparkSession

logger = logging.getLogger(__name__)

# The shared product step uses one constant property prefix. The
# ``<prefix>.source_id`` table properties are informational metadata that nothing
# in the pipeline reads back, so a single prefix replaces the former per-example
# "dense"/"schemapile" values without affecting ingest.
PROPERTY_PREFIX = "dbxcarta"

# A SQL statement that fails on the cluster raises a PySparkException
# (AnalysisException, ParseException, ...) or a raw JVM Py4JJavaError. Those are
# the "bad SQL / warehouse" failures the run tolerates: skip the table, row, or
# foreign key and continue, so one bad table never aborts a large run. Any OTHER
# exception is a programming bug and propagates unchanged, so a real defect is
# never masked as a tolerated skip.
_SQL_ERRORS = (PySparkException, Py4JJavaError)

# A runner that executes one statement and raises on failure. The entrypoint
# binds it to ``spark.sql``; tests inject a recorder. The label is for logging.
RunSql = Callable[[str, str], None]


def run_materialize(
    *,
    settings: MaterializeSettings | None = None,
    spark: SparkSession | None = None,
) -> MaterializeRunSummary:
    """Run a complete materialize and return the finished summary.

    With no arguments this is the Databricks wheel entrypoint: settings load from
    the environment and the active Spark session resolves lazily. The data
    catalog is assumed to exist (``dbxcarta-submit bootstrap`` creates it).

    Schemas are processed one at a time and the summary is updated after each, so
    a failure partway through still records the schemas and tally that actually
    landed rather than zeros.
    """
    resolved = settings if settings is not None else MaterializeSettings()
    if spark is None:
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.getOrCreate()
    run_id = os.environ.get("DATABRICKS_JOB_RUN_ID", "local")

    def run_sql(statement: str, _label: str) -> None:
        # Discard the DataFrame spark.sql returns: DDL/INSERT run eagerly, and
        # RunSql is a None-returning runner.
        spark.sql(statement)

    summary = MaterializeRunSummary(
        run_id=run_id,
        job_name=JOB_NAME,
        catalog=resolved.dbxcarta_catalog,
        schemas=[],
    )
    primary_error: BaseException | None = None
    try:
        schemas = _load_blueprint_schemas(resolved.dbxcarta_blueprint_volume)
        if not schemas:
            raise ValueError(f"blueprint at {resolved.dbxcarta_blueprint_volume} has no schemas")
        workers = read_materialize_workers()
        logger.info("[dbxcarta_materialize] workers=%d", workers)
        catalog_q = quote_identifier(resolved.dbxcarta_catalog)
        run_stats = MaterializeStats()
        for entry in schemas:
            uc_schema, schema_stats = materialize_schema(
                entry, catalog_q=catalog_q, run_sql=run_sql, workers=workers, log=logger
            )
            # Record after each schema completes, so a later failure leaves the
            # summary reflecting what actually materialized, not the planned set.
            run_stats = run_stats + schema_stats
            summary.schemas.append(uc_schema)
            summary.apply_stats(run_stats)
        summary.finish(status="success")
    except Exception as exc:
        primary_error = exc
        # Top-level catch-all is deliberate: record _any_ failure into the
        # summary (stdout + JSON + Delta) before re-raising so the Databricks
        # job still fails. The stats/schemas accumulated above are preserved.
        summary.finish(status="failure", error=str(exc))
        raise
    finally:
        _emit_summary(
            summary,
            spark,
            resolved.dbxcarta_summary_volume,
            resolved.dbxcarta_summary_table,
            primary_error=primary_error,
        )
    return summary


def _load_blueprint_schemas(blueprint_volume: str) -> list[dict[str, Any]]:
    """Read the staged blueprint JSON from the ops Volume and return its schemas.

    The blueprint is a FUSE-mounted ``/Volumes/...`` path the submit step staged;
    reading it with ``Path.read_text`` is a plain file read on the driver.
    """
    payload = load_json_file(Path(blueprint_volume), label="blueprint")
    return payload.get("schemas") or []


def materialize_blueprint(
    schemas: list[dict[str, Any]],
    *,
    catalog: str,
    run_sql: RunSql,
    workers: int = 1,
    log: logging.Logger | None = None,
) -> MaterializeStats:
    """Run every schema in the blueprint and return the summed tally.

    A convenience wrapper over :func:`materialize_schema` for callers that want
    the whole blueprint as one call; ``run_materialize`` instead drives the loop
    itself so it can record progress per schema.
    """
    log = log or logger
    catalog_q = quote_identifier(catalog)
    stats = MaterializeStats()
    for entry in schemas:
        _uc_schema, schema_stats = materialize_schema(
            entry, catalog_q=catalog_q, run_sql=run_sql, workers=workers, log=log
        )
        stats = stats + schema_stats
    return stats


def materialize_schema(
    entry: dict[str, Any],
    *,
    catalog_q: str,
    run_sql: RunSql,
    workers: int,
    log: logging.Logger,
) -> tuple[str, MaterializeStats]:
    """Materialize one schema entry and return ``(uc_schema, its tally)``.

    Creates the schema, builds every table's statements (pure, via core) and runs
    them — the independent table creates overlap in a bounded pool of ``workers``
    threads over ``spark.sql`` — then adds foreign keys in a serial second pass
    once every table exists. A failed table create or row insert is skipped
    (logged) so one bad table never aborts the run; the foreign-key adds are
    likewise tolerant. The CREATE SCHEMA is not tolerated: a schema that cannot
    be created raises, since none of its tables could land anyway.
    """
    uc_schema, source_id = read_schema_entry(entry)
    schema_q = quote_identifier(uc_schema)
    log.info("creating schema %s", uc_schema)
    create_schema_sql, label = build_create_schema_statement(
        catalog_q, uc_schema, source_id, property_prefix=PROPERTY_PREFIX
    )
    run_sql(create_schema_sql, label)
    stats = MaterializeStats(schemas_created=1)

    tables = entry.get("tables", [])
    total = len(tables)
    # Pair each build with its rendered progress tag up front, so the worker
    # below closes over no loop variable.
    indexed: list[tuple[str, TableBuild]] = [
        (
            f"{idx}/{total}",
            build_table(
                table,
                catalog_q=catalog_q,
                schema_q=schema_q,
                source_id=source_id,
                property_prefix=PROPERTY_PREFIX,
            ),
        )
        for idx, table in enumerate(tables, 1)
    ]

    # Run the independent table builds, pooled when workers > 1. Each build
    # returns (record_or_None, runtime_stats); results are collected and summed
    # after the pool drains, so no MaterializeStats is shared across threads. The
    # pool runs over spark.sql (thread-safe), not an opaque injected callable.
    def _run(
        item: tuple[str, TableBuild],
    ) -> tuple[MaterializedTable | None, MaterializeStats]:
        progress, build = item
        return _execute_build(build, run_sql, log, progress=progress)

    if workers > 1 and len(indexed) > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_run, indexed))
    else:
        results = [_run(item) for item in indexed]

    materialized: dict[str, MaterializedTable] = {}
    for record, local in results:
        stats = stats + local
        if record is not None:
            materialized[record.safe_name] = record

    # Second pass: foreign keys, only after every table exists.
    for fk_sql, fk_label in build_foreign_key_statements(
        materialized, catalog_q=catalog_q, schema_q=schema_q
    ):
        try:
            run_sql(fk_sql, fk_label)
            stats = stats + MaterializeStats(fk_constraints_added=1)
        except _SQL_ERRORS as exc:
            log.warning("add foreign key failed (%s): %s", fk_label, exc)

    return uc_schema, stats


def _execute_build(
    build: TableBuild,
    run_sql: RunSql,
    log: logging.Logger,
    *,
    progress: str,
) -> tuple[MaterializedTable | None, MaterializeStats]:
    """Run one table's plan and return ``(record_or_None, this table's stats)``.

    A build-time skip (``plan is None``) contributes its ``tables_skipped`` tally
    and no statements. A tolerated ``CREATE`` failure contributes nothing and is
    not registered for the foreign-key pass, so one bad table never aborts the
    run. On success the table is counted (with its primary key, if inline) and
    its rows inserted; a tolerated insert failure keeps the table without rows.
    Only SQL-execution failures (:data:`_SQL_ERRORS`) are tolerated; any other
    exception propagates so a programming bug is never masked as a skip.
    """
    if build.plan is None:
        return None, build.stats
    plan = build.plan
    log.info("table %s %s", progress, plan.create_label)
    try:
        run_sql(plan.create_sql, plan.create_label)
    except _SQL_ERRORS as exc:
        log.warning("table create failed (%s): %s", plan.create_label, exc)
        return None, MaterializeStats()

    stats = build.stats + MaterializeStats(tables_created=1)
    if plan.has_primary_key:
        stats = stats + MaterializeStats(pk_constraints_added=1)

    if plan.insert_sql is not None and plan.insert_label is not None:
        try:
            run_sql(plan.insert_sql, plan.insert_label)
            stats = stats + MaterializeStats(rows_inserted=plan.row_count)
        except _SQL_ERRORS as exc:
            log.warning("insert failed (%s): %s", plan.insert_label, exc)

    return plan.record, stats


def _emit_summary(
    summary: MaterializeRunSummary,
    spark: SparkSession,
    volume_path: str,
    table_name: str,
    *,
    primary_error: BaseException | None,
) -> None:
    """Emit the summary without masking an existing run failure."""
    try:
        summary.emit(spark, volume_path, table_name)
    except Exception:
        if primary_error is not None:
            logger.exception("[dbxcarta_materialize] failed to emit run summary after failure")
            return
        raise
