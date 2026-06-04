"""Re-embedding ledger I/O — Delta read/split/upsert for the per-label cache.

When enabled, skips ai_query for rows whose `embedding_text_hash` and
`embedding_model` haven't changed since the last successful run. Narrow
exception handling (`AnalysisException` only) — any other failure is signal.
Each label gets its own Delta path so table, column, schema, database, and
value embeddings can be invalidated independently.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dbxcarta.spark.contract import NodeLabel
    from pyspark.sql import DataFrame, SparkSession

logger = logging.getLogger(__name__)


def read_ledger(spark: SparkSession, ledger_root: str, label: NodeLabel) -> DataFrame | None:
    """Return the ledger DataFrame for label, or None if it doesn't exist yet.

    Catches only AnalysisException, which is what Spark raises when the Delta
    path doesn't exist. Other failures (permission denied, corrupt metadata)
    propagate as signal.
    """
    from pyspark.errors import AnalysisException

    ledger_path = f"{ledger_root.rstrip('/')}/{label.value.lower()}"
    try:
        return spark.read.format("delta").load(ledger_path)
    except AnalysisException:
        return None


def split_by_ledger(
    df_hashed: DataFrame,
    ledger_df: DataFrame,
    endpoint: str,
) -> tuple[DataFrame, DataFrame]:
    """Split df_hashed into (hits_df, misses_df) against the ledger.

    A hit requires: the ledger has a row with the same id, the same
    embedding_model as the current endpoint, and a matching embedding_text_hash.
    Hits carry five _led_* columns from the ledger row. Misses have those
    columns dropped so the result is schema-compatible with the original df.
    """
    from pyspark.sql.functions import col

    ledger_filtered = ledger_df.filter(col("embedding_model") == endpoint).select(
        col("id").alias("_led_id"),
        col("embedding_text_hash").alias("_led_hash"),
        col("embedding").alias("_led_embedding"),
        col("embedding_model").alias("_led_model"),
        col("embedded_at").alias("_led_embedded_at"),
    )

    joined = df_hashed.join(
        ledger_filtered,
        df_hashed["id"] == ledger_filtered["_led_id"],
        "left",
    )
    hit_cond = col("_led_id").isNotNull() & (col("_curr_hash") == col("_led_hash"))

    ledger_cols = [
        "_curr_hash",
        "_led_id",
        "_led_hash",
        "_led_embedding",
        "_led_model",
        "_led_embedded_at",
    ]
    hits_df = joined.filter(hit_cond)
    misses_df = joined.filter(~hit_cond).drop(*ledger_cols)

    return hits_df, misses_df


def upsert_ledger(staged_df: DataFrame, ledger_root: str, label: NodeLabel) -> None:
    """Upsert newly-embedded rows (excluding errors) into the per-label ledger.

    Merge key: (id, embedding_model). Rows where embedding_error is non-null
    are excluded so failed rows are re-attempted on every subsequent run.
    Schema: id STRING, embedding_text_hash STRING, embedding ARRAY<DOUBLE>,
    embedding_model STRING, embedded_at TIMESTAMP.
    """
    from delta.tables import DeltaTable  # type: ignore[import-not-found]
    from pyspark.errors import AnalysisException
    from pyspark.sql.functions import col

    ledger_path = f"{ledger_root.rstrip('/')}/{label.value.lower()}"
    spark = staged_df.sparkSession

    # Deduplicate on merge key — Delta MERGE requires at most one source row per
    # target row; while node IDs should be unique in practice, guard explicitly.
    rows_to_upsert = (
        staged_df.filter(col("embedding_error").isNull())
        .select("id", "embedding_text_hash", "embedding", "embedding_model", "embedded_at")
        .dropDuplicates(["id", "embedding_model"])
    )

    # forPath raises AnalysisException when the Delta path doesn't exist yet.
    try:
        existing = DeltaTable.forPath(spark, ledger_path)
    except AnalysisException:
        (rows_to_upsert.write.format("delta").mode("overwrite").save(ledger_path))
        logger.info("[dbxcarta] created ledger for %s at %s", label.value, ledger_path)
        return

    (
        existing.alias("existing")
        .merge(
            rows_to_upsert.alias("updates"),
            "existing.id = updates.id AND existing.embedding_model = updates.embedding_model",
        )
        .whenMatchedUpdateAll()
        .whenNotMatchedInsertAll()
        .execute()
    )
    logger.info("[dbxcarta] upserted ledger for %s at %s", label.value, ledger_path)
