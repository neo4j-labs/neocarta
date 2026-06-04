"""RetrievalTrace: per-question diagnostic record for the graph_rag arm."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from dbxcarta.client.ids import schema_from_node_id
from dbxcarta.core.identifiers import quote_qualified_name

if TYPE_CHECKING:
    from pyspark.sql import SparkSession


def schema_scores_from_seeds(
    col_seed_ids: list[str],
    col_seed_scores: list[float],
    tbl_seed_ids: list[str],
    tbl_seed_scores: list[float],
) -> dict[str, float]:
    """Aggregate seed scores onto schemas, normalized per vector index first."""
    raw: dict[str, float] = {}
    for scores in (
        _normalized_schema_scores(col_seed_ids, col_seed_scores),
        _normalized_schema_scores(tbl_seed_ids, tbl_seed_scores),
    ):
        for schema, score in scores.items():
            raw[schema] = raw.get(schema, 0.0) + score
    total = sum(raw.values()) or 1.0
    return {k: v / total for k, v in raw.items()}


def _normalized_schema_scores(
    seed_ids: list[str],
    seed_scores: list[float],
) -> dict[str, float]:
    raw: dict[str, float] = {}
    for node_id, score in zip(seed_ids, seed_scores, strict=False):
        schema = schema_from_node_id(node_id)
        if schema:
            raw[schema] = raw.get(schema, 0.0) + score
    total = sum(raw.values()) or 1.0
    return {schema: score / total for schema, score in raw.items()}


def chosen_schemas_from_columns(
    columns: list,
) -> list[str]:
    """Return deduplicated schemas present in the final column set, in order."""
    seen: set[str] = set()
    result: list[str] = []
    for col in columns:
        schema = schema_from_node_id(col.table_fqn)
        if schema and schema not in seen:
            seen.add(schema)
            result.append(schema)
    return result


@dataclass
class RetrievalTrace:
    run_id: str
    question_id: str
    question: str
    target_schema: str | None
    col_seed_ids: list[str]
    col_seed_scores: list[float]
    tbl_seed_ids: list[str]
    tbl_seed_scores: list[float]
    schema_scores: dict[str, float]
    chosen_schemas: list[str]
    expansion_tbl_ids: list[str]
    final_col_ids: list[str]
    rendered_context: str
    generated_sql: str | None = None
    reference_sql: str | None = None
    parsed: bool = False
    executed: bool = False
    correct: bool = False
    execution_error: str | None = None
    top1_schema_match: bool | None = None
    schema_in_context: bool | None = None
    context_purity: float | None = None


def compute_retrieval_metrics(trace: RetrievalTrace) -> None:
    """Compute top1_schema_match, schema_in_context, context_purity in-place."""
    if not trace.target_schema:
        return
    if trace.schema_scores:
        top1 = max(trace.schema_scores, key=trace.schema_scores.__getitem__)
        trace.top1_schema_match = top1 == trace.target_schema
    trace.schema_in_context = trace.target_schema in trace.chosen_schemas
    if trace.final_col_ids:
        from_target = sum(
            1 for cid in trace.final_col_ids if schema_from_node_id(cid) == trace.target_schema
        )
        trace.context_purity = from_target / len(trace.final_col_ids)


def emit_retrieval_traces(
    spark: SparkSession,
    traces: list[RetrievalTrace],
    table_name: str,
) -> None:
    if not traces:
        return

    from pyspark.sql import Row
    from pyspark.sql.types import (
        ArrayType,
        BooleanType,
        DoubleType,
        MapType,
        StringType,
        StructField,
        StructType,
    )

    schema = StructType(
        [
            StructField("run_id", StringType(), nullable=False),
            StructField("question_id", StringType()),
            StructField("question", StringType()),
            StructField("target_schema", StringType()),
            StructField("col_seed_ids", ArrayType(StringType())),
            StructField("col_seed_scores", ArrayType(DoubleType())),
            StructField("tbl_seed_ids", ArrayType(StringType())),
            StructField("tbl_seed_scores", ArrayType(DoubleType())),
            StructField("schema_scores", MapType(StringType(), DoubleType())),
            StructField("chosen_schemas", ArrayType(StringType())),
            StructField("expansion_tbl_ids", ArrayType(StringType())),
            StructField("final_col_ids", ArrayType(StringType())),
            StructField("rendered_context", StringType()),
            StructField("generated_sql", StringType()),
            StructField("reference_sql", StringType()),
            StructField("parsed", BooleanType()),
            StructField("executed", BooleanType()),
            StructField("correct", BooleanType()),
            StructField("execution_error", StringType()),
            StructField("top1_schema_match", BooleanType()),
            StructField("schema_in_context", BooleanType()),
            StructField("context_purity", DoubleType()),
        ]
    )

    rows = [
        Row(
            run_id=t.run_id,
            question_id=t.question_id,
            question=t.question,
            target_schema=t.target_schema,
            col_seed_ids=t.col_seed_ids,
            col_seed_scores=t.col_seed_scores,
            tbl_seed_ids=t.tbl_seed_ids,
            tbl_seed_scores=t.tbl_seed_scores,
            schema_scores=t.schema_scores,
            chosen_schemas=t.chosen_schemas,
            expansion_tbl_ids=t.expansion_tbl_ids,
            final_col_ids=t.final_col_ids,
            rendered_context=t.rendered_context,
            generated_sql=t.generated_sql,
            reference_sql=t.reference_sql,
            parsed=t.parsed,
            executed=t.executed,
            correct=t.correct,
            execution_error=t.execution_error,
            top1_schema_match=t.top1_schema_match,
            schema_in_context=t.schema_in_context,
            context_purity=t.context_purity,
        )
        for t in traces
    ]

    quoted = quote_qualified_name(table_name, expected_parts=3)
    (
        spark.createDataFrame(rows, schema=schema)
        .write.format("delta")
        .mode("append")
        .option("mergeSchema", "true")
        .saveAsTable(quoted)
    )
