"""Batch SQL generation via ai_query (best-practices Spark §1 and §4)."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

from dbxcarta.core.identifiers import quote_qualified_name, validate_serving_endpoint_name

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

logger = logging.getLogger(__name__)


def _input_hash(endpoint: str, arm: str, questions_with_prompts: list[dict]) -> str:
    """Stable hash of everything that determines the model output.

    Question order is preserved (not sorted) because it is deterministic from
    the loaded question set; any change to a prompt, the endpoint name, the
    arm, or the set/order of questions changes the hash and invalidates the
    cache by construction.
    """
    payload = json.dumps(
        {
            "endpoint": endpoint,
            "arm": arm,
            "items": [[q["question_id"], q["prompt"]] for q in questions_with_prompts],
        },
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _results_from_rows(rows: list) -> dict[str, tuple[str | None, str | None]]:
    results: dict[str, tuple[str | None, str | None]] = {}
    for row in rows:
        qid = row["question_id"]
        response = row["response"]
        if response is None:
            results[qid] = (None, "ai_query returned null struct")
        else:
            error = response["errorMessage"]
            results[qid] = (response["result"], error or None)
    return results


def _read_cached(
    spark: SparkSession,
    full_table: str,
    want_hash: str,
    want_ids: set[str],
) -> dict[str, tuple[str | None, str | None]] | None:
    """Return prior responses if the staging table matches this exact input.

    A miss (table absent, pre-cache schema, different input hash, or a
    different question set) returns None so the caller re-infers.
    """
    try:
        df: DataFrame = spark.table(full_table)
    except Exception:
        return None
    if "_input_hash" not in df.columns:
        return None
    rows = df.collect()
    if not rows:
        return None
    if {r["_input_hash"] for r in rows} != {want_hash}:
        return None
    if {r["question_id"] for r in rows} != want_ids:
        return None
    return _results_from_rows(rows)


def generate_sql_batch(
    spark: SparkSession,
    endpoint: str,
    questions_with_prompts: list[dict],
    staging_table: str,
    arm: str,
    *,
    refresh: bool = False,
) -> dict[str, tuple[str | None, str | None]]:
    """Generate SQL for every question in one ai_query pass.

    *questions_with_prompts* is a list of dicts with keys ``question_id``
    and ``prompt``.  Returns a mapping from question_id to
    ``(sql_text, error_message)``.

    Results are cached in the per-arm staging Delta table keyed by an input
    hash; an identical re-run (same endpoint, arm, and question prompts) skips
    ai_query entirely and reuses the prior responses. Pass ``refresh=True`` to
    force re-inference (e.g. the endpoint's model changed but prompts did not).

    Materializes to a UC-managed Delta table after ai_query (best-practices
    Spark §4) so the downstream execute loop never re-triggers inference.
    """
    # Guard before interpolation: ai_query requires the endpoint as a string
    # literal. validate_serving_endpoint_name rejects characters that would
    # break the SQL expression.
    validate_serving_endpoint_name(endpoint)

    from pyspark.sql import Row
    from pyspark.sql.functions import expr, lit

    full_table = quote_qualified_name(f"{staging_table}_{arm}", expected_parts=3)
    want_hash = _input_hash(endpoint, arm, questions_with_prompts)
    want_ids = {q["question_id"] for q in questions_with_prompts}

    if not refresh:
        cached = _read_cached(spark, full_table, want_hash, want_ids)
        if cached is not None:
            logger.info(
                "[dbxcarta] %s: cache hit, skipping ai_query (%d questions)",
                arm,
                len(want_ids),
            )
            return cached

    logger.info(
        "[dbxcarta] %s: running ai_query for %d questions",
        arm,
        len(want_ids),
    )
    rows = [Row(question_id=q["question_id"], prompt=q["prompt"]) for q in questions_with_prompts]
    df = spark.createDataFrame(rows)

    enriched = df.withColumn(
        "response",
        expr(f"ai_query('{endpoint}', prompt, failOnError => false)"),
    ).withColumn("_input_hash", lit(want_hash))

    (
        enriched.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(full_table)
    )

    return _results_from_rows(spark.table(full_table).collect())
