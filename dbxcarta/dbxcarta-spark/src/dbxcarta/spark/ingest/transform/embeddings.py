"""Transform: add embedding columns to a node DataFrame via ai_query()."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dbxcarta.core.identifiers import validate_serving_endpoint_name

if TYPE_CHECKING:
    from pyspark.sql import Column, DataFrame


def _validate_embedding(raw_col: Column, expected_dim: int) -> tuple[Column, Column]:
    """Return (embedding, embedding_error) for an ai_query _emb_raw struct column.

    Precedence: endpoint error wins. If raw_col.errorMessage is non-null the
    embedding is nulled and error = errorMessage. Only when errorMessage is
    null do we check the vector length; a mismatch produces a
    "dimension mismatch: got N, expected M" reason. Success yields the raw
    result vector and a null error.
    """
    from pyspark.sql.functions import concat, lit, size, when

    result = raw_col.getField("result")
    err = raw_col.getField("errorMessage")

    embedding = when(err.isNotNull(), lit(None)).otherwise(
        when(size(result) == expected_dim, result)
    )
    error = when(err.isNotNull(), err).otherwise(
        when(
            size(result) != expected_dim,
            concat(
                lit("dimension mismatch: got "),
                size(result).cast("string"),
                lit(f", expected {expected_dim}"),
            ),
        )
    )
    return embedding, error


def add_embedding_column(
    df: DataFrame,
    endpoint: str,
    expected_dimension: int,
    *,
    label: str,
) -> DataFrame:
    """Append embedding_text_hash, embedding, embedding_error,
    embedding_model, embedded_at to df, then drop the input embedding_text.

    `df` must already carry an `embedding_text` column produced by its node
    builder (the single source of truth is contract.EMBEDDING_TEXT_EXPR).
    This function no longer evaluates a per-label SQL string.

    embedding_text_hash is sha256 hex of embedding_text and is always stored
    (even on failed rows) so post-mortem can correlate failures by hash.
    embedding is nulled when ai_query() returns an errorMessage (endpoint
    failure) or the returned vector length does not match expected_dimension
    (shape failure) — both count as failures in compute_failure_stats().
    embedding_error carries the reason: endpoint-wins precedence.
    embedding_text is dropped before returning; the hash alone is sufficient
    for drift detection and keeps the Delta staging schema stable.
    embedding_text_hash / embedding_model / embedded_at / embedding_error
    live only in the Delta staging table, the ledger, and the run summary —
    the fail-closed write boundary projects them off the graph.
    """
    # Guard before interpolation: ai_query requires the endpoint as a string
    # literal. validate_serving_endpoint_name rejects characters that would
    # break the SQL expression.
    validate_serving_endpoint_name(endpoint, label="embedding endpoint")

    from pyspark.sql.functions import col, current_timestamp, expr, lit, sha2

    raw = expr(f"ai_query('{endpoint}', embedding_text, failOnError => false)")
    embedding_col, error_col = _validate_embedding(col("_emb_raw"), expected_dimension)

    return (
        df.withColumn("embedding_text_hash", sha2(col("embedding_text"), 256))
        .withColumn("_emb_raw", raw)
        .withColumn("embedding", embedding_col)
        .withColumn("embedding_error", error_col)
        .withColumn("embedding_model", lit(endpoint))
        .withColumn("embedded_at", current_timestamp())
        .drop("_emb_raw")
        .drop("embedding_text")
    )


def compute_failure_stats(df: DataFrame) -> tuple[float, int, int]:
    """Return (failure_rate, attempts, successes). Triggers a Spark action.

    Expects df to contain an 'embedding' column produced by add_embedding_column().
    A null embedding (from ai_query failure or dimension mismatch) counts as a failure.
    """
    from pyspark.sql.functions import col, count

    row = df.agg(
        count("*").alias("attempts"),
        count(col("embedding")).alias("successes"),
    ).collect()[0]
    attempts = int(row["attempts"])
    successes = int(row["successes"])
    rate = (attempts - successes) / attempts if attempts > 0 else 0.0
    return rate, attempts, successes
