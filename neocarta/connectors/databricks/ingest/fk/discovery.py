"""FK discovery orchestrator: declared foreign keys only.

Pipeline boundary for the connector's FK-discovery work. Declared FK is read
from `information_schema` as a bounded Spark frame and projected to the
canonical REFERENCES schema. Produces `FKDiscoveryResult` — a ready-to-write
REFERENCES DataFrame tagged with `EdgeSource.DECLARED`.

Heuristic (inferred) foreign keys are intentionally NOT computed here. That
capability lives in neocarta's enrichment layer
(`neocarta.enrichment.foreign_keys`), run in-process over the loaded graph,
so the connector only ingests catalog facts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import neocarta.connectors.databricks.ingest.schema_graph as sg
from neocarta.connectors.databricks.ingest.fk.declared import discover_declared
from neocarta.connectors.databricks.ingest.summary import FKSkipCounts, RunSummary

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

    from neocarta.connectors.databricks.settings import SparkIngestSettings

logger = logging.getLogger(__name__)


@dataclass
class FKDiscoveryResult:
    """Post-discovery DataFrame ready for the Neo4j REFERENCES write.

    `declared_edges_df` is None when no declared FKs were found (or discovery
    was gated off). The pipeline's load step skips the write when it is None.
    """

    declared_edges_df: DataFrame | None
    declared_edge_count: int


def run_fk_discovery(
    spark: SparkSession,
    settings: SparkIngestSettings,
    schema_list: list[str],
    summary: RunSummary,
) -> FKDiscoveryResult:
    """Read declared FKs and project them to the canonical REFERENCES schema."""
    if _fk_guardrail_tripped(settings, summary):
        return _skipped_result()

    declared_edges, declared_counters = discover_declared(spark, settings, schema_list)
    summary.fk_declared = declared_counters
    declared_edges_df = sg.build_references_rel(spark, declared_edges) if declared_edges else None
    return FKDiscoveryResult(
        declared_edges_df=declared_edges_df,
        declared_edge_count=len(declared_edges),
    )


def _fk_guardrail_tripped(
    settings: SparkIngestSettings,
    summary: RunSummary,
) -> bool:
    """Skip FK discovery when the catalog is absurdly wide.

    `fk_max_columns == 0` disables the guardrail. Otherwise, skip
    when the extracted column count exceeds it and record the trip on
    `summary`. Reads the already-materialized `summary.extract.columns`
    scalar, so no driver action is added.
    """
    limit = settings.fk_max_columns
    if limit <= 0:
        return False
    columns = summary.extract.columns
    if columns <= limit:
        return False
    logger.warning(
        "[databricks] FK discovery skipped by guardrail: %d columns > limit %d"
        " (NEOCARTA_DATABRICKS_FK_MAX_COLUMNS)",
        columns,
        limit,
    )
    summary.fk_skip = FKSkipCounts(column_count=columns, column_limit=limit)
    return True


def _skipped_result() -> FKDiscoveryResult:
    """All-`None` result so the load step writes no REFERENCES edges."""
    return FKDiscoveryResult(declared_edges_df=None, declared_edge_count=0)
