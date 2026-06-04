"""Embedding transform stage.

Owns one primitive: embed a single batch's node frame *once* and freeze it
to a transient Delta materialization, so the per-batch failure-count check
and the Neo4j node write both read the same result and ai_query is invoked
exactly once. There is no whole-catalog staging table and no failure-rate
gate: the run orchestrator drives node embedding + the Neo4j write in
batches by table range, and `embedded_batch` enforces a configurable
per-batch failure *count* before the batch is allowed to be written.

The per-label embedding-text expressions are not here: each node builder
attaches a single `embedding_text` column from the one source of truth
(contract.EMBEDDING_TEXT_EXPR), and this stage simply hashes and embeds it.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

import dbxcarta.spark.ingest.transform.embeddings as emb
from dbxcarta.spark.ingest.transform.ledger import (
    read_ledger,
    split_by_ledger,
    upsert_ledger,
)
from dbxcarta.spark.ingest.transform.staging import (
    delete_transient,
    materialize_transient,
    transient_path,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from dbxcarta.spark.contract import NodeLabel
    from dbxcarta.spark.ingest.summary import RunSummary
    from dbxcarta.spark.settings import SparkIngestSettings
    from pyspark.sql import DataFrame

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def embedded_batch(
    df: DataFrame,
    label: NodeLabel,
    settings: SparkIngestSettings,
    ledger_path: str,
    transient_root: str,
    batch_tag: str,
    summary: RunSummary,
) -> Iterator[DataFrame]:
    """Embed one batch's `df` for `label`, freeze it, and yield the result.

    `df` carries a builder-attached `embedding_text` column; the hash and the
    ai_query input both derive from it, so the ledger never churns from a
    hash/embed mismatch. When DBXCARTA_LEDGER_ENABLED, rows whose
    embedding_text_hash and model already exist in the per-label ledger are
    served from the ledger (no ai_query call); only misses call the endpoint
    and the ledger is then upserted with the new vectors (excluding errors).
    The ledger is keyed by text-hash + model, so a per-batch call already
    scopes the read and the upsert — there is no global ledger read.

    The embedded frame is written to a transient Delta path and read back so
    the caller's Neo4j write and the failure-count check both consume one
    ai_query pass. Per-batch attempts/successes/ledger-hits accumulate into
    `summary`; if this batch's failure count exceeds
    DBXCARTA_EMBEDDING_FAILURE_MAX the run fails *before* the batch is
    yielded (so nothing is written). The transient path is always deleted on
    exit, success or failure, so nothing accumulates across batches.
    """
    enriched = _embed_with_ledger(df, label, settings, ledger_path, summary)
    path = transient_path(transient_root, label, batch_tag)
    staged = materialize_transient(enriched, path)
    try:
        _accumulate_and_gate(staged, label, settings, summary)
        if settings.dbxcarta_ledger_enabled:
            upsert_ledger(staged, ledger_path, label)
        yield staged
    finally:
        delete_transient(path)


def finalize_embedding_summary(summary: RunSummary) -> None:
    """Compute per-label and aggregate failure rates from accumulated counts.

    `embedded_batch` only accumulates raw attempts/successes per label across
    batches (a per-batch rate is meaningless once batching exists). This is
    called once after all embedding is done to fill the derived reporting
    fields the summary/verify wire shape still carries. It is reporting only;
    nothing gates on it (the gate is the per-batch failure count).
    """
    counts = summary.embeddings
    total_attempts = 0
    total_successes = 0
    for label, attempts in counts.attempts.items():
        successes = counts.successes.get(label, 0)
        counts.failure_rate_per_label[label] = (
            (attempts - successes) / attempts if attempts > 0 else 0.0
        )
        total_attempts += attempts
        total_successes += successes
    counts.aggregate_failure_rate = (
        (total_attempts - total_successes) / total_attempts if total_attempts > 0 else 0.0
    )


def _embed_with_ledger(
    df: DataFrame,
    label: NodeLabel,
    settings: SparkIngestSettings,
    ledger_path: str,
    summary: RunSummary,
) -> DataFrame:
    """Return df enriched with embedding columns, using the ledger when on."""
    from pyspark.sql.functions import col, lit, sha2
    from pyspark.sql.types import ArrayType, DoubleType

    endpoint = settings.dbxcarta_embedding_endpoint
    dimension = settings.dbxcarta_embedding_dimension

    if not settings.dbxcarta_ledger_enabled:
        return emb.add_embedding_column(df, endpoint, dimension, label=label.value)

    ledger_df = read_ledger(df.sparkSession, ledger_path, label)
    if ledger_df is None:
        _add_ledger_hits(summary, label, 0)
        return emb.add_embedding_column(df, endpoint, dimension, label=label.value)

    df_hashed = df.withColumn("_curr_hash", sha2(col("embedding_text"), 256))
    hits_df, misses_df = split_by_ledger(df_hashed, ledger_df, endpoint)
    _add_ledger_hits(summary, label, hits_df.count())

    # `embedding_text` is a builder column, so it is in df.columns. The miss
    # branch (add_embedding_column) drops it; exclude it here too so both
    # unionByName arms — and the transient schema — match.
    hit_final = hits_df.select(
        *[col(c) for c in df.columns if c != "embedding_text"],
        col("_curr_hash").alias("embedding_text_hash"),
        col("_led_embedding").cast(ArrayType(DoubleType())).alias("embedding"),
        lit(None).cast("string").alias("embedding_error"),
        col("_led_model").alias("embedding_model"),
        col("_led_embedded_at").alias("embedded_at"),
    )
    embedded_misses = emb.add_embedding_column(
        misses_df,
        endpoint,
        dimension,
        label=label.value,
    )
    return hit_final.unionByName(embedded_misses)


def _accumulate_and_gate(
    staged: DataFrame,
    label: NodeLabel,
    settings: SparkIngestSettings,
    summary: RunSummary,
) -> None:
    """Accumulate this batch's counts and enforce the per-batch failure gate."""
    _, attempts, successes = emb.compute_failure_stats(staged)
    failures = attempts - successes
    counts = summary.embeddings
    counts.attempts[label] = counts.attempts.get(label, 0) + attempts
    counts.successes[label] = counts.successes.get(label, 0) + successes

    logger.info(
        "[dbxcarta] %s batch embeddings: attempts=%d successes=%d failures=%d",
        label.value,
        attempts,
        successes,
        failures,
    )

    cap = settings.dbxcarta_embedding_failure_max
    if cap > 0 and failures > cap:
        raise RuntimeError(
            f"[dbxcarta] {label.value} batch embedding failure count"
            f" {failures} exceeds DBXCARTA_EMBEDDING_FAILURE_MAX {cap};"
            f" aborting before this batch is written to Neo4j"
        )


def _add_ledger_hits(summary: RunSummary, label: NodeLabel, hits: int) -> None:
    counts = summary.embeddings
    counts.ledger_hits[label] = counts.ledger_hits.get(label, 0) + hits
