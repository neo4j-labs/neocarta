"""Sample-values transform stage.

Samples distinct column values and returns the sampled-value frames. This
stage no longer writes Value nodes or purges stale ones: the Value embed +
Neo4j write is folded into the table-range chunk loop (so a Value slice
embeds and writes alongside its Column slice), and stale-Value cleanup is a
single scoped server-side Cypher delete keyed on the run-start stamp. The
un-embedded sampled frame is returned whole for that per-chunk write, for
FK discovery, and for the HAS_VALUE relationship write in `_load`, so value
sampling stays a single bounded pass.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import dbxcarta.spark.ingest.transform.sample_values as sv
from dbxcarta.spark.ingest.summary import RunSummary, SampleValueCounts

if TYPE_CHECKING:
    from dbxcarta.spark.ingest.extract import ExtractResult
    from dbxcarta.spark.settings import SparkIngestSettings
    from pyspark.sql import DataFrame, SparkSession

logger = logging.getLogger(__name__)


@dataclass
class ValueResult:
    """Sample-values output passed from transform into the chunk loop, FK
    discovery, and load.

    The pipeline uses `None` instead of an empty ValueResult when sampling is
    disabled, so downstream branches can cleanly skip Value nodes and HAS_VALUE
    relationships without inspecting Spark DataFrames. `value_node_df` is the
    un-embedded sampled frame: the chunk loop slices it per table range to
    embed+write the Value nodes, FK discovery joins on sampled values (never
    the embedding vector), and `_load` writes HAS_VALUE from it.
    """

    value_node_df: DataFrame
    has_value_df: DataFrame
    sample_stats: sv.SampleStats
    # Cached sampled-value DataFrame backing value_node_df and has_value_df.
    # None when nothing was cached. The pipeline releases this only after the
    # chunk-loop Value writes, FK discovery, and the Neo4j load have finished,
    # mirroring ExtractResult.unpersist_cached().
    cache_handle: DataFrame | None = None

    def unpersist_cached(self) -> None:
        """Release the cached sampled-value DataFrame after the ingest run.

        Sampling caches raw_df because the per-chunk Value writes, FK
        discovery, and the HAS_VALUE write all read it. The pipeline calls
        this once those steps no longer need the cache. Idempotent and a
        no-op when nothing cached.
        """
        if self.cache_handle is not None:
            self.cache_handle.unpersist()


def transform_sample_values(
    spark: SparkSession,
    settings: SparkIngestSettings,
    schema_list: list[str],
    extract_result: ExtractResult,
    summary: RunSummary,
) -> ValueResult | None:
    """Sample distinct values and return the sampled-value frames.

    Sampling-only: the Value embed + Neo4j write now happens in the
    table-range chunk loop, and stale-Value cleanup is a single scoped
    server-side delete after the loop. Returns None when
    DBXCARTA_INCLUDE_VALUES is off; the Settings cross-field validator
    already rejects the embedding-values-without-include-values incoherence,
    so no warning branch is needed here.

    Value sampling is a single bounded pass (sample_limit + the cardinality
    threshold, not the n² FK blowup); the whole un-embedded frame is returned
    so the chunk loop can slice it by table range.
    """
    if not settings.dbxcarta_include_values:
        return None

    value_node_df, has_value_df, sample_stats, cache_handle = sv.sample(
        spark,
        extract_result.columns_df,
        settings.dbxcarta_catalog,
        schema_list,
        settings.dbxcarta_sample_limit,
        settings.dbxcarta_sample_cardinality_threshold,
        settings.dbxcarta_stack_chunk_size,
    )
    summary.sample_values = SampleValueCounts.from_sample_stats(sample_stats)
    logger.info(
        "[dbxcarta] sample values: candidates=%d sampled=%d value_nodes=%d",
        sample_stats.candidate_columns,
        sample_stats.sampled_columns,
        sample_stats.value_nodes,
    )

    return ValueResult(
        value_node_df=value_node_df,
        has_value_df=has_value_df,
        sample_stats=sample_stats,
        cache_handle=cache_handle,
    )
