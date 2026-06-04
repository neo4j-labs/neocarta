"""Sample value transforms: discover and sample distinct values for categorical columns.

Candidate discovery reads from the cached columns_df produced by the extract stage;
no Neo4j read occurs here. All Neo4j interaction (stale-value purge, node and
relationship writes) lives in pipeline.py.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dbxcarta.spark.contract import CONTRACT_VERSION, generate_id
from dbxcarta.spark.ingest.contract_expr import id_expr_from_columns, value_id_expr

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pyspark.sql import DataFrame, SparkSession

logger = logging.getLogger(__name__)

_SCHEMA_PROBE_LIMIT = 3


@dataclass
class SampleStats:
    candidate_columns: int
    sampled_columns: int
    skipped_columns: int
    skipped_schemas: int
    cardinality_failed_tables: int
    cardinality_wall_clock_ms: int
    sample_wall_clock_ms: int
    value_nodes: int
    has_value_edges: int
    cardinality_min: int | None = None
    cardinality_p25: int | None = None
    cardinality_p50: int | None = None
    cardinality_p75: int | None = None
    cardinality_p95: int | None = None
    cardinality_max: int | None = None


@dataclass
class TableCandidate:
    catalog: str
    schema_name: str
    table_name: str
    column_names: list[str]
    column_ids: list[str]

    def fq(self) -> str:
        return f"`{self.catalog}`.`{self.schema_name}`.`{self.table_name}`"


def sample(
    spark: SparkSession,
    columns_df: DataFrame,
    catalog: str,
    schema_list: list[str],
    sample_limit: int,
    cardinality_threshold: int,
    stack_chunk_size: int,
) -> tuple[DataFrame, DataFrame, SampleStats, DataFrame | None]:
    """Discover and sample distinct values for STRING/BOOLEAN columns.

    Returns (value_node_df, has_value_rel_df, stats, cache_handle). DataFrames
    may be empty when no qualifying values are found; check stats.value_nodes
    before writing. value_node_df carries `catalog`/`schema` (the run-stamp
    scoped delete keys on them); `table` rides along so the per-chunk Value
    write can be filtered to the same table range as its Column write.

    cache_handle is the cached sampled-value DataFrame on the success path, or
    None when nothing was cached (no rows, or zero value nodes — that path
    unpersists before returning). The caller must unpersist the handle only
    after both FK discovery and the Neo4j load have finished reading it, so the
    cache is not released here on the success path.
    """
    from pyspark.sql.functions import col, lit
    from pyspark.sql.types import LongType, StringType, StructField, StructType

    # `embedding_text` mirrors the VALUE embedding-text expression
    # (contract.EMBEDDING_TEXT_EXPR[VALUE] == "value"): a transient copy of
    # the `value` column so the embed stage is uniform across labels. The
    # fail-closed write boundary strips it; `value` stays a declared
    # property in its own right.
    value_schema = StructType(
        [
            StructField("id", StringType(), nullable=False),
            StructField("value", StringType()),
            StructField("count", LongType()),
            StructField("catalog", StringType()),
            StructField("schema", StringType()),
            StructField("table", StringType()),
            StructField("contract_version", StringType()),
            StructField("embedding_text", StringType()),
        ]
    )
    rel_schema = StructType(
        [
            StructField("source_id", StringType(), nullable=False),
            StructField("target_id", StringType(), nullable=False),
        ]
    )

    candidates = _candidates_from_columns_df(columns_df, schema_list)
    total_candidate_cols = sum(len(c.column_names) for c in candidates)

    candidates, skipped_schemas = _filter_readable_schemas(spark, candidates)

    t0 = time.perf_counter_ns()
    sampled_candidates, cardinality_values, cardinality_failed = _cardinality_filter(
        spark,
        candidates,
        cardinality_threshold,
        stack_chunk_size,
    )
    cardinality_wall_ms = (time.perf_counter_ns() - t0) // 1_000_000
    sampled_cols = sum(len(c.column_names) for c in sampled_candidates)

    t0 = time.perf_counter_ns()
    raw_df = _sample_values(spark, sampled_candidates, sample_limit, stack_chunk_size)
    sample_wall_ms = (time.perf_counter_ns() - t0) // 1_000_000

    stats = SampleStats(
        candidate_columns=total_candidate_cols,
        sampled_columns=sampled_cols,
        skipped_columns=total_candidate_cols - sampled_cols,
        skipped_schemas=skipped_schemas,
        cardinality_failed_tables=cardinality_failed,
        cardinality_wall_clock_ms=cardinality_wall_ms,
        sample_wall_clock_ms=sample_wall_ms,
        value_nodes=0,
        has_value_edges=0,
    )
    _add_cardinality_stats(stats, cardinality_values)

    if raw_df is None:
        logger.warning("[dbxcarta] no value rows produced")
        return (
            spark.createDataFrame([], schema=value_schema),
            spark.createDataFrame([], schema=rel_schema),
            stats,
            None,
        )

    # Cache raw_df so the two .count() actions and the downstream Neo4j writes
    # all read from Spark cache instead of re-running the window shuffle and
    # N UC table queries on every action.
    raw_df = raw_df.cache()
    vid_expr = value_id_expr()

    value_node_df = raw_df.select(
        vid_expr.alias("id"),
        col("val").alias("value"),
        col("cnt").alias("count"),
        col("tbl_catalog").alias("catalog"),
        col("tbl_schema").alias("schema"),
        col("tbl_name").alias("table"),
        lit(CONTRACT_VERSION).alias("contract_version"),
        col("val").alias("embedding_text"),
    ).dropDuplicates(["id"])
    has_value_df = raw_df.select(
        col("col_id").alias("source_id"),
        vid_expr.alias("target_id"),
    )

    stats.value_nodes = value_node_df.count()  # materializes raw_df into cache
    if stats.value_nodes == 0:
        raw_df.unpersist()
        logger.warning("[dbxcarta] no value rows produced")
        return (
            spark.createDataFrame([], schema=value_schema),
            spark.createDataFrame([], schema=rel_schema),
            stats,
            None,
        )
    stats.has_value_edges = has_value_df.count()  # reads from cache

    return (value_node_df, has_value_df, stats, raw_df)


def _candidates_from_columns_df(
    columns_df: DataFrame,
    schema_list: list[str],
) -> list[TableCandidate]:
    """Build TableCandidate list from the extract-stage columns DataFrame.

    Filters to STRING/BOOLEAN data types in memory. The extract stage already
    applies schema_list filtering, but we re-apply it here as a defensive guard
    so the function is correct when called with an unfiltered DataFrame in tests.
    """
    from pyspark.sql.functions import col, collect_list

    df = columns_df.filter(col("data_type").isin("STRING", "BOOLEAN"))
    if schema_list:
        df = df.filter(col("table_schema").isin(schema_list))

    rows = (
        df.groupBy("table_catalog", "table_schema", "table_name")
        .agg(collect_list("column_name").alias("column_names"))
        .orderBy("table_catalog", "table_schema", "table_name")
        .collect()
    )

    out: list[TableCandidate] = []
    for row in rows:
        cat = row["table_catalog"]
        sch = row["table_schema"]
        tbl = row["table_name"]
        names: list[str] = list(row["column_names"])
        # IDs are computed from generate_id(), byte-identical to id_expr() in Spark.
        ids = [generate_id(cat, sch, tbl, name) for name in names]
        out.append(
            TableCandidate(
                catalog=cat,
                schema_name=sch,
                table_name=tbl,
                column_names=names,
                column_ids=ids,
            )
        )
    return out


def _chunk[T](lst: list[T], n: int) -> Iterator[list[T]]:
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def _cardinality_query(fq_table: str, column_names: list[str]) -> str:
    aggs = ", ".join(
        f"approx_count_distinct(`{c}`) AS `card_{i}`" for i, c in enumerate(column_names)
    )
    return f"SELECT {aggs} FROM {fq_table}"


def _sample_query(fq_table: str, column_names: list[str]) -> str:
    n = len(column_names)
    quote = chr(39)
    stack_expr = ", ".join(
        f"'{c.replace(quote, quote * 2)}', CAST(`{c}` AS STRING)" for c in column_names
    )
    return (
        f"SELECT col_name, val, COUNT(*) AS cnt"
        f"  FROM {fq_table}"
        f"  LATERAL VIEW STACK({n}, {stack_expr}) t AS col_name, val"
        f" WHERE val IS NOT NULL AND val <> ''"
        f" GROUP BY col_name, val"
    )


def _cardinality_filter(
    spark: SparkSession,
    candidates: list[TableCandidate],
    threshold: int,
    chunk_size: int,
) -> tuple[list[TableCandidate], list[int], int]:
    """Return (filtered candidates, observed cardinalities, failed-table count)."""
    from py4j.protocol import Py4JJavaError  # type: ignore[import-untyped]
    from pyspark.errors import AnalysisException

    kept: list[TableCandidate] = []
    all_cards: list[int] = []
    failed_tables = 0
    for cand in candidates:
        kept_names: list[str] = []
        kept_ids: list[str] = []
        id_by_name = dict(zip(cand.column_names, cand.column_ids, strict=False))
        table_failed = False
        for chunk_index, chunk_cols in enumerate(_chunk(cand.column_names, chunk_size)):
            try:
                query = _cardinality_query(cand.fq(), chunk_cols)
                row = spark.sql(query).collect()[0]
                for i, name in enumerate(chunk_cols):
                    card = int(row[f"card_{i}"])
                    all_cards.append(card)
                    if card < threshold:
                        kept_names.append(name)
                        kept_ids.append(id_by_name[name])
            except (AnalysisException, Py4JJavaError) as exc:
                table_failed = True
                logger.warning(
                    "[dbxcarta] cardinality probe failed for %s chunk=%d cols=%s: %s",
                    cand.fq(),
                    chunk_index,
                    chunk_cols,
                    exc,
                )
                continue
        if table_failed:
            failed_tables += 1
        if kept_names:
            kept.append(
                TableCandidate(
                    catalog=cand.catalog,
                    schema_name=cand.schema_name,
                    table_name=cand.table_name,
                    column_names=kept_names,
                    column_ids=kept_ids,
                )
            )
    return kept, all_cards, failed_tables


def _sample_values(
    spark: SparkSession,
    candidates: list[TableCandidate],
    limit: int,
    chunk_size: int,
) -> DataFrame | None:
    """Return top-`limit` distinct values per column as a Spark DataFrame.

    Columns: col_id, col_name, val, cnt. Returns None when all table queries
    fail. Per-column top-N is applied via a window function so no value rows
    are collected to the driver (best-practices Spark §5).
    """
    from py4j.protocol import Py4JJavaError
    from pyspark.errors import AnalysisException
    from pyspark.sql.functions import col, lit, row_number
    from pyspark.sql.window import Window

    dfs = []
    for cand in candidates:
        for chunk_index, chunk_cols in enumerate(_chunk(cand.column_names, chunk_size)):
            try:
                query = _sample_query(cand.fq(), chunk_cols)
                chunk_df = (
                    spark.sql(query)
                    .withColumn(
                        "col_id",
                        id_expr_from_columns(
                            lit(cand.catalog),
                            lit(cand.schema_name),
                            lit(cand.table_name),
                            col("col_name"),
                        ),
                    )
                    .withColumn("tbl_catalog", lit(cand.catalog))
                    .withColumn("tbl_schema", lit(cand.schema_name))
                    .withColumn("tbl_name", lit(cand.table_name))
                )
                dfs.append(chunk_df)
            except (AnalysisException, Py4JJavaError) as exc:
                logger.warning(
                    "[dbxcarta] sampling failed for %s chunk=%d cols=%s: %s",
                    cand.fq(),
                    chunk_index,
                    chunk_cols,
                    exc,
                )

    if not dfs:
        return None

    raw_df = dfs[0]
    for df in dfs[1:]:
        raw_df = raw_df.unionByName(df)

    w = Window.partitionBy("col_id").orderBy(col("cnt").desc())
    top_n: DataFrame = (
        raw_df.withColumn("_rn", row_number().over(w)).filter(col("_rn") <= limit).drop("_rn")
    )
    return top_n


def _filter_readable_schemas(
    spark: SparkSession,
    candidates: list[TableCandidate],
) -> tuple[list[TableCandidate], int]:
    """Probe up to K tables per schema; drop schemas where all probes fail."""
    from py4j.protocol import Py4JJavaError
    from pyspark.errors import AnalysisException

    by_schema: dict[tuple[str, str], list[TableCandidate]] = {}
    for c in candidates:
        by_schema.setdefault((c.catalog, c.schema_name), []).append(c)

    readable: list[TableCandidate] = []
    skipped = 0
    for (cat, sch), cands in by_schema.items():
        probes = cands[:_SCHEMA_PROBE_LIMIT]
        last_exc: AnalysisException | Py4JJavaError | None = None
        readable_schema = False
        for probe in probes:
            try:
                spark.sql(f"SELECT 1 FROM {probe.fq()} LIMIT 1").collect()
                readable_schema = True
                break
            except (AnalysisException, Py4JJavaError) as exc:
                last_exc = exc
                continue
        if not readable_schema:
            skipped += 1
            logger.warning(
                "[dbxcarta] skipping schema %s.%s (%d probes failed, last: %s)",
                cat,
                sch,
                len(probes),
                last_exc,
            )
            continue
        readable.extend(cands)
    return readable, skipped


def _add_cardinality_stats(stats: SampleStats, values: list[int]) -> None:
    if not values:
        return
    s = sorted(values)

    def _pct(p: float) -> int:
        idx = min(len(s) - 1, max(0, round(p * (len(s) - 1))))
        return int(s[idx])

    stats.cardinality_min = int(s[0])
    stats.cardinality_p25 = _pct(0.25)
    stats.cardinality_p50 = _pct(0.50)
    stats.cardinality_p75 = _pct(0.75)
    stats.cardinality_p95 = _pct(0.95)
    stats.cardinality_max = int(s[-1])
